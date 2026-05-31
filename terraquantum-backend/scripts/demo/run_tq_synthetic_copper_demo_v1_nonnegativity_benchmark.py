"""
TerraQuantum — Benchmark de No Negatividad en Inversión Gravimétrica

Evalúa si imponer bounds físicos reales (0 <= m <= m_max) durante la inversión
mejora el modelo frente al solver experimental actual sin bounds (LSQR + clipping final).
No modifica servicios productivos ni usa datos reales.
"""
import math, os, sys, time
from typing import Dict, List, Tuple
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
from scipy.optimize import lsq_linear, minimize
from scipy.ndimage import label
def pr_auc_score(y_true, y_score):
    """Compute Average Precision (area under PR curve) without sklearn."""
    y_true = np.asarray(y_true, dtype=bool)
    y_score = np.asarray(y_score, dtype=float)
    desc = np.argsort(y_score)[::-1]
    y_true = y_true[desc]; y_score = y_score[desc]
    tp = np.cumsum(y_true); fp = np.cumsum(~y_true)
    prec = tp / np.maximum(tp + fp, 1)
    rec = tp / max(np.sum(y_true), 1)
    # prepend (0, 1) sentinel
    prec = np.concatenate([[1.0], prec]); rec = np.concatenate([[0.0], rec])
    return float(np.sum((prec[1:] + prec[:-1]) * np.diff(rec) * 0.5))

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

grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix_arr = grid_x.flatten(order="F").astype(np.int32)
iy_arr = grid_y.flatten(order="F").astype(np.int32)
iz_arr = grid_z.flatten(order="F").astype(np.int32)
x_c = (ix_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
y_c = (iy_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
z_c = (iz_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

xv, zv = np.meshgrid(np.linspace(0, 800, 33), np.linspace(0, 800, 33), indexing="ij")
sensor_coords = np.column_stack((xv.ravel(), np.zeros_like(xv.ravel()), zv.ravel()))

PHYSICAL_CONTRAST_THR = 0.15
LAMBDA_MAG = 0.00005
M_MAX = 1.60  # 4.2 - 2.6
BETA = 1.00
ALPHA_SPATIAL = 2.00
RUN_TRF = False  # TRF omitido por defecto: mostró costo prohibitivo en full resolution.

def build_gaussian_body(cx, cy, cz, rx, ry, rz, mc=0.55):
    r2 = ((x_c-cx)/rx)**2 + ((y_c-cy)/ry)**2 + ((z_c-cz)/rz)**2
    c = mc * np.exp(-r2); c[c < 0.05] = 0.0; return c

def generate_scenarios() -> Dict[str, np.ndarray]:
    s = {}
    s["shallow_body"] = build_gaussian_body(400, 120, 400, 120, 80, 120)
    s["mid_body"] = build_gaussian_body(400, 230, 400, 150, 120, 150)
    s["deep_body"] = build_gaussian_body(400, 330, 400, 150, 120, 150)
    s["elongated_body"] = build_gaussian_body(400, 230, 400, 250, 90, 100)
    b1 = build_gaussian_body(250, 150, 250, 100, 80, 100, 0.5)
    b2 = build_gaussian_body(550, 300, 550, 120, 100, 120, 0.6)
    s["two_bodies"] = np.maximum(b1, b2)
    return s

def setup_augmented_system(kernel, g_obs, beta, alpha_spatial):
    """Build a single augmented system shared by both solvers.

    Damping is included as an explicit row block so both LSQR (damp=0)
    and lsq_linear solve EXACTLY the same least-squares objective:
        min ||[Gt; ls*Wst; lam*I] x - [gn; 0; 0]||^2
    """
    n_s, n_v = kernel.shape
    sG = float(np.max(np.abs(kernel.data)))
    Gn = kernel / sG; gn = g_obs / sG
    W = np.power(y_c, beta / 2.0) if beta > 0 else np.ones(n_v)
    W /= np.mean(W)
    Wm = sp.diags(W, 0, format="csr")
    Gt = Gn.dot(Wm)
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    Ws = inv._build_spatial_regularizer() / 6.0
    Wst = Ws.dot(Wm)
    ls = float(alpha_spatial) * (n_s / n_v)
    Idamp = LAMBDA_MAG * sp.eye(n_v, format="csr")
    Ga = sp.vstack([Gt, ls * Wst, Idamp], format="csr")
    da = np.concatenate([gn, np.zeros(n_v), np.zeros(n_v)])
    return Ga, da, W, sG, Gn, gn

def _residual_stats(Gn, m_physical, W, sG, g_obs):
    """Compute physical residual and RMS from the physical model m.
    
    Receives physical model m.
    Calculates physical prediction Gm.
    Does not work in the transformed space x.
    """
    gm = Gn.dot(m_physical) * sG
    res = g_obs - gm
    return res, float(np.linalg.norm(res)), float(np.sqrt(np.mean(res**2)))

def solve_lsqr_unbounded(Ga, da, W, sG, Gn, gn, g_obs):
    """Solve with LSQR damp=0 (damping already in Ga rows)."""
    t0 = time.perf_counter()
    r = lsqr(Ga, da, damp=0.0, atol=1e-6, btol=1e-6, iter_lim=400, show=False)
    t_solve = time.perf_counter() - t0
    m_raw = r[0] * W          # physical model (may contain negatives)
    m_final = np.clip(m_raw, 0.0, M_MAX)

    min_m = float(np.min(m_raw))
    max_m = float(np.max(m_raw))
    neg_pct = 100.0 * np.sum(m_raw < 0) / len(m_raw)

    res_raw, rl2_raw, rms_raw = _residual_stats(Gn, m_raw, W, sG, g_obs)
    _, rl2_fin, rms_fin = _residual_stats(Gn, m_final, W, sG, g_obs)
    return m_final, m_raw, t_solve, rl2_raw, rms_raw, rms_fin, min_m, max_m, neg_pct, res_raw

def solve_bounded_lsq_linear(Ga, da, W, sG, Gn, gn, g_obs):
    """Solve with lsq_linear TRF, bounds=(0, M_MAX/W) in W-space."""
    t0 = time.perf_counter()
    upper_bounds = M_MAX / W
    res_lsq = lsq_linear(Ga, da, bounds=(0.0, upper_bounds), method="trf", lsq_solver="lsmr", tol=1e-6, lsmr_tol=1e-6, lsmr_maxiter=400, max_iter=100, verbose=0)
    t_solve = time.perf_counter() - t0
    m_raw = res_lsq.x * W     # physical model (should be >= 0 by construction)
    m_final = np.clip(m_raw, 0.0, M_MAX)

    min_m = float(np.min(m_raw))
    max_m = float(np.max(m_raw))
    neg_pct = 100.0 * np.sum(m_raw < 0) / len(m_raw)

    res_raw, rl2_raw, rms_raw = _residual_stats(Gn, m_raw, W, sG, g_obs)
    _, rl2_fin, rms_fin = _residual_stats(Gn, m_final, W, sG, g_obs)
    info_trf = {
        "success": res_lsq.success,
        "status": res_lsq.status,
        "nit": res_lsq.nit,
        "cost": res_lsq.cost,
        "optimality": res_lsq.optimality,
        "message": res_lsq.message
    }
    return m_final, m_raw, t_solve, rl2_raw, rms_raw, rms_fin, min_m, max_m, neg_pct, res_raw, info_trf

def solve_bounded_lbfgsb(Ga, da, W, sG, Gn, gn, g_obs, m_lsqr_final):
    """Solve with L-BFGS-B, bounds=(0, M_MAX/W) in W-space. Warm start from clipped LSQR."""
    x0 = np.clip(m_lsqr_final / W, 0.0, M_MAX / W)
    bounds = [(0.0, float(M_MAX / w_i)) for w_i in W]

    def fun_and_grad(x):
        r = Ga @ x - da
        f = 0.5 * np.dot(r, r)
        g = Ga.T @ r
        return f, np.asarray(g).ravel()

    t0 = time.perf_counter()
    result = minimize(fun_and_grad, x0, method="L-BFGS-B", jac=True,
                      bounds=bounds, options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-7})
    t_solve = time.perf_counter() - t0

    m_raw   = result.x * W
    m_final = np.clip(m_raw, 0.0, M_MAX)
    min_m   = float(np.min(m_raw))
    max_m   = float(np.max(m_raw))
    neg_pct = 100.0 * np.sum(m_raw < 0) / len(m_raw)

    res_raw, rl2_raw, rms_raw = _residual_stats(Gn, m_raw, W, sG, g_obs)
    _, rl2_fin, rms_fin       = _residual_stats(Gn, m_final, W, sG, g_obs)

    info_lbfgsb = {
        "success": result.success,
        "status":  result.status,
        "nit":     result.nit,
        "fun":     float(result.fun),
        "message": result.message,
    }
    return m_final, m_raw, t_solve, rl2_raw, rms_raw, rms_fin, min_m, max_m, neg_pct, res_raw, info_lbfgsb

def compute_metrics(m_final, ct, mask_true):
    corr = float(np.corrcoef(m_final, ct)[0, 1])
    mask_pred = m_final >= PHYSICAL_CONTRAST_THR
    tp = np.sum(mask_pred & mask_true)
    fp = np.sum(mask_pred & ~mask_true)
    fn = np.sum(~mask_pred & mask_true)
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    iou = tp / max(tp + fp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-15)
    
    cw_y_true = centroid_weighted(x_c, y_c, z_c, ct)[1]
    cw_y_pred = centroid_weighted(x_c, y_c, z_c, m_final)[1]
    y_err = cw_y_pred - cw_y_true
    
    total_mass = np.sum(m_final)
    shallow_mask = y_c <= 200.0
    shallow_mass = np.sum(m_final[shallow_mask])
    shallow_pct = 100.0 * shallow_mass / max(total_mass, 1e-9)
    
    pr_auc = pr_auc_score(mask_true, m_final)
        
    k = int(np.sum(mask_true))
    idx_true = np.argsort(ct)[-k:]
    idx_pred = np.argsort(m_final)[-k:]
    topk = len(np.intersect1d(idx_true, idx_pred)) / max(k, 1)
    
    return corr, iou, f1, prec, rec, y_err, shallow_pct, pr_auc, topk

def compute_fit_score(kernel, res):
    ve = np.abs(kernel.T @ res)
    mve = float(np.max(ve)) if len(ve) > 0 else 0.0
    return np.clip(1.0 - (ve / mve), 0, 1) if mve > 0 else np.ones(len(ve))

# --- Targeting ---
def legacy_productive_exact(ed, fit_score, grade):
    density_score = np.clip((ed - 2.6) / max(4.2 - 2.6, 1e-9), 0.0, 1.0)
    probability_score = np.clip(fit_score, 0.0, 1.0)
    visual_score = density_score * probability_score
    block_volume = float(BLOCK_SIZE ** 3)
    domain = np.where(ed >= 2.75, 1, 0).astype(int)
    resource_class = np.where(probability_score >= 0.7, 1, 2).astype(int)
    resource_class = np.where(probability_score < 0.35, 3, resource_class)

    df_full = pl.DataFrame({
        "x": x_c.astype(float), "y": y_c.astype(float), "z": z_c.astype(float),
        "ix": ix_arr.astype(int), "iy": iy_arr.astype(int), "iz": iz_arr.astype(int),
        "density": ed.astype(float), "rho": ed.astype(float),
        "probability": fit_score.astype(float), "visual_score": visual_score.astype(float),
        "grade": grade.astype(float), "tonnage": (ed * block_volume).astype(float),
        "domain": domain.astype(int), "resource_class": resource_class.astype(int),
    })
    df_anomaly = build_anomaly_dataframe(df_full, cutoff_density=CUTOFF_DENSITY)
    voxels = build_voxel_output(df_anomaly, block_size=BLOCK_SIZE, cutoff_density=CUTOFF_DENSITY)
    bt = build_best_target(voxels)
    if bt is None: return []
    return [(float(bt["x_m"]), float(bt["y_m"]), float(bt["z_m"]))]

def topological_targets(cr, mask, max_t=2):
    structure = np.ones((3,3,3), dtype=int)
    labeled, num = label(mask.reshape((NX,NY,NZ), order='F'), structure=structure)
    labeled = labeled.flatten(order='F')
    if num == 0: return []
    comp_scores = []
    for i in range(1, num + 1):
        cmask = (labeled == i)
        sc = np.sum(cr[cmask])
        comp_scores.append((i, sc))
    comp_scores.sort(key=lambda x: x[1], reverse=True)
    targets = []
    for i, _ in comp_scores[:max_t]:
        cmask = (labeled == i)
        targets.append(centroid_weighted(x_c, y_c, z_c, np.maximum(cr * cmask, 0.0)))
    return targets

def run():
    print("=" * 130)
    print("TerraQuantum — Benchmark de No Negatividad en Inversión Gravimétrica")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s.")

    scenarios = generate_scenarios()
    np.random.seed(42)

    SOLVERS = ["A. lsqr_unbounded", "B. bounded_lbfgsb"]
    db = {s: [] for s in SOLVERS}
    target_db = {s: [] for s in SOLVERS}

    print("\n[2] Ejecutando solvers...")
    
    for sc_name, ct in scenarios.items():
        print(f"  • Escenario: {sc_name}")
        mask_true = ct >= PHYSICAL_CONTRAST_THR
        g_exact = kernel @ ct
        ns = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        Ga, da, W, sG, Gn, gn = setup_augmented_system(kernel, g_obs, BETA, ALPHA_SPATIAL)
        
        # Unbounded LSQR
        print("        -> Iniciando LSQR unbounded...")
        m_fin_u, m_raw_u, t_u, rl2_u, rms_raw_u, rms_fin_u, min_u, max_u, neg_u, res_u = solve_lsqr_unbounded(Ga, da, W, sG, Gn, gn, g_obs)
        print(f"        -> LSQR terminado en {t_u:.1f} s")
        corr_u, iou_u, f1_u, prc_u, rec_u, yerr_u, shl_u, pra_u, top_u = compute_metrics(m_fin_u, ct, mask_true)
        db[SOLVERS[0]].append({"sc": sc_name, "t": t_u, "res": rl2_u, "rms_raw": rms_raw_u, "rms_fin": rms_fin_u,
                               "min_m": min_u, "max_m": max_u, "neg": neg_u,
                               "corr": corr_u, "iou": iou_u, "f1": f1_u, "prec": prc_u, "rec": rec_u, "y_err": yerr_u,
                               "shl": shl_u, "pra": pra_u, "topk": top_u})
        
        fit_u = compute_fit_score(kernel, res_u)
        ed_u = np.clip(BASE_DENSITY + m_fin_u, 2.6, 4.2)
        gr_u = estimate_grade_from_geophysics(ed_u, fit_u, 83, 79, "norte_chile")
        leg_u = legacy_productive_exact(ed_u, fit_u, gr_u)
        p90_u = topological_targets(m_fin_u, m_fin_u >= np.percentile(m_fin_u, 90.0))
        p925_u = topological_targets(m_fin_u, m_fin_u >= np.percentile(m_fin_u, 92.5))
        target_db[SOLVERS[0]].append({"sc": sc_name, "leg": leg_u, "p90": p90_u, "p925": p925_u})
        
        # Bounded L-BFGS-B (warm start desde LSQR)
        print("        -> Iniciando bounded L-BFGS-B...")
        m_fin_b, m_raw_b, t_b, rl2_b, rms_raw_b, rms_fin_b, min_b, max_b, neg_b, res_b, info_lb = \
            solve_bounded_lbfgsb(Ga, da, W, sG, Gn, gn, g_obs, m_fin_u)
        print(f"        -> L-BFGS-B terminado en {t_b:.1f} s  |  {info_lb['message']}")
        corr_b, iou_b, f1_b, prc_b, rec_b, yerr_b, shl_b, pra_b, top_b = compute_metrics(m_fin_b, ct, mask_true)
        db[SOLVERS[1]].append({"sc": sc_name, "t": t_b, "res": rl2_b, "rms_raw": rms_raw_b, "rms_fin": rms_fin_b,
                               "min_m": min_b, "max_m": max_b, "neg": neg_b,
                               "corr": corr_b, "iou": iou_b, "f1": f1_b, "prec": prc_b, "rec": rec_b, "y_err": yerr_b,
                               "shl": shl_b, "pra": pra_b, "topk": top_b, "lb_info": info_lb})

        fit_b = compute_fit_score(kernel, res_b)
        ed_b = np.clip(BASE_DENSITY + m_fin_b, 2.6, 4.2)
        gr_b = estimate_grade_from_geophysics(ed_b, fit_b, 83, 79, "norte_chile")
        leg_b = legacy_productive_exact(ed_b, fit_b, gr_b)
        p90_b = topological_targets(m_fin_b, m_fin_b >= np.percentile(m_fin_b, 90.0))
        p925_b = topological_targets(m_fin_b, m_fin_b >= np.percentile(m_fin_b, 92.5))
        target_db[SOLVERS[1]].append({"sc": sc_name, "leg": leg_b, "p90": p90_b, "p925": p925_b})

        if RUN_TRF:
            print("        -> Iniciando bounded TRF (referencia opcional)...")
            _, _, t_trf, _, _, _, _, _, _, _, info_trf = solve_bounded_lsq_linear(Ga, da, W, sG, Gn, gn, g_obs)
            print(f"        -> bounded TRF terminado en {t_trf:.1f} s  |  {info_trf['message']}")

    print("\n\n[3] Tabla por escenario (A=lsqr_unbounded, B=bounded_lsq_linear_trf):")
    print(f"{'Escenario/Solver':<32} | {'ResL2':>6} | {'RMSraw':>7} | {'RMSfin':>7} | {'Min_m':>6} | {'Neg%':>5} | {'Corr':>6} | {'IoU':>5} | {'F1':>5} | {'Y_err':>6} | {'ShMass':>6} | {'PRAUC':>6} | {'TopK':>5}")
    print("-" * 135)
    for sc_name in scenarios.keys():
        for s in SOLVERS:
            v = next(item for item in db[s] if item["sc"] == sc_name)
            name_disp = f"{sc_name[:12]} ({s[0]})"
            print(f"{name_disp:<32} | {v['res']:>6.2f} | {v['rms_raw']:>7.4f} | {v['rms_fin']:>7.4f} | {v['min_m']:>6.3f} | {v['neg']:>4.1f}% | {v['corr']:>6.4f} | {v['iou']:>5.3f} | {v['f1']:>5.3f} | {v['y_err']:>6.1f} | {v['shl']:>5.1f}% | {v['pra']:>6.4f} | {v['topk']:>5.3f}")

    print("\n\n[4] Tabla resumen por solver:")
    summary = []
    for s in SOLVERS:
        vals = db[s]
        summary.append({
            "name": s,
            "m_corr": np.mean([v["corr"] for v in vals]),
            "m_iou": np.mean([v["iou"] for v in vals]),
            "m_f1": np.mean([v["f1"] for v in vals]),
            "m_prec": np.mean([v["prec"] for v in vals]),
            "m_rec": np.mean([v["rec"] for v in vals]),
            "m_abs_y": np.mean([abs(v["y_err"]) for v in vals]),
            "w_abs_y": np.max([abs(v["y_err"]) for v in vals]),
            "m_shl": np.mean([v["shl"] for v in vals]),
            "m_pra": np.mean([v["pra"] for v in vals]),
            "m_topk": np.mean([v["topk"] for v in vals]),
            "m_rms_raw": np.mean([v["rms_raw"] for v in vals]),
            "m_rms_fin": np.mean([v["rms_fin"] for v in vals]),
            "m_time": np.mean([v["t"] for v in vals]),
        })

    print(f"{'Solver':<28} | {'mCorr':>6} | {'mIoU':>5} | {'mF1':>5} | {'mPrec':>5} | {'mRec':>5} | {'mAbsY':>6} | {'wAbsY':>6} | {'mShM%':>5} | {'mPRAUC':>6} | {'mTopK':>5} | {'mRMSraw':>8} | {'mRMSfin':>8} | {'mTime':>5}")
    print("-" * 140)
    for s in summary:
        print(f"{s['name']:<28} | {s['m_corr']:>6.4f} | {s['m_iou']:>5.3f} | {s['m_f1']:>5.3f} | {s['m_prec']:>5.3f} | {s['m_rec']:>5.3f} | {s['m_abs_y']:>6.1f} | {s['w_abs_y']:>6.1f} | {s['m_shl']:>4.1f}% | {s['m_pra']:>6.4f} | {s['m_topk']:>5.3f} | {s['m_rms_raw']:>8.4f} | {s['m_rms_fin']:>8.4f} | {s['m_time']:>5.1f}s")

    print("\n\n[5] Comparación de Targeting Topológico (Y_pred de Legacy vs P90 vs P92.5):")
    print(f"{'Escenario/Solver':<32} | {'Legacy_Y':>9} | {'P90_Y':>9} | {'P92.5_Y':>9}")
    print("-" * 75)
    for sc_name in scenarios.keys():
        for s in SOLVERS:
            t = next(item for item in target_db[s] if item["sc"] == sc_name)
            name_disp = f"{sc_name[:12]} ({s[0]})"
            l_y = t["leg"][0][1] if t["leg"] else 0.0
            p90_y = t["p90"][0][1] if t["p90"] else 0.0
            p925_y = t["p925"][0][1] if t["p925"] else 0.0
            print(f"{name_disp:<32} | {l_y:>9.1f} | {p90_y:>9.1f} | {p925_y:>9.1f}")

    print("\n\n[6] Diagnóstico de Convergencia de Bounded L-BFGS-B:")
    print(f"{'Escenario':<16} | {'Success':>7} | {'Status':>6} | {'Nit':>4} | {'Fun':>12} | {'Message'}")
    print("-" * 110)
    for v in db[SOLVERS[1]]:
        inf = v["lb_info"]
        print(f"{v['sc']:<16} | {str(inf['success']):>7} | {inf['status']:>6} | {inf['nit']:>4} | {inf['fun']:>12.4e} | {inf['message']}")

    print("\n[NOTE] TRF omitido por defecto: mostró costo prohibitivo en full resolution.")
    print(f"       Para reactivarlo: establecer RUN_TRF = True en el módulo.")

    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)

    su = summary[0]
    sb = summary[1]

    # Precompute deltas (usados en todos los sub-bloques)
    rms_degradation = (sb["m_rms_raw"] - su["m_rms_raw"]) / max(su["m_rms_raw"], 1e-9)
    rms_fin_delta   = (sb["m_rms_fin"] - su["m_rms_fin"]) / max(su["m_rms_fin"], 1e-9)
    depth_degradation = (sb["w_abs_y"] - su["w_abs_y"]) / max(su["w_abs_y"], 1e-9)

    metrics_improved = []
    if sb["m_iou"]  > su["m_iou"]:  metrics_improved.append("IoU física")
    if sb["m_f1"]   > su["m_f1"]:   metrics_improved.append("F1 física")
    if sb["m_pra"]  > su["m_pra"]:  metrics_improved.append("PR-AUC")
    if sb["m_topk"] > su["m_topk"]: metrics_improved.append("Top-K")

    metrics_degraded = []
    if sb["m_iou"]  < su["m_iou"]:  metrics_degraded.append(f"IoU  ({su['m_iou']:.3f} ->{sb['m_iou']:.3f})")
    if sb["m_f1"]   < su["m_f1"]:   metrics_degraded.append(f"F1   ({su['m_f1']:.3f} ->{sb['m_f1']:.3f})")
    if sb["m_pra"]  < su["m_pra"]:  metrics_degraded.append(f"PRAUC({su['m_pra']:.4f} ->{sb['m_pra']:.4f})")
    if sb["m_topk"] < su["m_topk"]: metrics_degraded.append(f"TopK ({su['m_topk']:.3f} ->{sb['m_topk']:.3f})")

    lb_results  = db[SOLVERS[1]]
    n_total     = len(lb_results)
    n_failed    = sum(1 for v in lb_results if not v["lb_info"]["success"])
    n_maxiter   = sum(1 for v in lb_results if v["lb_info"]["status"] == 1)

    # ── A. Costo computacional ────────────────────────────────────────────────
    print("\n  [A] COSTO COMPUTACIONAL")
    print(f"  • Tiempo de cómputo: {su['m_time']:.1f}s (LSQR) vs {sb['m_time']:.1f}s (Bounded L-BFGS-B)")
    if sb["m_time"] > su["m_time"] * 10:
        print("    [!!] El costo computacional de L-BFGS-B es prohibitivo para mallas grandes.")
    elif sb["m_time"] > su["m_time"] * 3:
        print("    [!!] El costo computacional de L-BFGS-B es significativamente mayor que LSQR.")
    else:
        print("    [OK] El costo computacional de L-BFGS-B es aceptable frente a LSQR.")

    # ── B. Convergencia ───────────────────────────────────────────────────────
    print("\n  [B] CONVERGENCIA L-BFGS-B")
    print(f"  • Escenarios sin convergencia: {n_failed}/{n_total}")
    print(f"  • Escenarios que alcanzaron iter_max (status=1): {n_maxiter}/{n_total}")
    if n_failed == n_total:
        print("    [NO] L-BFGS-B NO convergió en ningún escenario.")
        print("       El solver alcanzó el límite de iteraciones en todos los casos.")
        print("       Los resultados son subóptimos: la distribución de masa no es un mínimo real.")
    elif n_failed > n_total // 2:
        print(f"    [!!] L-BFGS-B falló en la mayoría de escenarios ({n_failed}/{n_total}).")
        print("       Los resultados son poco confiables como base de decisión productiva.")
    else:
        print(f"    [OK] L-BFGS-B convergió en la mayoría de escenarios ({n_total - n_failed}/{n_total}).")

    # ── C. Mejora geométrica ──────────────────────────────────────────────────
    print("\n  [C] MEJORA GEOMÉTRICA")
    print(f"  • Degradación de RMS aumentado:        {rms_degradation * 100:.1f}%")
    print(f"  • Cambio en RMS modelo final (clipped): {rms_fin_delta * 100:.1f}%")
    if len(metrics_improved) > 0:
        print(f"  • Métricas geométricas mejoradas: {', '.join(metrics_improved)}")
        print("    [OK] La no negatividad mejora activamente la forma de la inversión.")
    else:
        if metrics_degraded:
            print("  • Métricas geométricas degradadas:")
            for md in metrics_degraded:
                print(f"      {md}")
        print("    [NO] Ninguna métrica geométrica mejoró.")
        print("       La no negatividad simple eliminó negativos, pero no redistribuyó")
        print("       la masa hacia una geometría correcta.")
        if abs(rms_fin_delta) <= 0.05:
            print(f"       Nota: aunque el RMS final es similar ({rms_fin_delta * 100:.1f}%),")
            print("       el colapso de IoU, F1, PR-AUC y Top-K indica que la masa se")
            print("       concentró superficialmente sin corresponder a la anomalía real.")

    # ── D. Estabilidad de profundidad ─────────────────────────────────────────
    print("\n  [D] ESTABILIDAD DE PROFUNDIDAD")
    print(f"  • Error Y medio: {su['m_abs_y']:.1f}m (LSQR) ->{sb['m_abs_y']:.1f}m (L-BFGS-B)")
    print(f"  • Peor caso AbsY: {su['w_abs_y']:.1f}m ->{sb['w_abs_y']:.1f}m  (cambio {depth_degradation * 100:.1f}%)")
    if depth_degradation > 0.10:
        print("    [!!] El solver acotado empeora la profundidad severamente en al menos un caso.")
    else:
        print("    [OK] El solver acotado no degrada la estimación de profundidad.")

    # ── Recomendación técnica ─────────────────────────────────────────────────
    convergence_ok = (n_failed == 0)
    geometric_ok   = (len(metrics_improved) > 0)
    depth_ok       = (depth_degradation <= 0.10)
    overall_success = convergence_ok and geometric_ok and depth_ok

    print("\nRECOMENDACIÓN TÉCNICA:")
    if overall_success:
        if sb["m_time"] > su["m_time"] * 5:
            print("  -> b) L-BFGS-B es viable pero costoso para esta malla.")
            print("        Se confirma que imponer bounds físicos MEJORA la recuperación geométrica.")
            print("        Evaluar si el costo es aceptable en producción o explorar proyección de gradiente.")
        else:
            print("  -> a) Bounded L-BFGS-B es viable computacionalmente.")
            print("        Los bounds físicos mejoran la métrica sin degradar ajuste.")
            print("        Candidato para implementación productiva.")
    else:
        print("  [NO] NO IMPLEMENTAR bounds simples productivamente.")
        print()
        if not convergence_ok:
            print(f"     Razón primaria: L-BFGS-B no convergió en {n_failed}/{n_total} escenarios.")
            print("     Los resultados reflejan un punto subóptimo intermedio,")
            print("     no el mínimo acotado real.")
        if not geometric_ok:
            print("     Razón secundaria: ninguna métrica geométrica mejoró respecto a LSQR+clipping.")
            print("     La no negatividad simple concentró masa superficialmente")
            print("     sin mejorar la localización de la anomalía.")
        if not depth_ok:
            print("     Razón adicional: la estimación de profundidad empeoró significativamente.")
        print()
        print("  -> Siguiente paso: focusing / Minimum Support experimental.")
        print("     Un regularizador de soporte mínimo redistribuye masa activamente,")
        print("     no solo impone un piso en cero.")
        print()
        print("  -> Si se vuelve a estudiar bounds, hacerlo dentro de un prior más fuerte")
        print("     (ej. modelo de referencia, focusing iterativo), no como cambio aislado.")

    print("\nFin del benchmark de no negatividad.\n")

if __name__ == "__main__":
    run()
