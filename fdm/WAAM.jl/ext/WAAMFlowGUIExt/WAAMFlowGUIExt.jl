"""
WAAMFlowGUIExt — scientific front end for WAAMFlow.

## Architecture

The solver stays in `WAAMFlow`; this extension is a **thin server**: it serves a
self-contained scientific front end (no CDN, no build step, no JS framework) over
stdlib `Sockets` and streams every solved timestep to the browser as JSON over a
WebSocket. The browser renders the fields (2-D heatmaps, section views, history
charts) on a canvas — no OpenGL context on the Julia side, so the UI runs where
CPU-only containers run everything else.

Dependencies: `JSON` (weakdep trigger) + stdlib `Sockets`, `SHA`, `Base64`.
No downloads at launch: the front end ships as three static files that are read
into memory at load (`index.html`, `app.css`, `app.js` next to this module).

## Launch

From the package directory (`fdm/WAAM.jl`), **`-t 2` or more is required** — the
solver producer must run concurrently with the network server, and on a single
thread the browser would only update when the physics yields:

```julia
julia -t 2 --project=gui -e '
    using WAAMFlow, JSON
    ext = Base.get_extension(WAAMFlow, :WAAMFlowGUIExt)
    ext.serve(; port = 8751, open = true)
    wait()'
```

`ext.serve()` starts the loop and returns; call `Base.wait()` (or `ext.launch()`,
which does everything and blocks). The URL is printed once the server listens.

## Endpoints

| Route | Meaning |
| --- | --- |
| `GET /` | the front end |
| `GET /app.css`, `/app.js` | static assets |
| `GET /api/defaults` | `RunConfig` defaults as JSON |
| `GET /api/materials` | the alloy registry summary |
| `GET /api/material?alloy=…` | one alloy: properties + sampled curves + process audit |
| `GET /api/audit?alloy&mode` | energy split audit (Mode A / B) |
| `GET /api/mesh?…` | mesh preview counts for a domain config |
| `POST /api/run` | start a single-track run (409 if one is active) |
| `POST /api/pause` | `{"pause": true\|false}` |
| `POST /api/stop` | cancel the active run |
| `GET /api/history` | run history rows (CSV or JSON by `Accept`) |
| `WS /ws` | snapshot stream: `{type:snap,done,audit,status,…}` |

The producer mirrors `run_track`'s step body (the tier-1 validated path, Mode A
surface share) and reports the deposited droplet share it does **not** inject, so
the tier's known limitation stays visible in the UI.
"""
module WAAMFlowGUIExt

import WAAMFlow
import JSON
using Sockets
using SHA
using Base64
using Printf
using Base.Threads: @spawn, nthreads

using WAAMFlow: ProcessParameters, RunConfig, EnergySplit, EnergyWorkspace,
                CartesianGrid, metrics, graded_axis, get_material, arc_flux!,
                arc_source!, surface_loss!, solve_energy!, energy_residual,
                arc_power_delivered, timestep, TimestepController,
                latent_heat_fraction, bead_geometry, wire_feed_mass_rate,
                arc_power, droplet_heat, sigma_q, energy_budget, material_report,
                dgamma_dT, kcond, visc, Cp_s_ref, Cp_l_ref, liquid_fraction

const LOCK = ReentrantLock()
const GUI = `_gui_state`

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

mutable struct Session
    server::Union{Nothing,Sockets.TCPServer}
    port::Int
    status::Symbol               # :idle | :running | :paused | :finished | :error
    status_msg::String
    clients::Dict{Int,Sockets.TCPSocket}
    next_client::Int
    run_task::Union{Nothing,Task}
    stop::Bool
    pause::Bool
    cfg::Vector{UInt8}           # last accepted POST /api/run body
    history::Vector{Any}         # per-snapshot compact rows (for export)
    last_manifest::String
    Session() = new(nothing, 0, :idle, "", Dict{Int,Sockets.TCPSocket}(), 0,
                    nothing, false, false, UInt8[], Any[], "")
