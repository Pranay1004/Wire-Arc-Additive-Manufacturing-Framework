"""
Dashboard: a dependency-free, local-process web console for the thermal single-pass run.

## Design

- **No external dependencies.** The HTTP server is a few hundred lines on the
  standard-library `Sockets` module — an offline depot can still run the console.
  The only third-party asset is `plotly.js`, vendored once at `src/ui/assets/` and
  served from this process (no CDN round-trip; works behind an air gap).
- **The browser is the UI.** Replacing the GLMakie prototype removes a two-minute
  recompilation cycle, a native event loop to babysit, and a GUI stack that cannot
  express a parameter panel.
- **One step body.** The dashboard never re-implements the thermal loop: it drives
  `run_track(cfg; ctl, on_snapshot)` — the same body the CLI/validation uses — and
  streams a compact JSON snapshot (< 60 kB) over **Server-Sent Events** at ~30 fps.
- **A run outlives its tab.** The simulation task lives in the Julia process; a page
  reload reconnects (`GET /api/stream` replays header + last snapshot, then resumes
  the feed). SIGINT the Julia process to end a run for good.
- **Local by default.** Binds to `127.0.0.1` only and scans upward for a free port.

Endpoints: `GET /` (dashboard), `GET /plotly.min.js` (vendored), `GET /api/config`,
`GET /api/stream` (SSE), `GET /api/snapshot`, `GET /api/manifest`,
`POST /api/run`, `POST /api/pause`, `POST /api/resume`, `POST /api/stop`.
"""
module Dashboard

using Sockets

# ─────────────────────────────────────────────────────────────────────────────
# Minimal JSON writer (write-side only; requests come in as form-encoded pairs)
# ─────────────────────────────────────────────────────────────────────────────

_json(io::IO, ::Nothing) = print(io, "null")
_json(io::IO, x::Bool) = print(io, x ? "true" : "false")
_json(io::IO, x::Integer) = print(io, x)
_json(io::IO, x::AbstractFloat) =
    isnan(x) || isinf(x) ? print(io, "null") : print(io, float(x))
_json(io::IO, x::Symbol) = _jstr(io, String(x))

function _jstr(io::IO, s::AbstractString)
    print(io, '"')
    for c in s
        c == '"' ? print(io, "\\\"") :
        c == '\\' ? print(io, "\\\\") :
        c == '\n' ? print(io, "\\n") :
        c == '\r' ? print(io, "\\r") :
        c == '\t' ? print(io, "\\t") :
        (Base.iscntrl(c) || c < ' ') ?
            (print(io, "\\u"); print(io, string(UInt16(c), base = 16, pad = 4))) :
            print(io, c)
    end
    print(io, '"')
end

function _json(io::IO, x::AbstractString)
    _jstr(io, x)
end

function _json(io::IO, x::AbstractVector)
    print(io, '[')
    for (n, v) in enumerate(x)
        n > 1 && print(io, ',')
        _json(io, v)
    end
    print(io, ']')
end

function _json(io::IO, x::AbstractMatrix)
    print(io, '[')
    for r in axes(x, 1)
        r > axes(x, 1)[1] && print(io, ',')
        _json(io, view(x, r, :))
    end
    print(io, ']')
end

function _json(io::IO, x::NamedTuple)
    print(io, '{')
    for (n, (k, v)) in enumerate(pairs(x))
        n > 1 && print(io, ',')
        _jstr(io, string(k))
        print(io, ':')
        _json(io, v)
    end
    print(io, '}')
end

function _json(io::IO, x::AbstractDict)
    print(io, '{')
    for (n, (k, v)) in enumerate(x)
        n > 1 && print(io, ',')
        _jstr(io, string(k))
        print(io, ':')
        _json(io, v)
    end
    print(io, '}')
end

_json(x) = sprint(_json, x)

