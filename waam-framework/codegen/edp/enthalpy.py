"""
Thermodynamic enthalpy and specific heat smoothing functions for WAAM.
"""

def smooth_cp_spike(t_list, v_list, delta=2.0, slope_tol=1.0e5):
    """Replace near-vertical Cp spike edges with in-band ramps, preserving area.

    Material tables encode fusion latent heat as a tall box with ~0.01 K edges
    (e.g. 650 -> 5559 J/kg/K over 0.01 K). A Picard corrector with any finite
    temperature tolerance cannot converge across a discontinuity: predicted and
    corrected states land on opposite sides of a 5000 J/kg/K jump forever, so
    solidification/melting transients keep a ~10% energy error no iteration
    count removes (measured, then fixed here). Ramps of width ``delta`` inside
    the band make Cp continuous; the box height is raised from S to
    A_box / (width - delta) so the total latent (the table's own box area) is
    preserved exactly. Smooth tables pass through untouched. Returns new
    (T, Cp) lists.
    """
    T = [float(t) for t in t_list]
    V = [float(v) for v in v_list]
    if len(T) != len(V) or len(T) < 4:
        return t_list, v_list
    out_T, out_V = [T[0]], [V[0]]
    i = 1
    changed = False
    while i < len(T) - 1:
        dt = T[i] - T[i - 1]
        dv = V[i] - V[i - 1]
        # Up-edge of a spike box: huge positive slope over a tiny interval,
        # with the value staying high afterwards (not a data glitch).
        if dt > 0 and dt < 1.0 and dv / dt > slope_tol and i + 2 < len(T):
            # Find the matching down-edge: huge negative slope back down.
            j = i + 1
            while j < len(T) - 1:
                dt2 = T[j + 1] - T[j] if j + 1 < len(T) else 0.0
                dv2 = V[j + 1] - V[j] if j + 1 < len(T) else 0.0
                if dt2 > 0 and dt2 < 1.0 and dv2 / dt2 < -slope_tol:
                    break
                j += 1
            if j < len(T) - 1:
                Ts, base = T[i - 1], V[i - 1]
                Tl = T[j + 1]
                width = Tl - Ts
                # Box area between the edges (the latent the table encodes).
                a_box = 0.0
                for k in range(i - 1, j + 1):
                    a_box += 0.5 * (V[k] + V[k + 1]) * (T[k + 1] - T[k])
                a_box -= 0.5 * (base + V[j + 1]) * width  # above the base line
                d = min(delta, width / 4.0)
                if d > 0 and width - d > 0 and a_box > 0:
                    # The (Ts, base) point is already the last one appended;
                    # do not duplicate it (zero-width segments confuse the
                    # piecewise-linear emitter's dt guard).
                    H = a_box / (width - d)
                    out_T += [Ts + d, Tl - d, Tl]
                    out_V += [base + H, base + H, V[j + 1]]
                    i = j + 2
                    changed = True
                    continue
        out_T.append(T[i])
        out_V.append(V[i])
        i += 1
    if not changed:
        return t_list, v_list
    out_T.append(T[-1])
    out_V.append(V[-1])
    return out_T, out_V


def make_enthalpy_func(fname, t_list, v_list, t_ref=25.0):
    """Emit a FreeFEM function H(T) = integral of the SAME piecewise-linear
    Cp table from ``t_ref`` to T, evaluated EXACTLY (trapezoids between the
    table's own breakpoints, exact partial trapezoid up to T).

    Why not numeric quadrature (the previous Hseg): midpoint bins alias the
    near-vertical latent-spike edges by bin alignment, mis-stating stored /
    imposed energy by ~10% on any case that crosses the fusion band. The
    table is piecewise-LINEAR, so the integral is available in closed form
    and is O(#breakpoints) per call -- exact and fast enough to also serve
    as the solver's enthalpy in the secant-Cp mass term.
    """
    pairs = sorted((float(t), float(v)) for t, v in zip(t_list, v_list))
    pairs = [(t, v) for t, v in pairs]
    if len(pairs) < 2:
        # Safety net: constant-Cp integral, never exercised by real tables.
        return (f"func real {fname}(real T) {{\n"
                f"    return 800.*max(T - {float(t_ref):.6f}, 0.);\n}}")
    lines = [f"func real {fname}(real T) {{",
             f"    if (T <= {float(t_ref):.6f}) return 0.;"]
    H = 0.0
    for i in range(len(pairs) - 1):
        t0, v0 = pairs[i]
        t1, v1 = pairs[i + 1]
        if t1 <= t0:
            continue
        ta = max(t0, float(t_ref))
        if t1 <= ta:
            continue
        slope = (v1 - v0) / (t1 - t0)
        va = v0 + slope * (ta - t0)
        # T at or below this span's clipped start: accumulated H only.
        lines.append(f"    if (T <= {ta:.6f}) return {H:.10e};")
        # Partial trapezoid from ta to T, exact while T stays in this span.
        lines.append(
            f"    if (T <= {t1:.6f}) return {H:.10e} + 0.5*("
            f"{va:.8e} + ({v0:.8e} + {slope:.10e}*(T - {t0:.6f})))"
            f" * (T - {ta:.6f});")
        H += 0.5 * (va + v1) * (t1 - ta)
    t_last, v_last = pairs[-1]
    lines.append(f"    return {H:.10e} + {v_last:.8e} * (T - {t_last:.6f});")
    lines.append("}")
    return "\n".join(lines)


def make_inverse_enthalpy_func(fname, t_list, v_list, t_ref=25.0):
    """Emit T(H): the EXACT inverse of make_enthalpy_func's H(T).

    Within a table segment H is QUADRATIC in T (linear Cp), so T(H) is the
    exact root of H0 + v0*tau + m/2*tau^2 = H, emitted per segment -- no
    sampling, no interpolation error. Used by the solver to recover the
    temperature field from the enthalpy unknown (H is the primary variable;
    see the emitted aThermal/lThermal).
    """
    pairs = sorted((float(t), float(v)) for t, v in zip(t_list, v_list))
    if len(pairs) < 2:
        return (f"func real {fname}(real H) {{\n"
                f"    return {float(t_ref):.6f} + max(H, 0.)/800.;\n}}")
    lines = [f"func real {fname}(real H) {{",
             f"    if (H <= 0.) return {float(t_ref):.6f};"]
    Hacc = 0.0
    for i in range(len(pairs) - 1):
        t0, v0 = pairs[i]
        t1, v1 = pairs[i + 1]
        if t1 <= t0:
            continue
        ta = max(t0, float(t_ref))
        if t1 <= ta:
            continue
        L = t1 - ta
        m = (v1 - v0) / (t1 - t0)
        va = v0 + m * (ta - t0)
        dH = va * L + 0.5 * m * L * L
        if dH <= 1e-12:
            continue
        Hnext = Hacc + dH
        if abs(m) > 1e-9:
            lines.append(
                f"    if (H <= {Hnext:.10e}) return {ta:.6f} + "
                f"((-{va:.8e} + sqrt(max({va:.8e}*{va:.8e} + 2.*{m:.10e}"
                f"*(H - {Hacc:.10e}), 0.)))/{m:.10e});")
        else:
            lines.append(
                f"    if (H <= {Hnext:.10e}) return {ta:.6f} + "
                f"(H - {Hacc:.10e})/{va:.8e};")
        Hacc = Hnext
    v_last = pairs[-1][1]
    lines.append(
        f"    return {pairs[-1][0]:.6f} + (H - {Hacc:.10e})/{v_last:.8e};")
    lines.append("}")
    return "\n".join(lines)