end

_gui_state = Session()
GUI = _gui_state

# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------

const ASSETS = Dict{String,String}()

function _load_assets!
    dir = @__DIR__
    ASSETS["/"] = read(joinpath(dir, "index.html"), String)
    ASSETS["/app.css"] = read(joinpath(dir, "app.css"), String)
    ASSETS["/app.js"] = read(joinpath(dir, "app.js"), String)
    nothing
end

"base HTTP response with the common headers"
function _respond(sock, code::Int, ctype::String, body::AbstractString)
    reason = code == 200 ? "OK" :
             code == 404 ? "Not Found" :
             code == 409 ? "Conflict" :
             code == 400 ? "Bad Request" : "Error"
    header = "HTTP/1.1 $code $reason\r\n" *
             "Content-Type: $ctype; charset=utf-8\r\n" *
             "Cache-Control: no-store\r\n" *
             "Content-Length: $(ncodeunits(body))\r\n" *
             "Connection: close\r\n\r\n"
    write(sock, header)
    write(sock, body)
    flush(sock)
end

const MIME_JSON = "application/json"
const MIME_TEXT = "text/plain"

# ---------------------------------------------------------------------------
# WebSocket codec (RFC 6455, the subset a browser uses)
# ---------------------------------------------------------------------------

const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

"Sec-WebSocket-Accept for a `Sec-WebSocket-Key`"
function _ws_accept(key::AbstractString)
    digest = SHA.sha1_bytes(string(key, WS_GUID))
    # SHA.sha1_bytes returns UInt8[]; Base64.encode wants the raw bytes
    digital = String(digest)
    Base64.base64encode(digital)
end

"encode a server→client text frame (never masked from the server side)"
function _ws_frame_bytes(text::AbstractString)
    payload = collect(codeunits(text))
    n = length(payload)
    if n < 126
        hdr = UInt8[0x81, UInt8(n)]
    elseif n < 65536
        hdr = UInt8[0x81, 126, (n >> 8) % UInt8, (n & 0xff) % UInt8]
    else
        hdr = UInt8[0x81, 127]
        for s in 7:-1:0
            push!(hdr, UInt8((n >> (8s)) & 0xff))
        end
    end
    append!(hdr, payload)
    hdr
end

"send a text frame, dropping the client on failure"
function _ws_send(sock, text::AbstractString)
    lock(LOCK) do
        write(sock, _ws_frame_bytes(text))
        flush(sock)
        true
    end
    true
end

"""
    _ws_read_frame(sock) -> (opcode, payload)

Read one full client frame (browsers do not fragment the tiny control traffic this
app exchanges). Masked payloads are unmasked per RFC 6455 §5.3.
"""
function _ws_read_frame(sock)
    h1 = read(sock, UInt8)
    h2 = read(sock, UInt8)
    op = h1 & 0x0f
    len = Int(h2 & 0x7f)
    if len == 126
        len = Int(read(sock, UInt8)) << 8 | Int(read(sock, UInt8))
    elseif len == 127
        len = 0
        for _ in 1:8
            len = len << 8 | Int(read(sock, UInt8))
        end
    end
    if (h2 & 0x80) != 0                       # masked (client→server always is)
        key = read(sock, 4)
        payload = read(sock, len)
        for i in 1:len
            payload[i] = payload[i] ⊻ key[(i - 1) % 4 + 1]
        end
        (op, payload)
    else
        (op, read(sock, len))
    end
end

"WebSocket pump: read control frames, keep the client alive"
function _ws_loop(sock, id::Int)
    while true
        op, payload = _ws_read_frame(sock)
        op == 0x8 && break                          # close
        op == 0x9 &&                                                # ping
            write(sock, [0x8A, UInt8(length(payload))], payload)    # pong
        op == 0xA && break                                          # invalid
        # 0x1 text payloads: reserved for future ops ({"op":…}); ignore for now
    end
    lock(GUI.lock) do
        delete!(GUI.clients, id)
        nothing
    end
    close(sock)