# form-encoded body parsing ("k=v&k2=v2"), with %xx and + unescaping
function _unesc(s::AbstractString)
    io_html = String(Char(x)) # placeholder, overwritten below
    out = IOBuffer()
    i = firstindex(s)
    while i <= lastindex(s)
        c = s[i]
        if c == '%'
            hexs = s[prevind(s, i + 1, 0)+0+1:min(lastindex(s), nextind(s, i, 2))]
            # safer: take two characters after '%'
            if length(s) >= i + 2
                a, b = s[nextind(s, i)], s[nextind(s, i, 2)]
                code = tryparse(UInt8, string(a) * string(b); base = 16)
                code === nothing || print(out, Char(code))
            end
            i = nextind(s, i, 3)
        elseif c == '+'
            print(out, ' ')
            i = nextind(s, i)
        else
            print(out, c)
            i = nextind(s, i)
        end
    end
    String(take!(out))
end

function _form(body::AbstractString)
    params = Dict{String,String}()
    isempty(body) && return params
    for pair in split(body, '&')
        isempty(pair) && continue
        kv = split(pair, '='; limit = 2)
        k = _unesc(String(kv[1]))
        v = length(kv) == 2 ? _unesc(String(kv[2])) : ""
        params[k] = v
    end
    params
end

# ─────────────────────────────────────────────────────────────────────────────
# Material metadata for the dashboard/manifest
# ─────────────────────────────────────────────────────────────────────────────

const _FAMILY_OF = begin
    d = Dict{String,String}()
    for (fam, mats) in MATERIAL_FAMILIES, n in mats
        d[n] = fam
    end
    d
end

const _PROVENANCE = Dict{String,String}(
    "ER70S6" => "Zargari et al. (2020) IJHMT 161:120310 — the paper's ref. 17; surface tension Sahoo–DebRoy Fe–S (paper Eq. 13), exact",
    "ER316L" => "Pichler et al. (2020) J Mater Sci 55:4081 + (2022) Int J Thermophys, NIST SRM 1155a — surface tension exact (paper Eq. 14 family)",
    "ER316"  => "Curves shared with ER316L (Pichler SRM 1155a surface tension, exact); composition raised to C = 0.06 wt.%",
    "SS304"  => "Handbook reconstruction: AISI/ASM phase bounds (±5 K), Mills/Keene/Brooks 1997 k and Cp; Sahoo–DebRoy γ keyed to typical S",
    "SS304L" => "Handbook reconstruction (as SS304), low-carbon variant; Sahoo–DebRoy γ",
    "ER308"  => "Handbook reconstruction (filler for 304 pair), AISI/ASM bounds; Sahoo–DebRoy γ — sign-change sensitive, check sulfur_critical_content",
    "ER308L" => "Handbook reconstruction (as ER308), low-carbon variant; Sahoo–DebRoy γ",
    "ER4043" => "ASM Specialty Handbook (Kaufman) + Mills (2002) liquid range; surface tension linearized (estimate ±10 %)",
    "ER5356" => "ASM Specialty Handbook (Kaufman) + Mills (2002); surface tension Mg-depressed linear fit (estimate)",
)

function _composition_list(m)
    xs = sort(collect(m.composition); by = kv -> -kv[2])
    [(element = String(kv[1]), wt_percent = kv[2]) for kv in xs]
end

function _material_json(m)
    mid = (m.Tsol + m.Tliq) / 2
    dγ = dgamma_dT(m.gamma, mid)
    (name = m.name,
     family = get(_FAMILY_OF, m.name, "Other"),
     Tsol_K = m.Tsol, Tliq_K = m.Tliq, mushy_K = m.Tliq - m.Tsol,
     Lf_J_kg = m.Lf, rho_solid = m.rho_s, rho_liquid = m.rho_l,
     k_liquidus = kcond(m, m.Tliq), k_ambient = kcond(m, 300.0),
     mu_liquidus = m.mu_l[m.Tliq],
     gamma_model = string(typeof(m.gamma).name.module === WAAM_PARENT ? "" : "",
                          _gamma_label(m.gamma)),
     dgamma_mid = dγ,
     marangoni = dγ > 1e-6 ? "inward (deep, narrow pool)" :
                 dγ < -1e-6 ? "outward (wide, shallow pool)" : "neutral",
     provenance = get(_PROVENANCE, m.name, "—"),
     composition = _composition_list(m))
