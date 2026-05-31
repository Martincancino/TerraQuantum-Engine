"""
TerraQuantum - Sweep de Estabilidad Minimum Support / IRLS
Fase 1.7C.3L.1

Barre combinaciones de (EPS_MIN, BETA_MS, COOLING) para identificar la zona
estable del prior MS que compacta la anomalia sin generar rebote superficial.
No modifica servicios productivos ni usa datos reales.

Referencia: Portniaguine & Zhdanov (1999), Geophysics 64(3), 829-843.
"""
import os, sys, time, itertools
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr, LinearOperator
from scipy.ndimage import label

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from services.geophysics_service import (
    estimate_grade_from_geophysics,
    build_anomaly_dataframe,
    build_voxel_output,
    build_best_target,
)
import polars as pl
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    centroid_weighted, CUTOFF_DENSITY, CUTOFF_VISUAL_SCORE, BASE_DENSITY,
    TOTAL_VOXELS, NX, NY, NZ, BLOCK_SIZE,
)

# --- Grid (identico a benchmarks anteriores) ---
grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix_arr = grid_x.flatten(order="F").astype(np.int32)
iy_arr = grid_y.flatten(order="F").astype(np.int32)
iz_arr = grid_z.flatten(order="F").astype(np.int32)
x_c = (ix_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
y_c = (iy_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
z_c = (iz_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

xv, zv = np.meshgrid(np.linspace(0, 800, 33), np.linspace(0, 800, 33), indexing="ij")
sensor_coords = np.column_stack((xv.ravel(), np.zeros_like(xv.ravel()), zv.ravel()))

# --- Constantes fisicas FIJAS para este sweep ---
PHYSICAL_CONTRAST_THR = 0.15
LAMBDA_MAG    = 0.00005
M_MAX         = 1.60
BETA          = 1.00
ALPHA_SPATIAL = 2.00

# --- Parametros IRLS fijos ---
EPS_0    = 0.80
MAX_IRLS = 20
IRLS_TOL = 1e-3

# --- Grillas de sweep (4 x 4 x 2 = 32 combinaciones) ---
SWEEP_EPS_MIN  = [0.12, 0.10, 0.08, 0.06]
SWEEP_BETA_MS  = [1e-5, 3e-5, 1e-4, 3e-4]
SWEEP_COOLING  = [0.85, 0.90]
SWEEP_SCENARIOS = ["shallow_body", "deep_body", "two_bodies"]


# =============================================================================
# Utilidades
# =============================================================================

def pr_auc_score(y_true, y_score):
    """Average Precision sin sklearn."""
    y_true  = np.asarray(y_true, dtype=bool)
    y_score = np.asarray(y_score, dtype=float)
    desc    = np.argsort(y_score)[::-1]
    y_true  = y_true[desc]; y_score = y_score[desc]
    tp   = np.cumsum(y_true); fp = np.cumsum(~y_true)
    prec = tp / np.maximum(tp + fp, 1)
    rec  = tp / max(np.sum(y_true), 1)
    prec = np.concatenate([[1.0], prec]); rec = np.concatenate([[0.0], rec])
    return float(np.sum((prec[1:] + prec[:-1]) * np.diff(rec) * 0.5))


def build_gaussian_body(cx, cy, cz, rx, ry, rz, mc=0.55):
    r2 = ((x_c - cx)/rx)**2 + ((y_c - cy)/ry)**2 + ((z_c - cz)/rz)**2
    c = mc * np.exp(-r2); c[c < 0.05] = 0.0; return c


def generate_scenarios():
    s = {}
    s["shallow_body"]   = build_gaussian_body(400, 120, 400, 120,  80, 120)
    s["mid_body"]       = build_gaussian_body(400, 230, 400, 150, 120, 150)
    s["deep_body"]      = build_gaussian_body(400, 330, 400, 150, 120, 150)
    s["elongated_body"] = build_gaussian_body(400, 230, 400, 250,  90, 100)
    b1 = build_gaussian_body(250, 150, 250, 100,  80, 100, 0.5)
    b2 = build_gaussian_body(550, 300, 550, 120, 100, 120, 0.6)
    s["two_bodies"] = np.maximum(b1, b2)
    return s


# =============================================================================
# Sistema de ecuaciones
# =============================================================================

def build_augmented_system(kernel, g_obs, beta, alpha_spatial):
    """
    Sistema aumentado completo con damping isotropico.
    Devuelve Ga, da, W, sG, Gn, gn, n_v.
    Las ultimas n_v filas de Ga corresponden al bloque LAMBDA_MAG*I.
    """
    n_s, n_v = kernel.shape
    sG = float(np.max(np.abs(kernel.data)))
    Gn = kernel / sG; gn = g_obs / sG
    W  = np.power(y_c, beta / 2.0) if beta > 0 else np.ones(n_v)
    W /= np.mean(W)
    Wm  = sp.diags(W, 0, format="csr")
    Gt  = Gn.dot(Wm)
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    Ws  = inv._build_spatial_regularizer() / 6.0
    Wst = Ws.dot(Wm)
    ls    = float(alpha_spatial) * (n_s / n_v)
    Idamp = LAMBDA_MAG * sp.eye(n_v, format="csr")
    Ga = sp.vstack([Gt, ls * Wst, Idamp], format="csr")
    da = np.concatenate([gn, np.zeros(n_v), np.zeros(n_v)])
    return Ga, da, W, sG, Gn, gn, n_v


def _residual_stats(Gn, m_physical, W, sG, g_obs):
    gm  = Gn.dot(m_physical) * sG
    res = g_obs - gm
    return res, float(np.linalg.norm(res)), float(np.sqrt(np.mean(res**2)))


# =============================================================================
# Solvers
# =============================================================================

def solve_lsqr_baseline(Ga, da, W, sG, Gn, gn, g_obs):
    """LSQR con sistema aumentado completo."""
    t0      = time.perf_counter()
    r       = lsqr(Ga, da, damp=0.0, atol=1e-6, btol=1e-6, iter_lim=400, show=False)
    t_solve = time.perf_counter() - t0
    m_raw   = r[0] * W
    m_final = np.clip(m_raw, 0.0, M_MAX)
    res_raw, rl2_raw, rms_raw = _residual_stats(Gn, m_raw,   W, sG, g_obs)
    _,       rl2_fin, rms_fin = _residual_stats(Gn, m_final, W, sG, g_obs)
    return m_final, m_raw, t_solve, rl2_raw, rms_raw, rms_fin, res_raw


# =============================================================================
# Metricas
# =============================================================================

def compute_metrics_extended(m_final, ct, mask_true):
    corr      = float(np.corrcoef(m_final, ct)[0, 1])
    mask_pred = m_final >= PHYSICAL_CONTRAST_THR
    tp  = np.sum(mask_pred & mask_true)
    fp  = np.sum(mask_pred & ~mask_true)
    fn  = np.sum(~mask_pred & mask_true)
    prec = tp / max(tp + fp, 1)
    rec  = tp / max(tp + fn, 1)
    iou  = tp / max(tp + fp + fn, 1)
    f1   = 2 * prec * rec / max(prec + rec, 1e-15)
    cw_y_true = centroid_weighted(x_c, y_c, z_c, ct)[1]
    cw_y_pred = centroid_weighted(x_c, y_c, z_c, m_final)[1]
    y_err     = cw_y_pred - cw_y_true
    total_mass   = np.sum(m_final)
    shallow_mask = y_c <= 200.0
    shallow_pct  = 100.0 * np.sum(m_final[shallow_mask]) / max(total_mass, 1e-9)
    pr_auc  = pr_auc_score(mask_true, m_final)
    k_true  = int(np.sum(mask_true))
    topk    = len(np.intersect1d(np.argsort(ct)[-k_true:], np.argsort(m_final)[-k_true:])) / max(k_true, 1)
    n_active    = int(np.sum(mask_pred))
    max_density = float(np.max(m_final))
    return corr, iou, f1, prec, rec, y_err, shallow_pct, pr_auc, topk, n_active, max_density


def topological_targets(cr, mask, max_t=2):
    structure = np.ones((3, 3, 3), dtype=int)
    labeled, num = label(mask.reshape((NX, NY, NZ), order='F'), structure=structure)
    labeled = labeled.flatten(order='F')
    if num == 0: return []
    comp_scores = [(i, np.sum(cr[labeled == i])) for i in range(1, num + 1)]
    comp_scores.sort(key=lambda x: x[1], reverse=True)
    targets = []
    for i, _ in comp_scores[:max_t]:
        cmask = (labeled == i)
        targets.append(centroid_weighted(x_c, y_c, z_c, np.maximum(cr * cmask, 0.0)))
    return targets


# =============================================================================
# MS-IRLS con tracking completo por iteracion
# =============================================================================

def solve_ms_irls_tracked(Ga_base, da_base, W, sG, Gn, gn, g_obs, m0,
                           beta_ms, eps_0, eps_min, cooling, max_iter, irls_tol,
                           ct, mask_true):
    """
    Minimum Support via IRLS con metricas extendidas por iteracion.
    Devuelve (m_final, rl2_final, rms_final, irls_info).
    """
    n_v      = len(W)
    n_base   = Ga_base.shape[0]
    n_rows_k = n_base + n_v

    m_prev    = np.clip(m0, 0.0, M_MAX)
    x_prev    = m_prev / np.maximum(W, 1e-12)
    eps       = eps_0
    converged = False
    history   = []

    t0 = time.perf_counter()

    for k in range(max_iter):
        denom_sq   = np.maximum(m_prev**2 + eps**2, eps_min**2)
        focus_diag = np.clip(W / np.sqrt(denom_sq), 0.0, 1.0 / eps_min)
        sqrt_bms   = float(np.sqrt(beta_ms))

        def _matvec(x, fd=focus_diag, sb=sqrt_bms):
            return np.concatenate([Ga_base @ x, sb * fd * x])

        def _rmatvec(y, fd=focus_diag, sb=sqrt_bms):
            return Ga_base.T @ y[:n_base] + sb * fd * y[n_base:]

        op   = LinearOperator((n_rows_k, n_v), matvec=_matvec, rmatvec=_rmatvec, dtype=np.float64)
        da_k = np.concatenate([da_base, np.zeros(n_v)])
        sol  = lsqr(op, da_k, damp=0.0, atol=1e-6, btol=1e-6, iter_lim=200, show=False, x0=x_prev)
        x_new = sol[0]
        m_new = np.clip(x_new * W, 0.0, M_MAX)

        delta = float(np.linalg.norm(m_new - m_prev) / max(np.linalg.norm(m_new), 1e-9))
        r_base  = Ga_base @ x_new - da_base
        r_focus = sqrt_bms * focus_diag * x_new
        obj     = float(0.5 * (np.dot(r_base, r_base) + np.dot(r_focus, r_focus)))

        # Metricas extendidas por iteracion
        _, _, rms_i = _residual_stats(Gn, m_new, W, sG, g_obs)
        corr_i, iou_i, f1_i, _, _, yerr_i, shl_i, pra_i, topk_i, nact_i, maxd_i = \
            compute_metrics_extended(m_new, ct, mask_true)

        # P90 / P92.5 target Y (centroide del componente mas denso)
        p90_tgts  = topological_targets(m_new, m_new >= np.percentile(m_new, 90.0))
        p925_tgts = topological_targets(m_new, m_new >= np.percentile(m_new, 92.5))
        p90_y  = float(p90_tgts[0][1])  if p90_tgts  else -1.0
        p925_y = float(p925_tgts[0][1]) if p925_tgts else -1.0

        history.append({
            "iter": k, "eps": eps, "delta": delta, "obj": obj,
            "n_active": nact_i, "max_density": maxd_i, "rms": rms_i,
            "corr": corr_i, "iou": iou_i, "f1": f1_i,
            "prauc": pra_i, "topk": topk_i,
            "y_err": yerr_i, "shallow_mass": shl_i,
            "p90_y": p90_y, "p925_y": p925_y,
        })

        x_prev = x_new
        m_prev = m_new
        eps    = max(eps * cooling, eps_min)

        if delta < irls_tol:
            converged = True
            break

    t_total = time.perf_counter() - t0
    m_final  = m_prev
    _, rl2_final, rms_final = _residual_stats(Gn, m_final, W, sG, g_obs)

    return m_final, rl2_final, rms_final, {
        "converged":   converged,
        "iters_done":  len(history),
        "eps_final":   float(eps),
        "delta_final": history[-1]["delta"] if history else 0.0,
        "t_total":     t_total,
        "history":     history,
    }


# =============================================================================
# Deteccion de rebote
# =============================================================================

def detect_rebound(history, baseline_shallow):
    """
    Rebote si:
    - active_voxels_final > 2.0 * min_active_voxels a lo largo de la corrida
    - shallow_mass_final > shallow_mass_baseline + 25 puntos porcentuales
    - PR-AUC cae mas de 50% respecto al mejor PR-AUC previo en esa corrida
    """
    if not history:
        return False, "no_history"

    min_active   = min(h["n_active"]     for h in history)
    final_active = history[-1]["n_active"]
    final_shallow = history[-1]["shallow_mass"]

    max_prauc_seen = 0.0
    rebound_prauc  = False
    for h in history:
        if h["prauc"] > max_prauc_seen:
            max_prauc_seen = h["prauc"]
        elif max_prauc_seen > 1e-6 and h["prauc"] < 0.5 * max_prauc_seen:
            rebound_prauc = True
            break

    reasons = []
    if final_active > 2.0 * max(min_active, 1):
        reasons.append(f"active_exp({min_active}->{final_active})")
    if final_shallow > baseline_shallow + 25.0:
        reasons.append(f"shallow_surge({baseline_shallow:.1f}%->{final_shallow:.1f}%)")
    if rebound_prauc:
        reasons.append("prauc_drop50pct")

    return (len(reasons) > 0), ("|".join(reasons) if reasons else "none")


# =============================================================================
# Best iters y composite score
# =============================================================================

def find_best_iters(history):
    """
    Indices del mejor iter por PR-AUC, Top-K y score compuesto.
    Composite = 0.30*norm(PRAUC) + 0.25*norm(TopK) + 0.20*norm(IoU)
              - 0.15*norm(|Yerr|) - 0.10*norm(shallow_mass)
    """
    if not history:
        return 0, 0, 0

    prauc_arr = np.array([h["prauc"]            for h in history])
    topk_arr  = np.array([h["topk"]             for h in history])
    iou_arr   = np.array([h["iou"]              for h in history])
    yerr_arr  = np.array([abs(h["y_err"])        for h in history])
    shl_arr   = np.array([h["shallow_mass"]      for h in history])

    def norm01(arr):
        rng = arr.max() - arr.min()
        return (arr - arr.min()) / rng if rng > 1e-12 else np.ones_like(arr) * 0.5

    comp = (
        0.30 * norm01(prauc_arr)
      + 0.25 * norm01(topk_arr)
      + 0.20 * norm01(iou_arr)
      - 0.15 * norm01(yerr_arr)
      - 0.10 * norm01(shl_arr)
    )
    return int(np.argmax(prauc_arr)), int(np.argmax(topk_arr)), int(np.argmax(comp))


# =============================================================================
# Runner principal
# =============================================================================

def run():
    n_combos  = len(SWEEP_EPS_MIN) * len(SWEEP_BETA_MS) * len(SWEEP_COOLING)
    n_runs    = n_combos * len(SWEEP_SCENARIOS)

    print("=" * 145)
    print("TerraQuantum - Sweep de Estabilidad Minimum Support / IRLS  [Fase 1.7C.3L.1]")
    print(f"  Grillas: EPS_MIN={SWEEP_EPS_MIN}  BETA_MS={SWEEP_BETA_MS}  COOLING={SWEEP_COOLING}")
    print(f"  Fijos:   BETA={BETA}  ALPHA_SPATIAL={ALPHA_SPATIAL}  LAMBDA_MAG={LAMBDA_MAG}  EPS_0={EPS_0}")
    print(f"  MAX_IRLS={MAX_IRLS}  IRLS_TOL={IRLS_TOL}  Escenarios={SWEEP_SCENARIOS}")
    print(f"  Total: {n_combos} combinaciones x {len(SWEEP_SCENARIOS)} escenarios = {n_runs} corridas")
    print("=" * 145)

    # -------------------------------------------------------------------------
    # [1] Kernel
    # -------------------------------------------------------------------------
    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0  = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter() - t0:.1f}s.")

    all_scenarios = generate_scenarios()
    scenarios     = {k: v for k, v in all_scenarios.items() if k in SWEEP_SCENARIOS}
    np.random.seed(42)

    # -------------------------------------------------------------------------
    # [2] LSQR baseline (una vez por escenario, se reutiliza en todo el sweep)
    # -------------------------------------------------------------------------
    print("\n[2] Calculando LSQR baseline por escenario...")
    lsqr_cache = {}
    for sc_name, ct in scenarios.items():
        mask_true = ct >= PHYSICAL_CONTRAST_THR
        g_exact   = kernel @ ct
        ns        = 0.01 * np.max(np.abs(g_exact))
        g_obs     = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        Ga_full, da_full, W, sG, Gn, gn, n_v = build_augmented_system(kernel, g_obs, BETA, ALPHA_SPATIAL)
        Ga_base = Ga_full[:-n_v, :]
        da_base = da_full[:-n_v]

        tl = time.perf_counter()
        m_lsqr, _, t_l, rl2_l, rms_l, rms_fin_l, res_l = \
            solve_lsqr_baseline(Ga_full, da_full, W, sG, Gn, gn, g_obs)
        print(f"    {sc_name}: {time.perf_counter() - tl:.1f}s")

        corr_l, iou_l, f1_l, _, _, yerr_l, shl_l, pra_l, topk_l, nact_l, maxd_l = \
            compute_metrics_extended(m_lsqr, ct, mask_true)

        lsqr_cache[sc_name] = {
            "ct": ct, "mask_true": mask_true, "g_obs": g_obs,
            "Ga_base": Ga_base, "da_base": da_base,
            "W": W, "sG": sG, "Gn": Gn, "gn": gn,
            "m_lsqr": m_lsqr, "t_lsqr": t_l,
            "lm": {  # lsqr metrics
                "corr": corr_l, "iou": iou_l, "f1": f1_l,
                "y_err": yerr_l, "shl": shl_l, "pra": pra_l,
                "topk": topk_l, "nact": nact_l, "maxd": maxd_l,
            },
        }

    print("\n  LSQR baseline reference:")
    hdr_ref = f"    {'Escenario':<16} | {'PRAUC':>6} | {'TopK':>5} | {'IoU':>5} | {'Yerr':>6} | {'Shl%':>5} | {'NAct':>5}"
    print(hdr_ref)
    print("    " + "-" * (len(hdr_ref) - 4))
    for sc_name, c in lsqr_cache.items():
        lm = c["lm"]
        print(f"    {sc_name:<16} | {lm['pra']:>6.4f} | {lm['topk']:>5.3f} | {lm['iou']:>5.3f} | "
              f"{lm['y_err']:>6.1f} | {lm['shl']:>4.1f}% | {lm['nact']:>5d}")

    # -------------------------------------------------------------------------
    # [3] Sweep MS-IRLS
    # -------------------------------------------------------------------------
    print(f"\n[3] Sweep MS-IRLS ({n_runs} corridas)...")
    all_results    = []
    combo_list     = list(itertools.product(SWEEP_EPS_MIN, SWEEP_BETA_MS, SWEEP_COOLING))
    run_count      = 0
    t_sweep_start  = time.perf_counter()

    for eps_min, beta_ms, cooling in combo_list:
        for sc_name in SWEEP_SCENARIOS:
            run_count += 1
            cache     = lsqr_cache[sc_name]
            baseline_shallow = cache["lm"]["shl"]

            m_final, rl2_f, rms_f, info = solve_ms_irls_tracked(
                cache["Ga_base"], cache["da_base"],
                cache["W"], cache["sG"], cache["Gn"], cache["gn"], cache["g_obs"],
                m0=cache["m_lsqr"],
                beta_ms=beta_ms, eps_0=EPS_0, eps_min=eps_min,
                cooling=cooling, max_iter=MAX_IRLS, irls_tol=IRLS_TOL,
                ct=cache["ct"], mask_true=cache["mask_true"],
            )

            rebound, rb_reason = detect_rebound(info["history"], baseline_shallow)
            bi_prauc, bi_topk, bi_comp = find_best_iters(info["history"])

            h = info["history"]
            fh = h[-1]          if h else {}
            ph = h[bi_prauc]    if h else {}
            th = h[bi_topk]     if h else {}
            ch = h[bi_comp]     if h else {}

            elapsed = time.perf_counter() - t_sweep_start
            eta     = (elapsed / run_count) * (n_runs - run_count) if run_count > 0 else 0
            rb_tag  = "[RB]" if rebound else "    "
            print(f"  {run_count:>3}/{n_runs} {rb_tag} "
                  f"eps={eps_min:.2f} bms={beta_ms:.0e} cl={cooling:.2f} | "
                  f"{sc_name:<12} | {info['t_total']:>5.1f}s | "
                  f"conv={str(info['converged']):<5} iters={info['iters_done']:>2} | "
                  f"best_pra={ph.get('prauc',0):.4f}@{bi_prauc} "
                  f"fin_pra={fh.get('prauc',0):.4f} "
                  f"shl_fin={fh.get('shallow_mass',0):.1f}% | ETA={eta:.0f}s")

            all_results.append({
                "eps_min": eps_min, "beta_ms": beta_ms, "cooling": cooling,
                "sc": sc_name,
                "converged":  info["converged"],
                "iters":      info["iters_done"],
                "rebound":    rebound,
                "rb_reason":  rb_reason,
                # indices best iters
                "bi_prauc": bi_prauc, "bi_topk": bi_topk, "bi_comp": bi_comp,
                # final metrics
                "fin_prauc":   fh.get("prauc",        0.0),
                "fin_topk":    fh.get("topk",         0.0),
                "fin_iou":     fh.get("iou",          0.0),
                "fin_yerr":    fh.get("y_err",        0.0),
                "fin_shallow": fh.get("shallow_mass", 0.0),
                "fin_active":  fh.get("n_active",     0),
                "fin_maxd":    fh.get("max_density",  0.0),
                # best by PR-AUC
                "best_prauc":      ph.get("prauc",        0.0),
                "best_prauc_topk": ph.get("topk",         0.0),
                "best_prauc_iou":  ph.get("iou",          0.0),
                "best_prauc_yerr": ph.get("y_err",        0.0),
                "best_prauc_shl":  ph.get("shallow_mass", 0.0),
                "best_prauc_act":  ph.get("n_active",     0),
                # best by Top-K
                "best_topk":       th.get("topk",         0.0),
                "best_topk_prauc": th.get("prauc",        0.0),
                # best by composite
                "best_comp_prauc": ch.get("prauc",        0.0),
                "best_comp_topk":  ch.get("topk",         0.0),
                "best_comp_iou":   ch.get("iou",          0.0),
                "best_comp_shl":   ch.get("shallow_mass", 0.0),
                # lsqr reference
                "lsqr_prauc":  cache["lm"]["pra"],
                "lsqr_topk":   cache["lm"]["topk"],
                "lsqr_iou":    cache["lm"]["iou"],
                "lsqr_shl":    cache["lm"]["shl"],
                "lsqr_active": cache["lm"]["nact"],
                # full history (para analisis posterior)
                "history": info["history"],
            })

    t_sweep = time.perf_counter() - t_sweep_start
    print(f"\n  Sweep completado en {t_sweep:.1f}s ({t_sweep/60:.1f} min)  "
          f"(~{t_sweep/n_runs:.1f}s/corrida)")

    # =========================================================================
    # TABLA A: por combinacion x escenario
    # =========================================================================
    print("\n\n" + "=" * 145)
    print("TABLA A: Resultados por combinacion x escenario")
    print(f"  Rebote: active_final > 2*min_active  O  shallow_final > baseline+25pp  O  PRAUC baja >50%")
    print("=" * 145)
    hdr_a = (f"{'EPS_MIN':>7} {'BETA_MS':>8} {'COOL':>4} | {'Escenario':<14} | "
             f"{'Reb?':>4} | {'BestIt':>6} | {'BstPRAUC':>8} | {'FinPRAUC':>8} | "
             f"{'BstTopK':>7} | {'FinTopK':>7} | {'BstIoU':>6} | "
             f"{'FinShl%':>7} | {'FinAct':>6} | {'Conv':>5} | {'Iters':>5}")
    print(hdr_a)
    print("-" * 145)
    for r in all_results:
        rb_str = "[RB]" if r["rebound"] else "    "
        print(f"{r['eps_min']:>7.2f} {r['beta_ms']:>8.0e} {r['cooling']:>4.2f} | "
              f"{r['sc']:<14} | "
              f"{rb_str:>4} | {r['bi_prauc']:>6} | "
              f"{r['best_prauc']:>8.4f} | {r['fin_prauc']:>8.4f} | "
              f"{r['best_topk']:>7.3f} | {r['fin_topk']:>7.3f} | "
              f"{r['best_prauc_iou']:>6.3f} | "
              f"{r['fin_shallow']:>6.1f}% | {r['fin_active']:>6d} | "
              f"{str(r['converged']):>5} | {r['iters']:>5}")

    # =========================================================================
    # TABLA B: ranking global por combinacion
    # =========================================================================
    print("\n\n" + "=" * 145)
    print("TABLA B: Ranking global por configuracion (media sobre 3 escenarios)")
    print("  Ordenado: rebounds asc, luego mean best PRAUC desc")
    print("=" * 145)

    combo_keys = list(dict.fromkeys(
        (r["eps_min"], r["beta_ms"], r["cooling"]) for r in all_results
    ))
    combo_summary = []
    for key in combo_keys:
        em, bm, cl = key
        rows = [r for r in all_results
                if r["eps_min"] == em and r["beta_ms"] == bm and r["cooling"] == cl]
        n_rb   = sum(1 for r in rows if r["rebound"])
        n_conv = sum(1 for r in rows if r["converged"])
        mn_bst_pra  = float(np.mean([r["best_prauc"]      for r in rows]))
        mn_bst_topk = float(np.mean([r["best_topk"]       for r in rows]))
        mn_bst_iou  = float(np.mean([r["best_prauc_iou"]  for r in rows]))
        mn_bst_yerr = float(np.mean([abs(r["best_prauc_yerr"]) for r in rows]))
        mn_fin_shl  = float(np.mean([r["fin_shallow"]     for r in rows]))
        mn_fin_act  = float(np.mean([r["fin_active"]      for r in rows]))
        mn_lsqr_pra = float(np.mean([r["lsqr_prauc"]     for r in rows]))
        gain_pra    = mn_bst_pra - mn_lsqr_pra
        combo_summary.append({
            "eps_min": em, "beta_ms": bm, "cooling": cl,
            "n_rb": n_rb, "n_conv": n_conv,
            "mn_bst_pra": mn_bst_pra, "mn_bst_topk": mn_bst_topk,
            "mn_bst_iou": mn_bst_iou, "mn_bst_yerr": mn_bst_yerr,
            "mn_fin_shl": mn_fin_shl, "mn_fin_act": mn_fin_act,
            "gain_pra": gain_pra,
        })

    combo_summary.sort(key=lambda x: (x["n_rb"], -x["mn_bst_pra"]))

    hdr_b = (f"{'Rank':>4} | {'EPS_MIN':>7} {'BETA_MS':>8} {'COOL':>4} | "
             f"{'Conv/3':>6} | {'Reb/3':>5} | "
             f"{'mBstPRAUC':>9} | {'GainPRAUC':>9} | "
             f"{'mBstTopK':>8} | {'mBstIoU':>7} | "
             f"{'mBstYerr':>8} | {'mFinShl%':>8} | {'mFinAct':>7}")
    print(hdr_b)
    print("-" * 145)
    for rank, s in enumerate(combo_summary, 1):
        rb_flag = " <--RB" if s["n_rb"] > 0 else ""
        print(f"{rank:>4} | {s['eps_min']:>7.2f} {s['beta_ms']:>8.0e} {s['cooling']:>4.2f} | "
              f"{s['n_conv']:>6} | {s['n_rb']:>5} | "
              f"{s['mn_bst_pra']:>9.4f} | {s['gain_pra']:>+9.4f} | "
              f"{s['mn_bst_topk']:>8.3f} | {s['mn_bst_iou']:>7.3f} | "
              f"{s['mn_bst_yerr']:>8.1f} | {s['mn_fin_shl']:>7.1f}% | "
              f"{s['mn_fin_act']:>7.0f}{rb_flag}")

    # =========================================================================
    # TABLA C: Recomendacion
    # =========================================================================
    print("\n\n" + "=" * 145)
    print("TABLA C: RECOMENDACION TECNICA  [Fase 1.7C.3L.1]")
    print("=" * 145)

    stable   = [s for s in combo_summary if s["n_rb"] == 0]
    unstable = [s for s in combo_summary if s["n_rb"] > 0]
    lsqr_ref_pra = float(np.mean([c["lm"]["pra"] for c in lsqr_cache.values()]))

    print(f"\n  LSQR baseline reference:  mean PR-AUC = {lsqr_ref_pra:.4f} (3 escenarios)")

    print(f"\n  [A] CONFIGURACIONES ESTABLES (0 rebotes):")
    if stable:
        print(f"      Total: {len(stable)}/{len(combo_summary)} configuraciones sin rebote")
        best = stable[0]
        print(f"\n      MEJOR CONFIGURACION ESTABLE:")
        print(f"        EPS_MIN={best['eps_min']}  BETA_MS={best['beta_ms']:.0e}  COOLING={best['cooling']}")
        print(f"        Conv={best['n_conv']}/3  |  mean best PR-AUC={best['mn_bst_pra']:.4f}  "
              f"gain={best['gain_pra']:+.4f}  |  mean best Top-K={best['mn_bst_topk']:.3f}")
        print(f"        mean best IoU={best['mn_bst_iou']:.3f}  |  "
              f"mean best Yerr={best['mn_bst_yerr']:.1f}m  |  mean shallow_final={best['mn_fin_shl']:.1f}%")
        if best["gain_pra"] > 0.02:
            print(f"        -> [OK] MS supera al baseline LSQR en PR-AUC.")
        elif best["gain_pra"] > -0.02:
            print(f"        -> [!!] MS similar al baseline. Mejora geometrica marginal.")
        else:
            print(f"        -> [NO] MS estable pero por debajo del baseline.")
    else:
        print(f"      [NO] Ninguna configuracion evito todos los rebotes.")
        if unstable:
            least = min(unstable, key=lambda x: x["n_rb"])
            print(f"      Menor cantidad de rebotes: EPS_MIN={least['eps_min']} "
                  f"BETA_MS={least['beta_ms']:.0e} COOLING={least['cooling']} "
                  f"({least['n_rb']}/3 rebounds)")

    print(f"\n  [B] PATRON DE INESTABILIDAD:")
    n_total_rb = sum(1 for r in all_results if r["rebound"])
    print(f"      Rebotes totales: {n_total_rb}/{n_runs} corridas ({100*n_total_rb/n_runs:.0f}%)")

    print(f"\n      Por EPS_MIN:")
    for em in SWEEP_EPS_MIN:
        rows_em = [r for r in all_results if r["eps_min"] == em]
        n_rb_em = sum(1 for r in rows_em if r["rebound"])
        print(f"        EPS_MIN={em:.2f}: {n_rb_em:>2}/{len(rows_em)} rebotes")

    print(f"\n      Por BETA_MS:")
    for bm in SWEEP_BETA_MS:
        rows_bm = [r for r in all_results if r["beta_ms"] == bm]
        n_rb_bm = sum(1 for r in rows_bm if r["rebound"])
        print(f"        BETA_MS={bm:.0e}: {n_rb_bm:>2}/{len(rows_bm)} rebotes")

    print(f"\n      Por COOLING:")
    for cl in SWEEP_COOLING:
        rows_cl = [r for r in all_results if r["cooling"] == cl]
        n_rb_cl = sum(1 for r in rows_cl if r["rebound"])
        print(f"        COOLING={cl:.2f}: {n_rb_cl:>2}/{len(rows_cl)} rebotes")

    print(f"\n  [C] PROXIMOS PASOS:")
    if stable and stable[0]["gain_pra"] > 0.02:
        print(f"      1. Configuracion estable encontrada con mejora real sobre LSQR.")
        print(f"         Siguiente fase: validar en los 5 escenarios completos.")
        print(f"         Luego sweep Fase 1.7C.3L.2: barrer ALPHA_SPATIAL=[2.0, 1.0, 0.5]")
        print(f"         manteniendo la mejor (EPS_MIN, BETA_MS, COOLING).")
    elif stable:
        print(f"      1. Configuracion estable encontrada pero sin mejora clara sobre LSQR.")
        print(f"         El regularizador Tikhonov (ALPHA_SPATIAL=2.0) domina sobre el prior MS.")
        print(f"         Siguiente fase 1.7C.3L.2: reducir ALPHA_SPATIAL=[2.0, 1.0, 0.5, 0.2]")
        print(f"         para dar mas espacio al focusing MS.")
    else:
        print(f"      1. MS puro es inestable con BETA=1.0 y ALPHA_SPATIAL=2.0.")
        print(f"         Opciones para Fase 1.7C.3L.2:")
        print(f"         a) Reducir ALPHA_SPATIAL: 2.0 -> 0.5 (primer intento recomendado)")
        print(f"         b) Reducir BETA depth-weight: 1.0 -> 0.5")
        print(f"         c) Pasar a Lp-norm focusing (p=0.8) si MS sigue fallando")
        print(f"         Recomendacion: intentar opcion (a) primero.")

    print(f"\n  [D] CONVERGENCIA IRLS:")
    n_conv_total = sum(1 for r in all_results if r["converged"])
    print(f"      Total convergencias: {n_conv_total}/{n_runs} ({100*n_conv_total/n_runs:.0f}%)")
    for em in SWEEP_EPS_MIN:
        rows_em = [r for r in all_results if r["eps_min"] == em]
        n_c = sum(1 for r in rows_em if r["converged"])
        print(f"        EPS_MIN={em:.2f}: {n_c}/{len(rows_em)} convergencias")

    print("\nFin del sweep de estabilidad MS-IRLS  [Fase 1.7C.3L.1]\n")


if __name__ == "__main__":
    run()