catch e
    e isa EOFError || e isa Base.IOError ||
        Base.showerror(stderr, e; backtrace = false) &&
        print(stderr, "\n")
    lock(GUI.lock) do
        delete!(GUI.clients, id)
        nothing
    end
    close(sock)
end

"broadcast a JSON payload to every connected browser"
function broadcast(text::AbstractString)
    lock(GUI.lock) do
        dead = Int[]
        for (id, sock) in GUI.clients
            try
                _ws_send(sock, text)
            catch
                push!(dead, id)
            end
        end
        for id in dead
            s = pop!(GUI.clients, id, nothing)
            s === nothing || close(s)
        end
        nothing
    end
    nothing
end

# ---------------------------------------------------------------------------
# JSON payloads
# ---------------------------------------------------------------------------

_r(x::Real, n::Int = 4) = round(Float64(x), digits = n)

"""registry summary for the alloy grid"""
function _materials_payload()
    al = Any[]
    for name in sort(collect(keys(WAAMFlow.MATERIALS)))
        m = get_material(name)
        dγ = dgamma_dT(m.gamma, (m.Tsol + m.Tliq) / 2)
        push!(al, (name = m.name,
                   family = String(m.family),
                   Tsol = _r(m.Tsol, 1), Tliq = _r(m.Tliq, 1),
                   mushy = _r(m.Tliq - m.Tsol, 1),
                   kTl = _r(kcond(m, m.Tliq), 2),
                   marangoni = dγ > 1e-12 ? "inward" :
                               dγ < -1e-12 ? "outward" : "neutral"))
    end
    JSON.json((alloys = al,))
end

"""full card for one alloy: scalars + sampled curves for the panel plots + audit"""
function _material_payload(query)
    m = get_material(String(get(query, "alloy", "ER70S6")))
    proc = ProcessParameters()
    Ts, Tl = m.Tsol, m.Tliq
    x = Float64[300, 500, 800, 1100, 1400, 1700, 2000, 2400, 2900]
    push!(x, Ts, Tl)
    sort!(unique!(x))
    kT = [Float64(kcond(m, T)) for T in x]
    cpT = [Float64(WAAMFlow.Cp(m, T)) for T in x]
    μT = Float64[visc(m, T) for T in x]
    γT = [Float64(m.gamma(T)) for T in x]
    dγT = [Float64(dgamma_dT(m.gamma, T)) for T in x]
    comp = [(el = String(k), v = _r(v, 3)) for (k, v) in sort(collect(m.composition); by = x -> -x[2])]
    mode = Symbol(get(query, "mode", "paper"))
    es = EnergySplit(proc, m; mode = mode)
    JSON.json((
        name = m.name, family = String(m.family),
        Tsol = _r(m.Tsol, 1), Tliq = _r(m.Tliq, 1),
        mushy = _r(m.Tliq - m.Tsol, 1), Lf = _r(m.Lf, 0),
        rho_s = _r(m.rho_s, 0), rho_l = _r(m.rho_l, 0),
        beta_T = _r(m.beta_T, 8),
        kTl = _r(kcond(m, Tl), 2), viscTl = _r(visc(m, Tl), 8),
        CpTs = _r(Cp_s_ref(m), 1), CpTl = _r(Cp_l_ref(m), 1),
        dgamma_mid = _r(dgamma_dT(m.gamma, (m.Tsol + m.Tliq) / 2), 10),
        gamma_model = m.gamma isa WAAMFlow.SahooDebRoyFeS ? "Sahoo–DebRoy Fe–S (sulfur-dependent)" :
                      m.gamma isa WAAMFlow.LinearGamma ? "linear (Pichler family)" : "constant",
        marangoni = dgamma_dT(m.gamma, (Ts + Tl) / 2) > 0 ? "inward → deep, narrow pool" :
                    dgamma_dT(m.gamma, (Ts + Tl) / 2) < 0 ? "outward → wide, shallow pool" : "neutral",
        report = material_report(m),
        composition = comp,
        curves = (T = x, k = kT, cp = cpT, mu = μT, gamma = γT, dgamma = dγT),
        audit = _audit_nt(proc, m, mode),
    ))