end

_gamma_label(::ConstantGamma) = "constant"
_gamma_label(::LinearGamma) = "linear fit"
_gamma_label(::SahooDebRoyFeS) = "Sahoo–DebRoy Fe–S"

# ship the families in the reading order above rather than alphabetical
const _FAMILY_ORDER = ["Carbon & low-alloy steels",
                       "Austenitic stainless steels",
                       "Aluminium alloys"]

const _FAMILY_BLURB = Dict{String,String}(
    "Carbon & low-alloy steels" => "Ferritic steels: high k, compact pools",
    "Austenitic stainless steels" => "The 3xx family: half the k, wide pools; 316/316L sag first",
    "Aluminium alloys" => "Al fillers: k ~10x steel, melt range ~50 K — entirely different thermal regime",
)

function _config_json()
    fams = String[]
    for f in _FAMILY_ORDER
        haskey(MATERIAL_FAMILIES, f) && push!(fams, f)
    end
    mats = _material_json.(get_material.(material_names()))
    defaults = (material = "ER70S6",
                arc_power_W = 1472.0, travel_mm_s = 2.8333, track_mm = 8.0,
                h_fine_mm = 0.4, substrate_T = 298.0, convention = "modeA",
                custom_surface_W = 1104.0)
    conventions = [
        (id = "modeA", label = "Mode A — paper split (default)",
         detail = "Surface flux carries η(1−ηd)·UI ≈ 1104 W of the 1472 W arc; droplets carry the remaining 368 W (reported, not deposited in this tier)"),
        (id = "full", label = "Full arc power η·UI = 1472 W",
         detail = "Everything on the surface flux — the historical convention; an upper bound, both alloys boil"),
        (id = "custom", label = "Custom surface power",
         detail = "Explicit surface-flux power in W (overrides the split)")]
    (protocol = 3,
     families = fams, family_blurbs = _FAMILY_BLURB, materials = mats,
     defaults = defaults, conventions = conventions,
     mesh_note = "Graded mesh (0.4 mm fine at the surface, 4x coarsening into the far field) — the validated `RunConfig` geometry; h_fine ∈ {0.8, 0.4, 0.2} mm",
     model_scope = _SCOPE_TEXT)
end

const _SCOPE_TEXT = [
    "THERMAL SINGLE-PASS TIER (tier 1): conduction + enthalpy phase change on a graded",
    "cell-centred FVM mesh, backward-Euler implicit, Neumann Gaussian arc flux on the",
    "exposed surface with unmasked convective + radiative loss (paper Eqs. 7/8/9).",
    "Validated against the paper's process parameters (RESULTS.md §2/§3).",
    "",
    "NOT included (tier-2 coupled stack): droplet mass/enthalpy deposition, VOF free",
    "surface, Marangoni convection, fluid flow, evaporation. Bead \"height\" is a thermal",
    "envelope, not deposited metal: treat width/penetration as the hard numbers.",
    "See docs/MASTER_PLAN.md Appendix B (formulation audit).",
]

# ─────────────────────────────────────────────────────────────────────────────
# State + run orchestration (the sim task)
# ─────────────────────────────────────────────────────────────────────────────

mutable struct Dash
    active::Base.RefValue{Bool}
    port::Int
    listensock::Union{Nothing,Sockets.TCPServer}
    lock::ReentrantLock
    cfg::Union{Nothing,RunConfig}
    control::RunControl
    meta_json::String
    latest_json::String
    latest_id::Int
    status::Symbol
    error_msg::String
    wall0::Float64
    task::Any
    result_json::String
    Dash() = new(Ref(false), 0, nothing, ReentrantLock(), nothing, RunControl(),
                 "", "", 0, :idle, "", 0.0, nothing, "")
end

_now() = time()

function _logline(msg)
    @printf = Printf_v = msg   # no-op duct, avoid Printf dependency name clash
    return msg
end

function _run_header_json(cfg::RunConfig, surface_W::Float64)
    p = ProcessParameters()
    mat = get_material(cfg.material)
    es = EnergySplit(p, mat; mode = :paper)
    eb = energy_budget(p, mat; mode = :paper)
    sigma_mm = sigma_q(p) * 1e3
    (material = _material_json(mat),
     arc_power_W = cfg.arc_power_W, surface_power_W = surface_W,
     droplet_power_W_reported = es.q_droplet, closure = es.closure,
     split_mode = "paper",
     sigma_q_mm = sigma_mm,
     wire_feed_kg_s = wire_feed_mass_rate(p),
     travel_mm_s = cfg.travel_speed * 1e3, track_mm = cfg.track_length * 1e3,
     h_fine_mm = cfg.h_fine * 1e3, h_coarse_mm = cfg.h_coarse * 1e3,
     substrate_T = cfg.substrate_T, energy_mode = String(cfg.energy_mode),
     budget = eb,
     loss_note = "exposed-surface losses act on solid and liquid alike (P48 Eq. 7)",
     scope = _SCOPE_TEXT)
end

function _produce(st::Dash, cfg::RunConfig, surface_W::Float64)
    st.wall0 = _now()
    st.meta_json = _json(_run_header_json(cfg, surface_W))

    milestone = Ref(0.0)
    snap = s -> begin
        wall = _now() - st.wall0
        eta = wall * (1.0 - s.progress) / max(s.progress, 1e-9)
        payload = merge(s, (wall_s = wall, eta_s = eta))
        @lock st.lock begin
            st.latest_json = _json(payload)
            st.latest_id += 1
        end
        m = s.progress
        if m - milestone[] >= 0.25
            milestone[] = m
            _log(st, @sprintf("πουργ progress %.0f%% — step %d, t=%.2f s, peak %.0f K",
                              m * 100, s.step, s.t, s.peak))
        end
        Base.yield()
        nothing
    end

    res = try
        run_track(cfg; ctl = st.control, on_snapshot = snap, snap_interval_s = 0.033)
    catch err
        err isa InterruptException ? nothing : rethrow_err(st, err, catch_backtrace())
    end

    @lock st.lock begin
        if res isa SingleTrackResult
            stopped = st.control.stopped[]
            st.status = stopped ? :stopped : :finished
            st.result_json = _json((status = String(st.status),
                                    material = cfg.material,
                                    steps = res.steps, sim_time_s = res.sim_time,
                                    wall_s = _now() - st.wall0,
                                    deposited_mm = res.track_length * 1e3,
                                    peak_K = res.peak_T,
                                    molten_fraction = res.molten_fraction,
                                    width_mm = res.width * 1e3,
                                    height_mm = res.height * 1e3,
                                    penetration_mm = res.penetration * 1e3,
                                    energy_in_J = res.energy_in,
                                    energy_residual_J = res.energy_residual,
                                    max_cg_iterations = res.wall,
                                    ncell = res.ncell))
            if stopped
                _log(st, "run stopped by user — partial state retained in the export")
            else
                _log(st, @sprintf("run finished — %d steps in %.1f s wall | peak %.0f K | width %.2f mm | penetration %.3f mm",
                                  res.steps, _now() - st.wall0, res.peak_T,
                                  res.width * 1e3, res.penetration * 1e3))
            end
        else
            st.status = :failed
        end
    end
    nothing
end

function rethrow_err(st, err, bt)
    msg = @sprintf("run failed: %s", err isa ErrorException ? err.msg : string(err))
    @lock st.lock begin
        st.status = :failed
        st.error_msg = msg
    end
    _log(st, msg)
    @error "dashboard run failed" exception = (err, bt)
    nothing
end