end

function _audit_nt(proc, m, mode::Symbol)
    es = EnergySplit(proc, m; mode = mode)
    mdot = wire_feed_mass_rate(proc)
    Vdot = mdot / m.rho_l
    (arc_power_W = _r(arc_power(proc), 1),
     sigma_q_mm = _r(sigma_q(proc) * 1e3, 3),
     ui_W = _r(proc.UI, 1), eta = _r(proc.eta, 3), eta_d = _r(proc.eta_d, 3),
     droplet_eq12_W = _r(droplet_heat(proc, m), 1),
     droplet_eq10_W = _r(proc.eta * proc.eta_d * proc.UI, 1),
     q_surface_W = _r(es.q_surface, 1),
     q_droplet_W = _r(es.q_droplet, 1),
     closure_pct = _r(es.closure * 100, 4),
     mode = String(es.mode),
     wire_kg_s = _r(mdot, 9),
     volume_mm3_s = _r(Vdot * 1e9, 2))
end

"""mesh preview: counts for the domain panel (graded axes, as `run_track` builds them)"""
function _mesh_payload(query)
    h_fine = parse(Float64, get(query, "h_fine", "0.4")) * 1e-3
    ratio = parse(Float64, get(query, "ratio", "4"))
    Lx = parse(Float64, get(query, "Lx", "20")) * 1e-3
    Ly = parse(Float64, get(query, "Ly", "4")) * 1e-3
    Lz = parse(Float64, get(query, "Lz", "8")) * 1e-3
    ny = parse(Int, get(query, "ny", "10"))
    h_coarse = ratio * h_fine
    xf = graded_axis(0.0, Lx, h_fine, h_coarse; h_fine_end = :first)
    zf = graded_axis(0.0, Lz, h_fine, h_coarse; h_fine_end = :first)
    JSON.json((nx = length(xf) - 1, ny = ny, nz = length(zf) - 1,
               ncells = (length(xf) - 1) * ny * (length(zf) - 1),
               dx_start_mm = _r((xf[2] - xf[1]) * 1e3, 3),
               dx_end_mm = _r((xf[end] - xf[end-1]) * 1e3, 3),
               dz_start_mm = _r((zf[2] - zf[1]) * 1e3, 3),
               dz_end_mm = _r((zf[end] - zf[end-1]) * 1e3, 3)))
end

"""RunConfig defaults"""
function _defaults_payload()
    c = RunConfig()
    JSON.json((material = c.material, Lx = _r(c.Lx * 1e3, 2), Ly = _r(c.Ly * 1e3, 2),
               Lz = _r(c.Lz * 1e3, 2), h_fine = _r(c.h_fine * 1e3, 3),
               h_coarse = _r(c.h_coarse * 1e3, 3), ny = c.ny,
               arc_power_W = _r(c.arc_power_W, 1),
               travel_mm_s = _r(c.travel_speed * 1e3, 4),
               track_mm = _r(c.track_length * 1e3, 2), substrate_T = c.substrate_T,
               energy_mode = String(c.energy_mode), verbose = c.verbose))
end

# ---------------------------------------------------------------------------
# Run producer  (mirrors run_track's step body — the validated tier-1 path)
# ---------------------------------------------------------------------------

_round(x::Float64, d::Int) = round(x, digits = d)