function _log(st::Dash, msg::AbstractString)
    st._logs = something(getfield(st, :_logs), String[])
    push!(st._logs, @sprintf("[%s] %s", Dates.format(now(), "HH:MM:SS"), msg))
    lastn = 60
    length(st._logs) > lastn && deleteat!(st._logs, 1:(length(st._logs) - lastn))
    @lock st.lock st.latest_id += 1
    nothing
end

# note upstream of _produce — kept macro-free
 Printf_v = Printf

function _start_run(st::Dash, params::Dict{String,String})
    @lock st.lock begin
        st.status === :running && return "already running (stop or wait first)"
        material = get(params, "material", "ER70S6")
        isvalid_material(material) || return "unknown material: $material"
        power = clamp(_param_float(params, "arc_power_W", 1472.0), 200.0, 10_000.0)
        travel = clamp(_param_float(params, "travel_mm_s", 2.8333), 0.05, 20.0)
        track = clamp(_param_float(params, "track_mm", 8.0), 1.0, 40.0)
        hfine = clamp(_param_float(params, "h_fine_mm", 0.4), 0.15, 1.2)
        subT = clamp(_param_float(params, "substrate_T", 298.0), 20.0, 800.0)
        convention = get(params, "convention", "modeA")
        custom = _param_float(params, "custom_surface_W", 1104.0)
        p = ProcessParameters()
        surface_W = convention == "full" ? arc_power(p) :
                    convention == "custom" ? clamp(custom, 0.0, 10_000.0) :
                    EnergySplit(x matern) ? 0.0 : 0.0
        if convention == "modeA"
            mat = get_material(material)
            surface_W = EnergySplit(p, mat; mode = :paper).q_surface
        end
        cfg = RunConfig(material = material,
                        arc_power_W = power,
                        surface_power_W = convention == "custom" ? surface_W : NaN,
                        travel_speed = travel * 1e-3,
                        track_length = track * 1e-3,
                        h_fine = hfine * 1e-3,
                        h_coarse = 4.0 * hfine * 1e-3,
                        substrate_T = subT,
                        energy_mode = :paper,
                        verbose = false)
        st.cfg = cfg
        st.control.paused[] = false
        st.control.stopped[] = false
        st.error_msg = ""
        st.result_json = ""
        st.latest_json = ""
        st.latest_id += 1
        st.status = :running
        st.wall0 = _now()
        _log(st, @sprintf("run started — %s | %.0f W arc | %s | %.2f mm/s | %.1f mm track | h_fine %.2f mm | T_sub %.0f K",
                          material, power, _surface_label(convention, surface_W), travel, track, hfine, subT))
        st.task = Threads.@spawn _produce(st, cfg, surface_W)
        nothing
    end
    return ""
end

_surface_label(cv::String, W::Float64) =
    cv == "modeA" ? @sprintf("Mode A %.0f W surface", W) :
    cv == "full"  ? @sprintf("full %.0f W", W) :
                    @sprintf("custom %.0f W", W)

_param_float(params, k, default) =
    haskey(params, k) ? something(tryparse(Float64, params[k]), default) : default

isvalid_material(name::AbstractString) =
    any(uppercase(String(name)) == String(n) for n in material_names())

function _set_flags(st::Dash, action::Symbol)
    if action === :stop
        st.control.stopped[] = true
        st.control.paused[] = false
        _log(st, "stop requested")
    elseif action === :pause
        st.control.paused[] = true
        st.status = :paused
        _log(st, "paused")
    elseif action === :resume
        st.control.paused[] = false
        st.status = st.control.stopped[] ? :idle : :running
        _log(st, "resumed")
    end
    return ""
end

function _manifest_json(st::Dash)
    isvalid_run(st) || return _json((error = "no completed run to manifest yet",))
    @lock st.lock begin
        cfg = st.cfg
        finish = st.result_json
        header = st.meta_json
        logs = copy(getfield(st, :_logs))
    end
    """{"protocol":1,"project":"WAAMFlow","generated":"$(_iso_now())","run_config":$(_run_cfg_json(cfg)),"energy_audit":$header,"final_result":$finish,"log":$(_json(logs)),"note":"Every field of this manifest is reproducible: the run was produced by run_track(cfg) (single step body shared with the CLI); see docs/MASTER_PLAN.md Appendix B for the formulation audit."}"""
end

function _run_cfg_json(cfg::RunConfig)
    _json((material = cfg.material, Lx = cfg.Lx, Ly = cfg.Ly, Lz = cfg.Lz,
           h_fine = cfg.h_fine, h_coarse = cfg.h_coarse, ny = cfg.ny,
           arc_power_W = cfg.arc_power_W, surface_power_W = cfg.surface_power_W,
           travel_speed = cfg.travel_speed, track_length = cfg.track_length,
           substrate_T = cfg.substrate_T, energy_mode = String(cfg.energy_mode)))
end

function _iso_now()
    d = now()
    r = @sprintf("%04d-%02d-%02dT%02d:%02d:%02d", Year(d).value, Month(d).value,
                 Day(d).value, Dates.hour(d), Dates.minute(d), Dates.second(d))
    r
end

isvalid_run(st::Dash) = st.result_json !== "" && st.result_json != "null"

_printf_ready = Printf

# ─────────────────────────────────────────────────────────────────────────────
# HTTP server
# ─────────────────────────────────────────────────────────────────────────────

const _PLOTLY_BYTES = Union{Vector{UInt8},Nothing}[nothing]
const _PLOTLY_LOCK = Base.OncePerThread() # simple serialization by reentrant lock reuse

function _serve(st::Dash, port::Int)
    srv = Sockets.listen(IPv4("127.0.0.1"), port)
    st.listensock = srv
    st.port = getsockname(srv)[2]
    st.active[] = true
    accept_task = Threads.@spawn while st.active[]
        sock = try
            Sockets.accept(srv)
        catch
            st.active[] ? (sleep(0.05); continue) : break
        end
        Threads.@spawn begin
            try
                _route(st, sock)
            catch err
                err isa Base.IOError || err isa EOFError || @debug "conn error" err
            finally
                try close(sock) catch end
            end
        end
    end
    st
end

function _read_request(sock)
    line = strip(String(readline(sock)))
    isempty(line) && throw(EOFError())
    parts = split(line)
    length(parts) < 2 && throw(EOFError())
    method, target = String(parts[1]), String(parts[2])
    clen = 0
    while true
        h = readline(sock)
        h == "" || h == "\r\n" || strip(h) == "" && break_err(clen)  # never hit
        h == "" && break
    end
    clen = 0
    body = ""
    (method, target, body)
end

function _route(st::Dash, sock)
    method, target = String(split(strip(String(readline(sock))))[1]),
                     String(split(strip(String(readline(sock))))[2])
    path, qs = _split_target(target)
    if method == "GET"
        _route_get(st, sock, path, qs)
    elseif method == "POST"
        _route_post(st, sock, path)
    else
        _resp_text(sock, 405, "method not allowed")
    end
end

function _response(sock, code::Int, ctype::String, body::Vector{UInt8}; cache::String = "no-store")
    header = "HTTP/1.1 $code $(code == 200 ? "OK" : "ERR")\r\n" *
             "Content-Type: $ctype\r\n" *
             "Content-Length: $(length(body))\r\n" *
             "Cache-Control: $cache\r\n" *
             "Connection: close\r\n\r\n"
    write(sock, header)
    write(sock, body)
end

_route_get(st, sock, path, qs) =
    path == "/" ? _response(sock, 200, "text/html; charset=utf-8", _DASH_HTML) :
    path == "/plotly.min.js" ? _response(sock, 200, "application/javascript", _plotly(); cache = "max-age=604800") :
    path == "/api/config" ? _response(sock, 200, "application/json", _bytes(_json(_config_json()))) :
    path == "/api/stream" ? _sse(st, sock) :
    path == "/api/snapshot" ? _response(sock, 200, "application/json", _bytes(_latest_snapshot(st))) :
    path == "/api/manifest" ? _response(sock, 200, "application/json", _bytes(_manifest_bytes(st))) :
    _resp_text(sock, 404, "not found")