"""snapshot payload between the solver loop and the browser"""
function _snap(step, t, dt, x_torch, prog, regime, peak, melt, bg,
               wall, top, sec, topshape, secshape, q_surface)
    JSON.json((
        type = "snap",
        step = step, t = _r(t, 4), dt = _r(dt, 9),
        xtorch = _r(x_torch * 1e3, 3), prog = _r(prog, 4),
        regime = String(regime), peak = _r(peak, 1), melt = _r(melt, 5),
        width = _r(bg.width * 1e3, 3), height = _r(bg.height * 1e3, 3),
        pen = _r(bg.penetration * 1e3, 3), wall = _r(wall, 2),
        q_surface = _r(q_surface, 1),
        top = (shape = topshape, data = top),
        sec = (shape = secshape, data = sec),
    ))
end

"""the producer: run a single track, streaming snapshots over the WebSocket"""
function _produce(sess, cfg::RunConfig; snapshot_every::Float64 = 0.033)
    try
        mat = get_material(cfg.material)
        proc = ProcessParameters()
        es = EnergySplit(proc, mat; mode = cfg.energy_mode)
        q_surface = isnan(cfg.surface_power_W) ? es.q_surface : cfg.surface_power_W

        xf = graded_axis(0.0, cfg.Lx, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
        zf = graded_axis(0.0, cfg.Lz, cfg.h_fine, cfg.h_coarse; h_fine_end = :first)
        yf = collect(range(0.0, cfg.Ly; length = cfg.ny))
        g = CartesianGrid(xf, yf, zf)
        m = metrics(g)
        ws = EnergyWorkspace(g)
        nx, ny, nz = g.nx, g.ny, g.nz

        T = fill(cfg.substrate_T, nx, ny, nz)
        Told = copy(T)
        z3 = zeros(nx, ny, nz)
        qb = zeros(nx, ny, nz); sb = zeros(nx, ny, nz); lb = zeros(nx, ny, nz)
        ctrl = TimestepController()

        x_start = cfg.h_fine * 2
        x_torch = x_start
        t = 0.0
        steps = 0
        peak = cfg.substrate_T
        e_in = 0.0
        e_res = 0.0
        maxspeed = 0.0
        last_push = time()
        t0 = time()

        broadcast(JSON.json((
            type = "audit",
            cfg = (material = mat.name, ncells = length(T),
                   Lx = _r(cfg.Lx * 1e3, 1), Ly = _r(cfg.Ly * 1e3, 1), Lz = _r(cfg.Lz * 1e3, 1)),
            audit = _audit_nt(proc, mat, cfg.energy_mode),
            q_surface = _r(q_surface, 1),
            note = "conduction-only tier: droplet share reported, not injected",
        )))

        while (x_torch - x_start) < cfg.track_length
            sess.stop && break
            while sess.pause && !sess.stop
                sleep(0.05)
            end
            sess.stop && break

            torch = (x_torch, yf[1])
            arc_flux!(qb, T, proc, mat, m, g, torch; q_surface_power = q_surface)
            arc_source!(sb, qb, T, mat, m, g; top_k = 1)
            surface_loss!(lb, T, proc, mat, m, g)

            dt, regime, info = timestep(T, fill(1.0, nx, ny, nz), m, g, mat, nothing, proc;
                                        ctrl = ctrl, t = t, torch = torch, src_now = sb)
            dt = clamp(dt, 1e-9, 0.05)

            copyto!(Told, T)
            res, iters, pin = solve_energy!(ws, T, Told, mat, nothing, sb, z3, lb, m, g, dt)
            e_res += energy_residual(T, ws.hout, Told, mat, nothing, sb, z3, lb, m, g, dt) * dt
            e_in += (abs(arc_power_delivered(sb, m)) + abs(sum(lb .* m.vol))) * dt

            t += dt
            steps += 1
            peak = max(peak, maximum(T))
            x_torch += cfg.travel_speed * dt

            now = time()
            if now - last_push >= snapshot_every
                last_push = now
                bg = bead_geometry(T, mat, m, g)
                top = [_r(T[i, j, 1], 2) for i in 1:nx, j in 1:ny]
                sec = [_r(T[i, 1, k], 2) for i in 1:nx, k in 1:nz]
                push!(sess.history, (step = steps, t = _r(t, 4), x = _r(x_torch * 1e3, 3),
                                     peak = _r(peak, 1), melt = _r(latent_heat_fraction(T, mat), 5),
                                     width = _r(bg.width * 1e3, 3), height = _r(bg.height * 1e3, 3),
                                     pen = _r(bg.penetration * 1e3, 3), dt = _r(dt, 9),
                                     regime = String(regime)))
                broadcast(_snap(steps, t, dt, x_torch, (x_torch - x_start) / cfg.track_length,
                                regime, peak, latent_heat_fraction(T, mat), bg,
                                now - t0, top, sec, (nx, ny), (nx, nz), q_surface))
            end
            x_torch > xf[end] - cfg.h_fine && break
        end

        bg = bead_geometry(T, mat, m, g)
        melt = latent_heat_fraction(T, mat)
        sess.last_manifest = """
        WAAMFlow single-track manifest
          material                 : $(mat.name)
          energy mode              : $(cfg.energy_mode)   (surface $(q_surface) W, droplets $(es.q_droplet) W)
          $(material_report(mat))
          deposited track          : $((x_torch - x_start) * 1e3) mm in $(t) s
          peak temperature         : $(peak) K
          bead width / height      : $(bg.width * 1e3) / $(bg.height * 1e3) mm
          penetration              : $(bg.penetration * 1e3) mm
          molten fraction          : $(melt)
          energy in / residual     : $(e_in) J / $(e_res) J
        """
        broadcast(JSON.json((
            type = "done", step = steps, t = _r(t, 3), peak = _r(peak, 1),
            melt = _r(melt, 5), width = _r(bg.width * 1e3, 3),
            pen = _r(bg.penetration * 1e3, 3),
            e_in = _r(e_in, 1), e_res = _r(e_res, 9),
            stopped = sess.stop, manifest = sess.last_manifest)))
        sess.status = sess.stop ? :stopped : :finished
        sess.status_msg = sess.stop ? "run cancelled at step $steps" : "run finished — $steps steps"
    catch e
        sess.status = :error
        sess.status_msg = sprint(showerror, e)
        broadcast(JSON.json((type = "error", message = sprint(showerror, e))))
        rethrow()
    finally
        sess.run_task = nothing
        sess.pause = false
    end
end

# ---------------------------------------------------------------------------
# HTTP router
# ---------------------------------------------------------------------------

"""read one HTTP request head (+ body for POST); returns (method, path, query, body)"""
function _read_request(sock)
    first_line = readline(sock)
    (isempty(first_line) || eof(sock)) && return nothing
    parts = split(first_line, " "; limit = 3)
    length(parts) == 3 || return nothing
    method, target = String(parts[1]), String(parts[2])
    headers = Dict{String,String}()
    while true
        line = readline(sock)
        isempty(line) && break
        i = findfirst(':', line)
        i === nothing && break
        headers[lowercase(strip(line[1:i-1]))] = strip(line[i+1:end])
    end
    body = ""
    if haskey(headers, "content-length")
        n = parse(Int, headers["content-length"])
        n > 0 && (body = String(read(sock, n)))
    end
    path, query = target, Dict{String,String}()
    q = findfirst('?', target)
    if q !== nothing
        path = target[1:q-1]
        for kv in split(target[q+1:end], "&"; keepempty = false)
            i = findfirst('=', kv)
            if i === nothing
                query[String(kv)] = ""
            else
                query[String(kv[1:i-1])] = String(kv[i+1:end])
            end
        end
    end
    (method = method, path = path, query = query, body = body, headers = headers)
end

_recent_history_json() = JSON.json((rows = length(GUI.history) > 0 ? GUI.history : Any[],))

"dispatch one connection; `ws` is true when the request upgraded to WebSocket"
function _handle(sock)
    req = _read_request(sock)
    req === nothing && (close(sock); return)
    try
        if lowercase(get(req.headers, "upgrade", "")) == "websocket"
            key = get(req.headers, "sec-websocket-key", "")
            id = 0
            lock(GUI.lock) do
                id = GUI.next_client += 1
                GUI.clients[id] = sock
                nothing
            end
            write(sock, "HTTP/1.1 101 Switching Protocols\r\n" *
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n" *
                        "Sec-WebSocket-Accept: $(_ws_accept(key))\r\n\r\n")
            flush(sock)
            _ws_loop(sock, id)     # stays until the client (or we) closes
            return
        end
        path = req.path
        if path == "/"
            _respond(sock, 200, "text/html", ASSETS["/"])
        elseif path == "/app.js"
            _respond(sock, 200, "application/javascript", ASSETS["/app.js"])
        elseif path == "/app.css"
            _respond(sock, 200, "text/css", ASSETS["/app.css"])
        elseif path == "/api/defaults"
            _respond(sock, 200, MIME_JSON, _defaults_payload())
        elseif path == "/api/materials"
            _respond(sock, 200, MIME_JSON, _materials_payload())
        elseif path == "/api/material"
            _respond(sock, 200, MIME_JSON, _material_payload(req.query))
        elseif path == "/api/audit"
            alloy = String(get(req.query, "alloy", "ER70S6"))
            mat = get_material(alloy)
            proc = ProcessParameters()
            mode = Symbol(get(req.query, "mode", "paper"))
            _respond(sock, 200, MIME_JSON, JSON.json(_audit_nt(proc, mat, mode)))
        elseif path == "/api/mesh"
            _respond(sock, 200, MIME_JSON, _mesh_payload(req.query))
        elseif path == "/api/history"
            _respond(sock, 200, MIME_JSON, _recent_history_json())
        elseif path == "/api/run"
            _handle_run_post(sock, req.body)
        elseif path == "/api/pause"
            pause = parse(Bool, get(JSON.parse(req.body == "" ? "{}" : req.body), "pause", true))
            GUI.status == (:running) || GUI.status == (:paused) ||
                return _respond(sock, 409, MIME_JSON,
                                JSON.json((error = "no active run to pause/resume",)))
            GUI.pause = pause
            GUI.status = pause ? :paused : :running
            broadcast(JSON.json((type = "status", status = String(GUI.status),
                                 message = GUI.status_msg)))
            _respond(sock, 200, MIME_JSON, JSON.json((ok = true, pause = pause)))
        elseif path == "/api/stop"
            GUI.run_task === nothing &&
                return _respond(sock, 409, MIME_JSON,
                                JSON.json((error = "no active run",)))
            GUI.stop = true
            _respond(sock, 200, MIME_JSON, JSON.json((ok = true,)))
        else
            _respond(sock, 404, MIME_JSON, JSON.json((error = "no route $path",)))
        end
    catch e
        _respond(sock, 400, MIME_JSON,
                 JSON.json((error = sprint(showerror, e),)))
    finally
        close(sock)
    end
end

"POST /api/run: validate the body, build a RunConfig, spawn the producer"
function _handle_run_post(sock, body::AbstractString)
    GUI.run_task !== nothing &&
        return _respond(sock, 409, MIME_JSON,
                        JSON.json((error = "a run is already active — stop it first",)))
    cfg_in = JSON.parse(body == "" ? "{}" : body)
    need(k) = haskey(cfg_in, k) || return false
    need("material") && need("travel_mm_s") && need("track_mm") || return
        _respond(sock, 400, MIME_JSON,
                 JSON.json((error = "body needs material, travel_mm_s and track_mm",)))
    mat = get_material(String(cfg_in["material"]))
    mm(x) = Float64(x) * 1e-3
    surface = Float64(get(cfg_in, "surface_power_W", NaN))
    surface = isnan(surface) ? NaN : surface
    cfg = RunConfig(material = mat.name,
                    Lx = mm(get(cfg_in, "Lx", 20.0)),
                    Ly = mm(get(cfg_in, "Ly", 4.0)),
                    Lz = mm(get(cfg_in, "Lz", 8.0)),
                    h_fine = mm(get(cfg_in, "h_fine", 0.4)),
                    h_coarse = mm(get(cfg_in, "h_coarse", 1.6)),
                    ny = Int(get(cfg_in, "ny", 10)),
                    arc_power_W = Float64(get(cfg_in, "arc_power_W", 1472.0)),
                    surface_power_W = surface,
                    travel_speed = Float64(get(cfg_in, "travel_mm_s", 2.8333)) / 1e3,
                    track_length = mm(get(cfg_in, "track_mm", 8.0)),
                    substrate_T = Float64(get(cfg_in, "substrate_T", 298.0)),
                    energy_mode = Symbol(get(cfg_in, "energy_mode", "paper")),
                    verbose = Bool(get(cfg_in, "verbose", false)))
    GUI.status = :running
    GUI.status_msg = ""
    GUI.stop = false
    GUI.pause = false
    empty!(GUI.history)
    GUI.run_task = @spawn _produce(GUI, cfg)
    _respond(sock, 200, MIME_JSON, JSON.json((ok = true, ncells_expected =
        Int(ceil(cfg.Lx / cfg.h_fine)) * 4,)))
end

"serve forever; each connection handled on its own task"
function _serve_loop(server)
    while true
        sock = accept(server)
        @spawn _handle(sock)
    end
end

# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

"""
    serve(; port = 8751, open = true) -> Int

Start the front end on `port` (returns the actual bound port). With `open`, the
system browser is opened at the URL immediately. Throws if the port is taken.
"""
function serve(; port::Int = 8751, open::Bool = true)
    isempty(ASSETS) && _load_assets!()
    GUI.server !== nothing && return GUI.port                # already serving
    server = listen(Sockets.InetAddr(Sockets.localhost, port))
    GUI.server = server
    GUI.port = port
    url = "http://127.0.0.1:$port/"
    @spawn _serve_loop(server)
    @printf("WAAMFlow UI listening on %s  (threads=%d)", url, nthreads())
    nthreads() < 2 &&
        @printf("\n  WARNING: passed %d thread; restart with `julia -t 2` or the " *
                "field updates will stall between physics steps\n", nthreads())
    open && _open_browser(url)
    port
end

"""
    shutdown()

Stop serving and cancel any run. Idempotent.
"""
function shutdown()
    GUI.stop = true
    GUI.run_task === nothing || @async begin
        try
            wait(GUI.run_task)
        catch
        end
    end
    GUI.server === nothing || try
        close(GUI.server)
    catch
    end
    GUI.server = nothing
    for s in values(GUI.clients)
        try
            close(s)
        catch
        end
    end
    empty!(GUI.clients)
    GUI.status = :idle
    nothing
end

"open a URL in the OS browser (no external package)"
function _open_browser(url::AbstractString)
    cmd = if Sys.isapple()
        `open $url`
    elseif Sys.islinux()
        `xdg-open $url`
    elseif Sys.iswindows()
        `cmd /c start $url`
    else
        return
    end
    try
        run(detach(cmd))
    catch e
        println("could not open the browser: ", e)
        println(url)
    end
end

"""
    launch(; port = 8751) -> Nothing

Serve the UI, open a browser, and block forever. The one-liner entry point.
"""
function launch(; port::Int = 8751)
    serve(; port = port, open = true)
    try
        while true
            sleep(3600)                 # keep the main task alive
        end
    catch e
        e isa InterruptException || rethrow()
    end
    nothing
end

end # module