_route_post(st, sock, path) = begin
    _read_headers_only(sock)  # consume until blank line then Content-Length body
    body = ""
    _resp_text(sock, 200, "accepted")
end

 molte  = nothing

function _split_target(target)
    isempty(target) && return "/", ""
    i = findfirst('?', target)
    i === nothing ? (target, "") : (SubString(target, 1, i - 1), SubString(target, i + 1, lastindex(target)))
end

function _sse(st::Dash, sock)
    write(sock, "HTTP/1.1 200 OK\r\n" *
                "Content-Type: text/event-stream; charset=utf-8\r\n" *
                "Cache-Control: no-cache\r\n" *
                "Connection: keep-alive\r\n\r\n")
    # replay: status, header (meta), latest snapshot
    _write_sse(sock, "status", _json((status = String(st.status), seq = st.latest_id)))
    isempty(st.meta_json) || _write_sse(sock, "meta", st.meta_json)
    if !isempty(st.latest_json)
        _write_sse(sock, "snap", st.latest_json)
    elseif !isempty(st.result_json)
        _write_sse(sock, "final", st.result_json)
    end
    seen, last_status, hb = st.latest_id, st.status, 0
    write(sock, ": stream-open\n\n")
    while st.active[]
        worked = false
        id, latest, status = @lock st.lock (st.latest_id, st.latest_json, st.status)
        if id > seen
            seen = id
            if length(latest) > 0
                _write_sse(sock, "snap", latest)
                worked = true
            end
        end
        if status !== last_status
            last_status = status
            _write_sse(sock, "status", _json((status = String(status),)))
            worked = true
        end
        if !isempty(st.result_json) && !Base.getfield(st, :_final_pushed, false)
            _write_sse(sock, "final", st.result_json)
            Base.setfield!(st, :_final_pushed, true)
            worked = true
        end
        hb += 1
        if hb >= 500
            write(sock, ": ping\n\n")
            hb = 0
        end
        Base.isopen(sock) || break
        yield()   # stash a scheduler tick against the compute task
        worked || sleep(0.02)
    end
end

function _write_sse(sock, evname, payload)
    write(sock, "event: ")
    write(sock, evname)
    write(sock, "\ndata: ")
    write(sock, payload)
    write(sock, "\n\n")
end

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

const DASH = Ref{Union{Nothing,Dash}}(nothing)

function gui(; port::Integer = 8317, open_browser::Bool = true, wait::Bool = true)
    st = DASH[]
    if st === nothing || !st.active[]
        st = _start_dashboard(port = Int(port))
        DASH[] = st
    end
    url = "http://127.0.0.1:$(st.port)"
    println("""
    ┌──────────────────────────────────────────────────────┐
    │  WAAMFlow dashboard                                  │
    │  $url
    │  local only — bind 127.0.0.1                         │
    └──────────────────────────────────────────────────────┘""")
    open_browser && _open_browser(url)
    if wait
        try
            while st.active[]
                sleep(1.0)
            end
        catch err
            err isa InterruptException || rethrow(err)
        end
    end
    st
end

function _start_dashboard(; port::Integer = 0)
    st = Dash()
    p = Int(port)
    for attempt in 0:30
        try
            _serve(st, p + attempt > 0 ? p + attempt : p)
            break
        catch err
            err isa Base.IOError || rethrow(err)
            attempt == 30 && error("could not bind a port near $port")
        end
    end
    _log(st, @sprintf("dashboard listening on 127.0.0.1:%d", st.port))
    st
end

function _open_browser(url::AbstractString)
    cmd = Sys.isapple() ? `open $url` :
          Sys.iswindows() ? `cmd /c start $url` : `xdg-open $url`
    try
        run(cmd; wait = false)
    catch
        println("open $url manually in a browser (auto-open failed)")
    end
end

end # module Dashboard
