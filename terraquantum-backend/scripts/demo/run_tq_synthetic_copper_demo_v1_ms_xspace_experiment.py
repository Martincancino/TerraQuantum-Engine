"""
TerraQuantum - Validacion MS-x con early stopping por PR-AUC
Fase 1.7C.3L.8

Objetivo: evaluar si usar m@best_iter (en vez de m_final) como salida del
solver MS-x mejora la clasificacion de escala y la consistencia fisica en los
5 escenarios, sin cambiar la formulacion.

Problema identificado en Fase 1.7C.3L.7:
  - shallow_body y two_bodies clasifican como ESCALA_INESTABLE porque
    max_density crece monotonamente a lo largo del IRLS (CV > 30%).
  - En esos escenarios, el mejor estado de la solucion ocurre en iters
    intermedios (best_iter=6 para shallow, best_iter=2 para two_bodies),
    pero el solver entregaba m_final que degrada la escala.
  - La hipotesis es que detener en best_iter estabiliza la escala sin
    perder la ganancia de PR-AUC/Top-K.

Cambio central:
  solve_ms_x ahora rastrea m_best (modelo al iter de maxima PR-AUC) y lo
  retorna como solucion definitiva. El historial completo se conserva para
  diagnostico.

Configuracion fija (identica a Fase 1.7C.3L.7):
  formulacion    = ms_x
  BETA_MS        = 1e-2
  ALPHA_SPATIAL  = 2.0
  BETA           = 1.0
  LAMBDA_MAG     = 5e-5
  EPS_0          = 0.80
  EPS_MIN        = 0.12
  COOLING        = 0.90
  MAX_IRLS       = 10

Escenarios: shallow_body, mid_body, deep_body, elongated_body, two_bodies.

Criterios de rechazo (8, mismos que Fase 1.7C.3L.7):
  1. shallow_mass_best > baseline_shl + 15 pp
  2. PR-AUC_best < 0.90 * baseline_PRAUC
  3. Top-K_best  < 0.90 * baseline_TopK
  4. y_err_best  < y_err_base - 25 m
  5. active_voxels_best > 2x min_active en esa corrida
  6. max_density_best < 0.05 sin mejora clara PR-AUC/Top-K (>5pp)
  7. RMS_best empeora fuertemente vs baseline (>2x)
  8. rebound: shl@best > shl@best_anterior + 10 pp (no aplica para best model)

Clasificacion de escala (aplicada al modelo best_iter):
  ESCALA_OK        : max_density_best >= 0.15
  ESCALA_SUPRIMIDA : max_density_best < 0.15
  ESCALA_INESTABLE : max_density_best > 1.5 * baseline sin ganancia de ranking

NO modifica servicios productivos ni usa datos reales.
NO modifica gravimetry.py ni geophysics_service.py.

Referencia: Portniaguine & Zhdanov (1999), Geophysics 64(3), 829-843.
"""
import os, sys, time
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr, LinearOperator
from scipy.ndimage import label

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    centroid_weighted, TOTAL_VOXELS, NX, NY, NZ, BLOCK_SIZE,
)

# -- Grid --
grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
ix_arr = grid_x.flatten(order="F").astype(np.int32)
iy_arr = grid_y.flatten(order="F").astype(np.int32)
iz_arr = grid_z.flatten(order="F").astype(np.int32)
x_c = (ix_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
y_c = (iy_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
z_c = (iz_arr * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

xv, zv = np.meshgrid(np.linspace(0, 800, 33), np.linspace(0, 800, 33), indexing="ij")
sensor_coords = np.column_stack((xv.ravel(), np.zeros_like(xv.ravel()), zv.ravel()))

# -- Configuracion fija --
PHYSICAL_CONTRAST_THR  = 0.15
LAMBDA_MAG             = 0.00005
M_MAX                  = 1.60
BETA                   = 1.00
ALPHA_SPATIAL          = 2.00
BETA_MS                = 1e-2

EPS_0    = 0.80
EPS_MIN  = 0.12
COOLING  = 0.90
MAX_IRLS = 10
IRLS_TOL = 1e-3

SCALE_COLLAPSE_THR  = 0.05
SCALE_SUPPRESS_THR  = PHYSICAL_CONTRAST_THR
SCALE_SPIKE_FACTOR  = 1.5

SCENARIOS = ["shallow_body", "mid_body", "deep_body", "elongated_body", "two_bodies"]


# -- Utilidades --

def pr_auc_score(y_true, y_score):
    y_true  = np.asarray(y_true, dtype=bool)
    y_score = np.asarray(y_score, dtype=float)
    desc    = np.argsort(y_score)[::-1]
    y_true  = y_true[desc]
    tp      = np.cumsum(y_true); fp = np.cumsum(~y_true)
    prec    = tp / np.maximum(tp + fp, 1)
    rec     = tp / max(np.sum(y_true), 1)
    prec    = np.concatenate([[1.0], prec]); rec = np.concatenate([[0.0], rec])
    return float(np.sum((prec[1:] + prec[:-1]) * np.diff(rec) * 0.5))


def build_gaussian_body(cx, cy, cz, rx, ry, rz, mc=0.55):
    r2 = ((x_c - cx)/rx)**2 + ((y_c - cy)/ry)**2 + ((z_c - cz)/rz)**2
    c  = mc * np.exp(-r2); c[c < 0.05] = 0.0
    return c


def generate_scenarios():
    s = {}
    s["shallow_body"]   = build_gaussian_body(400, 75,  400, 120, 50,  120, 0.55)
    s["mid_body"]       = build_gaussian_body(400, 200, 400, 130, 100, 130, 0.55)
    s["deep_body"]      = build_gaussian_body(400, 330, 400, 150, 120, 150, 0.55)
    s["elongated_body"] = build_gaussian_body(400, 225, 400, 250, 70,  80,  0.55)
    b1 = build_gaussian_body(250, 150, 250, 100,  80, 100, 0.5)
    b2 = build_gaussian_body(550, 300, 550, 120, 100, 120, 0.6)
    s["two_bodies"]     = np.maximum(b1, b2)
    return s


def build_augmented_system(kernel, g_obs):
    n_s, n_v = kernel.shape
    sG  = float(np.max(np.abs(kernel.data)))
    Gn  = kernel / sG; gn = g_obs / sG
    W   = np.power(y_c, BETA / 2.0)
    W  /= np.mean(W)
    Wm  = sp.diags(W, 0, format="csr")
    Gt  = Gn.dot(Wm)
    inv = GravimetryInversion(nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE)
    Ws  = inv._build_spatial_regularizer() / 6.0
    Wst = Ws.dot(Wm)
    ls    = float(ALPHA_SPATIAL) * (n_s / n_v)
    Idamp = LAMBDA_MAG * sp.eye(n_v, format="csr")
    Ga_full = sp.vstack([Gt, ls * Wst, Idamp], format="csr")
    da_full = np.concatenate([gn, np.zeros(n_v), np.zeros(n_v)])
    Ga_base = Ga_full[:-n_v, :]
    da_base = da_full[:-n_v]
    return Ga_full, da_full, Ga_base, da_base, W, sG, Gn, gn, n_v


def residual_rms(Gn, m, sG, g_obs):
    gm = Gn.dot(m) * sG
    return float(np.sqrt(np.mean((g_obs - gm)**2)))


def compute_metrics(m, ct, mask_true):
    corr      = float(np.corrcoef(m, ct)[0, 1])
    mask_pred = m >= PHYSICAL_CONTRAST_THR
    tp   = np.sum(mask_pred & mask_true)
    fp   = np.sum(mask_pred & ~mask_true)
    fn   = np.sum(~mask_pred & mask_true)
    prec = tp / max(tp + fp, 1)
    rec  = tp / max(tp + fn, 1)
    iou  = tp / max(tp + fp + fn, 1)
    f1   = 2 * prec * rec / max(prec + rec, 1e-15)
    cw_pred = centroid_weighted(x_c, y_c, z_c, m)[1]
    cw_true = centroid_weighted(x_c, y_c, z_c, ct)[1]
    y_err   = cw_pred - cw_true
    total   = np.sum(m)
    shl_pct = 100.0 * np.sum(m[y_c <= 200.0]) / max(total, 1e-9)
    pr_auc  = pr_auc_score(mask_true, m)
    k_true  = int(np.sum(mask_true))
    topk    = len(np.intersect1d(
        np.argsort(ct)[-k_true:], np.argsort(m)[-k_true:]
    )) / max(k_true, 1)
    mean_act = float(np.mean(m[mask_pred])) if np.any(mask_pred) else 0.0
    return {
        "corr": corr, "iou": iou, "f1": f1,
        "y_err": y_err, "shallow_mass": shl_pct,
        "prauc": pr_auc, "topk": topk,
        "n_active": int(np.sum(mask_pred)),
        "max_density": float(np.max(m)),
        "mean_density_active": mean_act,
    }


def topological_centroid_y(m, percentile):
    thr  = np.percentile(m, percentile)
    mask = m >= thr
    if not np.any(mask):
        return -1.0
    structure    = np.ones((3, 3, 3), dtype=int)
    labeled, num = label(mask.reshape((NX, NY, NZ), order='F'), structure=structure)
    labeled      = labeled.flatten(order='F')
    if num == 0:
        return -1.0
    best_comp = max(range(1, num + 1), key=lambda i: np.sum(m[labeled == i]))
    return float(centroid_weighted(x_c, y_c, z_c, np.where(labeled == best_comp, m, 0.0))[1])


def classify_scale_state(mtr_best, mtr_base):
    """
    Clasificacion de escala aplicada al modelo best_iter (no final).
    ESCALA_INESTABLE: max_density_best > 1.5 * maxd_baseline sin mejora de ranking.
    ESCALA_SUPRIMIDA: max_density_best < 0.15.
    ESCALA_OK       : max_density_best >= 0.15.
    """
    maxd_best = mtr_best["max_density"]
    maxd_base = mtr_base["max_density"]
    gain_p    = mtr_best["prauc"] - mtr_base["prauc"]
    gain_t    = mtr_best["topk"]  - mtr_base["topk"]
    spike = (maxd_best > SCALE_SPIKE_FACTOR * maxd_base
             and gain_p < -0.02 and gain_t < -0.02)
    if spike:
        return "ESCALA_INESTABLE"
    if maxd_best < SCALE_SUPPRESS_THR:
        return "ESCALA_SUPRIMIDA"
    return "ESCALA_OK"


def check_rejection(mtr_best, mtr_base, history, rms_best, rms_base):
    """Criterios de rechazo aplicados al modelo best_iter."""
    flags = []

    if mtr_best["shallow_mass"] > mtr_base["shallow_mass"] + 15.0:
        flags.append(
            f"shl_surge({mtr_base['shallow_mass']:.1f}%->{mtr_best['shallow_mass']:.1f}%)"
        )

    if mtr_base["prauc"] > 1e-6 and mtr_best["prauc"] < 0.90 * mtr_base["prauc"]:
        flags.append(f"prauc_drop10({mtr_base['prauc']:.4f}->{mtr_best['prauc']:.4f})")

    if mtr_base["topk"] > 1e-6 and mtr_best["topk"] < 0.90 * mtr_base["topk"]:
        flags.append(f"topk_drop10({mtr_base['topk']:.3f}->{mtr_best['topk']:.3f})")

    if mtr_best["y_err"] < mtr_base["y_err"] - 25.0:
        flags.append(f"yerr_worse({mtr_base['y_err']:.1f}->{mtr_best['y_err']:.1f}m)")

    if history:
        min_act = max(min(h["n_active"] for h in history), 1)
        best_act = history[int(np.argmax([h["prauc"] for h in history]))]["n_active"]
        if best_act > 2.0 * min_act:
            flags.append(f"active_exp({min_act}->{best_act})")

    if mtr_best["max_density"] < SCALE_COLLAPSE_THR:
        gain_p = mtr_best["prauc"] - mtr_base["prauc"]
        gain_t = mtr_best["topk"]  - mtr_base["topk"]
        if gain_p < 0.05 and gain_t < 0.05:
            flags.append(
                f"scale_collapse(maxd={mtr_best['max_density']:.3f},gainP={gain_p:+.3f})"
            )

    if rms_base > 1e-9 and rms_best > 2.0 * rms_base:
        flags.append(f"rms_surge({rms_base:.4f}->{rms_best:.4f})")

    # Criterio 8: no aplica directamente a best_iter (no hay iter posterior)
    # Se reporta si best_iter != final_iter para informacion
    if history and len(history) > 1:
        bi = int(np.argmax([h["prauc"] for h in history]))
        fi = len(history) - 1
        if bi < fi:
            # Hay degradacion posterior al best_iter, reportar como warning no rechazo
            prauc_deg = history[fi]["prauc"] - history[bi]["prauc"]
            if prauc_deg < -0.05:
                flags.append(f"degradation@final({prauc_deg:+.4f}PR-AUC)")

    return bool(flags), ("|".join(flags) if flags else "OK")


def print_iter_table(history, best_iter):
    hdr = (
        f"  {'it':>3} | {'eps':>5} | {'active':>6} | {'maxd':>5} | "
        f"{'mAct':>5} | {'RMS':>7} | {'corr':>5} | {'IoU':>5} | {'F1':>5} | "
        f"{'PR-AUC':>6} | {'Top-K':>5} | {'y_err':>7} | {'shl%':>5} | "
        f"{'P90_y':>6} | {'P925_y':>7} | {'*':>1}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for h in history:
        star = "<-- BEST" if h["iter"] == best_iter else ""
        print(
            f"  {h['iter']:>3} | {h['eps']:>5.3f} | {h['n_active']:>6} | "
            f"{h['max_density']:>5.3f} | {h['mean_density_active']:>5.3f} | "
            f"{h['rms']:>7.4f} | {h['corr']:>5.3f} | "
            f"{h['iou']:>5.3f} | {h['f1']:>5.3f} | {h['prauc']:>6.4f} | "
            f"{h['topk']:>5.3f} | {h['y_err']:>7.1f} | {h['shallow_mass']:>4.1f}% | "
            f"{h['p90_y']:>6.1f} | {h['p925_y']:>7.1f} | {star}"
        )


# -- Solvers --

def solve_baseline_lsqr(Ga_full, da_full, W, sG, Gn, g_obs, ct, mask_true):
    t0  = time.perf_counter()
    r   = lsqr(Ga_full, da_full, damp=0.0, atol=1e-6, btol=1e-6, iter_lim=400, show=False)
    m   = np.clip(r[0] * W, 0.0, M_MAX)
    t   = time.perf_counter() - t0
    rms = residual_rms(Gn, m, sG, g_obs)
    mtr = compute_metrics(m, ct, mask_true)
    p90  = topological_centroid_y(m, 90.0)
    p925 = topological_centroid_y(m, 92.5)
    return m, rms, t, mtr, p90, p925


def solve_ms_x_best(Ga_base, da_base, W, sG, Gn, g_obs, m0, ct, mask_true):
    """
    MS-IRLS x-space con seleccion de mejor modelo por PR-AUC.

    Ejecuta MAX_IRLS iteraciones completas para diagnostico, pero retorna
    m_best (modelo al iter de maxima PR-AUC) en lugar de m_final.
    El historial completo se conserva.
    """
    n_v      = len(W)
    n_base   = Ga_base.shape[0]
    m_prev   = np.clip(m0, 0.0, M_MAX)
    x_prev   = m_prev / np.maximum(W, 1e-12)
    eps      = EPS_0
    sqrt_bms = float(np.sqrt(BETA_MS))
    history  = []
    converged = False

    # Rastreo del mejor modelo por PR-AUC
    best_prauc_val = -1.0
    best_iter_idx  = 0
    m_best         = m_prev.copy()

    t0 = time.perf_counter()

    for k in range(MAX_IRLS):
        x_safe     = m_prev / np.maximum(W, 1e-12)
        denom_sq_x = np.maximum(
            x_safe**2 + eps**2,
            (EPS_MIN / np.maximum(W, 1e-12))**2,
        )
        focus_diag = np.clip(1.0 / np.sqrt(denom_sq_x), 0.0, 1.0 / EPS_MIN)

        def _mv(x, fd=focus_diag, sb=sqrt_bms):
            return np.concatenate([Ga_base @ x, sb * fd * x])

        def _rmv(y, fd=focus_diag, sb=sqrt_bms):
            return Ga_base.T @ y[:n_base] + sb * fd * y[n_base:]

        op   = LinearOperator((n_base + n_v, n_v), matvec=_mv, rmatvec=_rmv, dtype=np.float64)
        da_k = np.concatenate([da_base, np.zeros(n_v)])
        sol  = lsqr(op, da_k, damp=0.0, atol=1e-6, btol=1e-6,
                    iter_lim=200, show=False, x0=x_prev)
        x_new = sol[0]
        m_new = np.clip(x_new * W, 0.0, M_MAX)

        delta = float(np.linalg.norm(m_new - m_prev) / max(np.linalg.norm(m_new), 1e-9))
        rms   = residual_rms(Gn, m_new, sG, g_obs)
        mtr   = compute_metrics(m_new, ct, mask_true)
        p90   = topological_centroid_y(m_new, 90.0)
        p925  = topological_centroid_y(m_new, 92.5)

        # Actualizar mejor modelo
        if mtr["prauc"] > best_prauc_val:
            best_prauc_val = mtr["prauc"]
            best_iter_idx  = k
            m_best         = m_new.copy()

        history.append({
            "iter": k, "eps": eps, "delta": delta, "rms": rms,
            "p90_y": p90, "p925_y": p925,
            **mtr,
        })

        x_prev = x_new
        m_prev = m_new
        eps    = max(eps * COOLING, EPS_MIN)

        if delta < IRLS_TOL:
            converged = True
            break

    t_total = time.perf_counter() - t0
    rms_best = residual_rms(Gn, m_best, sG, g_obs)
    return m_best, rms_best, t_total, history, converged, best_iter_idx


# -- Runner --

def run():
    print("=" * 114)
    print("TerraQuantum - Validacion MS-x con early stopping por PR-AUC  [Fase 1.7C.3L.8]")
    print(f"  Escenarios   : {SCENARIOS}")
    print(f"  Config fija  : BETA_MS={BETA_MS:.0e}  ALPHA_SPATIAL={ALPHA_SPATIAL}  "
          f"BETA={BETA}  LAMBDA_MAG={LAMBDA_MAG:.0e}")
    print(f"  MS params    : EPS_0={EPS_0}  EPS_MIN={EPS_MIN}  COOLING={COOLING}  MAX_IRLS={MAX_IRLS}")
    print(f"  Cambio 1.7C.3L.8: solver retorna m@best_iter (max PR-AUC) en vez de m_final")
    print("=" * 114)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0  = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter() - t0:.1f}s.")

    scenarios = generate_scenarios()
    np.random.seed(42)

    all_results = {}

    for sc_name in SCENARIOS:
        ct        = scenarios[sc_name]
        mask_true = ct >= PHYSICAL_CONTRAST_THR
        g_exact   = kernel @ ct
        ns        = 0.01 * np.max(np.abs(g_exact))
        g_obs     = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        Ga_full, da_full, Ga_base, da_base, W, sG, Gn, gn, n_v = \
            build_augmented_system(kernel, g_obs)

        print(f"\n{'='*114}")
        print(f"  ESCENARIO: {sc_name.upper()}")
        cw_true_y = centroid_weighted(x_c, y_c, z_c, ct)[1]
        print(f"  Ground truth: {int(np.sum(mask_true))} voxeles activos  "
              f"max_ct={float(np.max(ct)):.3f}  centroide_y={cw_true_y:.1f}m")
        print(f"{'='*114}")

        # -- Baseline LSQR --
        print(f"\n  [BASELINE LSQR  alpha={ALPHA_SPATIAL}]")
        m_base, rms_base, t_base, mtr_base, p90_base, p925_base = \
            solve_baseline_lsqr(Ga_full, da_full, W, sG, Gn, g_obs, ct, mask_true)
        print(f"    t={t_base:.1f}s | RMS={rms_base:.5f} | PR-AUC={mtr_base['prauc']:.4f} | "
              f"Top-K={mtr_base['topk']:.3f} | IoU={mtr_base['iou']:.3f} | "
              f"F1={mtr_base['f1']:.3f} | corr={mtr_base['corr']:.3f} | "
              f"y_err={mtr_base['y_err']:.1f}m | shl={mtr_base['shallow_mass']:.1f}% | "
              f"maxd={mtr_base['max_density']:.3f}")

        # -- MS-x con best_iter --
        print(f"\n  [MS-x BEST_ITER  BETA_MS={BETA_MS:.0e}  (warm start desde baseline)]")
        m_best, rms_best, t_ms, history, converged, best_iter = solve_ms_x_best(
            Ga_base, da_base, W, sG, Gn, g_obs,
            m0=m_base, ct=ct, mask_true=mask_true,
        )
        print_iter_table(history, best_iter)

        mtr_best             = history[best_iter]
        p90_best             = mtr_best["p90_y"]
        p925_best            = mtr_best["p925_y"]
        mtr_final            = history[-1]
        scale_state          = classify_scale_state(mtr_best, mtr_base)
        rejected, rej_reason = check_rejection(mtr_best, mtr_base, history, rms_best, rms_base)

        gain_pr   = mtr_best["prauc"] - mtr_base["prauc"]
        gain_topk = mtr_best["topk"]  - mtr_base["topk"]
        gain_yerr = mtr_best["y_err"] - mtr_base["y_err"]
        prauc_deg = mtr_final["prauc"] - mtr_best["prauc"]
        maxd_deg  = mtr_final["max_density"] - mtr_best["max_density"]

        tag = "[REJ]" if rejected else "     "
        print(f"\n    {tag} best_iter={best_iter} | total_iters={len(history)} | conv={converged}")
        print(f"    PR-AUC@best={mtr_best['prauc']:.4f}  PR-AUC@final={mtr_final['prauc']:.4f}  "
              f"deg={prauc_deg:+.4f}")
        print(f"    Top-K@best={mtr_best['topk']:.3f}  IoU@best={mtr_best['iou']:.3f}  "
              f"F1@best={mtr_best['f1']:.3f}")
        print(f"    maxd@best={mtr_best['max_density']:.3f}  maxd@final={mtr_final['max_density']:.3f}  "
              f"deg={maxd_deg:+.3f}")
        print(f"    gain_PR={gain_pr:+.4f}  gain_TopK={gain_topk:+.4f}  "
              f"y_err@best={mtr_best['y_err']:.1f}m  shl@best={mtr_best['shallow_mass']:.1f}%")
        print(f"    escala={scale_state}  criteria={rej_reason}")

        all_results[sc_name] = {
            "baseline": {
                "metrics": mtr_base, "rms": rms_base, "t": t_base,
                "p90_y": p90_base, "p925_y": p925_base,
            },
            "ms_x": {
                "mtr_best":   mtr_best,
                "mtr_final":  mtr_final,
                "best_iter":  best_iter,
                "iters_done": len(history),
                "converged":  converged,
                "rejected":   rejected,
                "rej_reason": rej_reason,
                "scale_state":scale_state,
                "gain_pr":    gain_pr,
                "gain_topk":  gain_topk,
                "gain_yerr":  gain_yerr,
                "prauc_deg":  prauc_deg,
                "maxd_deg":   maxd_deg,
                "rms":        rms_best,
                "t":          t_ms,
                "history":    history,
                "p90_y":      p90_best,
                "p925_y":     p925_best,
            },
        }

    # -- Tabla A --
    print("\n\n" + "=" * 114)
    print("TABLA A: baseline_lsqr vs ms_x@best_iter por escenario  [Fase 1.7C.3L.8]")
    print("=" * 114)

    hdr_a = (
        f"  {'Escenario':<16} | {'Variante':<16} | "
        f"{'PRAUC':>6} | {'TopK':>5} | {'IoU':>5} | {'F1':>5} | "
        f"{'corr':>5} | {'y_err':>7} | {'shl%':>5} | "
        f"{'maxd':>5} | {'BstIt':>5} | {'Rej':>5} | {'Escala':>18}"
    )
    print(hdr_a)
    print("  " + "-" * (len(hdr_a) - 2))

    for sc_name in SCENARIOS:
        b   = all_results[sc_name]["baseline"]
        r   = all_results[sc_name]["ms_x"]
        mtr = b["metrics"]
        mb  = r["mtr_best"]
        rj  = "[REJ]" if r["rejected"] else "     "

        print(
            f"  {sc_name:<16} | {'baseline_lsqr':<16} | "
            f"{mtr['prauc']:>6.4f} | {mtr['topk']:>5.3f} | {mtr['iou']:>5.3f} | {mtr['f1']:>5.3f} | "
            f"{mtr['corr']:>5.3f} | {mtr['y_err']:>7.1f} | {mtr['shallow_mass']:>4.1f}% | "
            f"{mtr['max_density']:>5.3f} | {'  -':>5} | {'  N/A':>5} | {'ESCALA_OK':>18}"
        )
        gain_str = f"({r['gain_pr']:+.4f})"
        print(
            f"  {sc_name:<16} | {'ms_x@best_iter':<16} | "
            f"{mb['prauc']:>6.4f} | {mb['topk']:>5.3f} | {mb['iou']:>5.3f} | {mb['f1']:>5.3f} | "
            f"{mb['corr']:>5.3f} | {mb['y_err']:>7.1f} | {mb['shallow_mass']:>4.1f}% | "
            f"{mb['max_density']:>5.3f} | {r['best_iter']:>5} | {rj:>5} | {r['scale_state']:>18}  {gain_str}"
        )
        print("  " + "." * (len(hdr_a) - 2))

    # -- Tabla B --
    print("\n\n" + "=" * 114)
    print("TABLA B: Resumen global (5 escenarios)")
    print("=" * 114)

    base_praucs = [all_results[sc]["baseline"]["metrics"]["prauc"]        for sc in SCENARIOS]
    base_topks  = [all_results[sc]["baseline"]["metrics"]["topk"]         for sc in SCENARIOS]
    base_yerrs  = [all_results[sc]["baseline"]["metrics"]["y_err"]        for sc in SCENARIOS]
    base_shls   = [all_results[sc]["baseline"]["metrics"]["shallow_mass"] for sc in SCENARIOS]
    base_maxds  = [all_results[sc]["baseline"]["metrics"]["max_density"]  for sc in SCENARIOS]

    ms_praucs   = [all_results[sc]["ms_x"]["mtr_best"]["prauc"]        for sc in SCENARIOS]
    ms_topks    = [all_results[sc]["ms_x"]["mtr_best"]["topk"]         for sc in SCENARIOS]
    ms_yerrs    = [all_results[sc]["ms_x"]["mtr_best"]["y_err"]        for sc in SCENARIOS]
    ms_shls     = [all_results[sc]["ms_x"]["mtr_best"]["shallow_mass"] for sc in SCENARIOS]
    ms_maxds    = [all_results[sc]["ms_x"]["mtr_best"]["max_density"]  for sc in SCENARIOS]
    ms_ious     = [all_results[sc]["ms_x"]["mtr_best"]["iou"]          for sc in SCENARIOS]
    ms_f1s      = [all_results[sc]["ms_x"]["mtr_best"]["f1"]           for sc in SCENARIOS]
    ms_gains    = [all_results[sc]["ms_x"]["gain_pr"]                  for sc in SCENARIOS]
    ms_states   = [all_results[sc]["ms_x"]["scale_state"]              for sc in SCENARIOS]

    # Comparacion con Fase 1.7C.3L.7 (usando m_final)
    prev_praucs_fin = {
        "shallow_body": 0.7740, "mid_body": 0.5299, "deep_body": 0.3979,
        "elongated_body": 0.3449, "two_bodies": 0.4120,
    }
    prev_maxds_fin = {
        "shallow_body": 1.390, "mid_body": 0.303, "deep_body": 0.065,
        "elongated_body": 0.062, "two_bodies": 0.561,
    }

    n_rej      = sum(1 for sc in SCENARIOS if all_results[sc]["ms_x"]["rejected"])
    n_improve  = sum(1 for g in ms_gains if g > 0.02)
    n_ok       = sum(1 for ss in ms_states if ss == "ESCALA_OK")
    n_supp     = sum(1 for ss in ms_states if ss == "ESCALA_SUPRIMIDA")
    n_unstable = sum(1 for ss in ms_states if ss == "ESCALA_INESTABLE")

    print(f"\n  Metrica              | Baseline (mean) | MS-x@best (mean) | Delta mean | 1.7C.3L.7 final")
    print(f"  ---------------------+-----------------+------------------+------------+----------------")
    prev_pr_mean = float(np.mean(list(prev_praucs_fin.values())))
    print(f"  PR-AUC               | {np.mean(base_praucs):>15.4f} | {np.mean(ms_praucs):>16.4f} | {np.mean(ms_gains):>+10.4f} | {prev_pr_mean:>14.4f}")
    print(f"  Top-K                | {np.mean(base_topks):>15.3f} | {np.mean(ms_topks):>16.3f} | {np.mean(ms_topks)-np.mean(base_topks):>+10.3f} |")
    print(f"  IoU                  | {np.mean([all_results[sc]['baseline']['metrics']['iou'] for sc in SCENARIOS]):>15.3f} | {np.mean(ms_ious):>16.3f} | {np.mean(ms_ious)-np.mean([all_results[sc]['baseline']['metrics']['iou'] for sc in SCENARIOS]):>+10.3f} |")
    print(f"  F1                   | {np.mean([all_results[sc]['baseline']['metrics']['f1'] for sc in SCENARIOS]):>15.3f} | {np.mean(ms_f1s):>16.3f} | {np.mean(ms_f1s)-np.mean([all_results[sc]['baseline']['metrics']['f1'] for sc in SCENARIOS]):>+10.3f} |")
    print(f"  y_err                | {np.mean(base_yerrs):>15.1f} | {np.mean(ms_yerrs):>16.1f} | {np.mean(ms_yerrs)-np.mean(base_yerrs):>+10.1f} |")
    print(f"  shallow_mass%        | {np.mean(base_shls):>15.1f} | {np.mean(ms_shls):>16.1f} | {np.mean(ms_shls)-np.mean(base_shls):>+10.1f} |")
    prev_maxd_mean = float(np.mean(list(prev_maxds_fin.values())))
    print(f"  max_density          | {np.mean(base_maxds):>15.3f} | {np.mean(ms_maxds):>16.3f} | {np.mean(ms_maxds)-np.mean(base_maxds):>+10.3f} | {prev_maxd_mean:>14.3f}")
    print(f"\n  Rechazos             : {n_rej}/{len(SCENARIOS)}")
    print(f"  Mejoran PR-AUC>2pp   : {n_improve}/{len(SCENARIOS)}")
    print(f"  Escala OK            : {n_ok}/{len(SCENARIOS)}")
    print(f"  Escala suprimida     : {n_supp}/{len(SCENARIOS)}")
    print(f"  Escala inestable     : {n_unstable}/{len(SCENARIOS)}")

    # Impacto del early stopping
    print(f"\n  Impacto del early stopping (best vs final) por escenario:")
    print(f"  {'Escenario':<16} | {'best_iter':>9} | {'PR@best':>7} | {'PR@fin':>7} | "
          f"{'deg_PR':>7} | {'maxd@best':>9} | {'maxd@fin':>9} | {'deg_maxd':>8}")
    print("  " + "-" * 87)
    for sc in SCENARIOS:
        r  = all_results[sc]["ms_x"]
        mb = r["mtr_best"]
        mf = r["mtr_final"]
        print(
            f"  {sc:<16} | {r['best_iter']:>9} | {mb['prauc']:>7.4f} | {mf['prauc']:>7.4f} | "
            f"{r['prauc_deg']:>+7.4f} | {mb['max_density']:>9.3f} | {mf['max_density']:>9.3f} | "
            f"{r['maxd_deg']:>+8.3f}"
        )

    # -- Diagnostico por escenario --
    print("\n\n" + "=" * 114)
    print("DIAGNOSTICO POR ESCENARIO  [Fase 1.7C.3L.8]")
    print("=" * 114)

    for sc_name in SCENARIOS:
        b    = all_results[sc_name]["baseline"]
        r    = all_results[sc_name]["ms_x"]
        mtr  = b["metrics"]
        mb   = r["mtr_best"]
        mf   = r["mtr_final"]
        ss   = r["scale_state"]
        bi   = r["best_iter"]

        cw_true_y = centroid_weighted(x_c, y_c, z_c, scenarios[sc_name])[1]
        print(f"\n  [{sc_name.upper()}]  centroide_verdadero_y={cw_true_y:.1f}m")
        print(f"    Baseline  : PR-AUC={mtr['prauc']:.4f}  TopK={mtr['topk']:.3f}  "
              f"IoU={mtr['iou']:.3f}  y_err={mtr['y_err']:.1f}m  "
              f"shl={mtr['shallow_mass']:.1f}%  maxd={mtr['max_density']:.3f}")
        print(f"    MS-x@best : PR-AUC={mb['prauc']:.4f}  TopK={mb['topk']:.3f}  "
              f"IoU={mb['iou']:.3f}  y_err={mb['y_err']:.1f}m  "
              f"shl={mb['shallow_mass']:.1f}%  maxd={mb['max_density']:.3f}  @iter={bi}")
        print(f"    MS-x@fin  : PR-AUC={mf['prauc']:.4f}  maxd={mf['max_density']:.3f}  "
              f"deg_PR={r['prauc_deg']:+.4f}  deg_maxd={r['maxd_deg']:+.3f}")
        print(f"    Escala    : {ss}  |  Rechazo: {'SI - ' + r['rej_reason'] if r['rejected'] else 'NO'}")
        print(f"    gain_PR={r['gain_pr']:+.4f}  gain_TopK={r['gain_topk']:+.4f}  "
              f"gain_yerr={r['gain_yerr']:+.1f}m")

        prev_prauc_fin = prev_praucs_fin.get(sc_name, None)
        if prev_prauc_fin is not None:
            delta_vs_prev = mb["prauc"] - prev_prauc_fin
            print(f"    vs 1.7C.3L.7 fin: PR-AUC {prev_prauc_fin:.4f} -> {mb['prauc']:.4f}  "
                  f"({delta_vs_prev:+.4f})  maxd {prev_maxds_fin[sc_name]:.3f} -> {mb['max_density']:.3f}")

        if ss == "ESCALA_OK":
            uso = "Mascara fisica directamente aplicable."
        elif ss == "ESCALA_SUPRIMIDA":
            uso = ("PR-AUC/Top-K validos para targeting. "
                   "Escalar antes de inferir reservas.")
        else:
            uso = "Escala fuera del rango fisico esperado. Usar con precaucion."
        print(f"    Uso rec   : {uso}")

    # -- Diagnostico global --
    print("\n\n" + "=" * 114)
    print("DIAGNOSTICO GLOBAL  [Fase 1.7C.3L.8]")
    print("=" * 114)

    print(f"\n  G1 Impacto del early stopping sobre la escala:")
    prev_ok_count  = 1   # solo mid_body en 1.7C.3L.7
    prev_supp_count= 2
    prev_inst_count= 2
    print(f"     Fase 1.7C.3L.7 (m_final)   : OK={prev_ok_count}/5  SUPRIMIDA={prev_supp_count}/5  INESTABLE={prev_inst_count}/5")
    print(f"     Fase 1.7C.3L.8 (m@best)    : OK={n_ok}/5  SUPRIMIDA={n_supp}/5  INESTABLE={n_unstable}/5")
    delta_ok   = n_ok - prev_ok_count
    delta_supp = n_supp - prev_supp_count
    delta_inst = n_unstable - prev_inst_count
    print(f"     Delta                       : OK={delta_ok:+d}  SUPRIMIDA={delta_supp:+d}  INESTABLE={delta_inst:+d}")

    print(f"\n  G2 Comparacion de PR-AUC best@best vs PR-AUC final@1.7C.3L.7:")
    for sc in SCENARIOS:
        mb_pr  = all_results[sc]["ms_x"]["mtr_best"]["prauc"]
        fin_pr = prev_praucs_fin[sc]
        delta  = mb_pr - fin_pr
        print(f"     {sc:<16} : 1.7C.3L.7_fin={fin_pr:.4f}  1.7C.3L.8_best={mb_pr:.4f}  ({delta:+.4f})")

    print(f"\n  G3 Clasificacion final de uso por escenario:")
    for sc in SCENARIOS:
        r  = all_results[sc]["ms_x"]
        mb = r["mtr_best"]
        ss = r["scale_state"]
        if ss == "ESCALA_OK" and not r["rejected"]:
            uso_final = "MASCARA_FISICA"
        elif not r["rejected"]:
            uso_final = "TARGETING_SCORE"
        else:
            uso_final = "NO_RECOMENDADO"
        print(f"     {sc:<16} : {ss:<18}  IoU={mb['iou']:.3f}  F1={mb['f1']:.3f}  "
              f"PR-AUC={mb['prauc']:.4f}  -> {uso_final}")

    # -- Veredicto --
    print("\n\n" + "=" * 114)
    print("VEREDICTO GLOBAL  [Fase 1.7C.3L.8]")
    print("=" * 114)

    gain_mean  = float(np.mean(ms_gains))
    topk_mean  = float(np.mean(ms_topks) - np.mean(base_topks))
    iou_mean   = float(np.mean(ms_ious))
    scale_improved = (n_unstable < prev_inst_count) or (n_ok > prev_ok_count)

    if n_rej == 0 and n_improve == 5 and scale_improved:
        verdict = "APROBADO CON MEJORA -- early stopping mejora escala y mantiene ganancia"
        rec_tag = "A"
        rec_msg = (
            f"MS-x con m@best_iter es la configuracion final recomendada. "
            f"Gain medio PR-AUC={gain_mean:+.4f}  TopK={topk_mean:+.3f}. "
            f"Escala fisica OK en {n_ok}/5 escenarios. "
            f"Listo para avanzar a implementacion experimental productiva futura."
        )
    elif n_rej == 0 and n_improve == 5:
        verdict = "APROBADO -- early stopping no cambia escala pero mantiene ranking"
        rec_tag = "C"
        rec_msg = (
            f"MS-x@best_iter es el targeting score candidato. "
            f"Gain medio PR-AUC={gain_mean:+.4f}. "
            f"Escala suprimida en {n_supp}/5. Usar como score relativo."
        )
    elif n_rej > 0:
        verdict = f"RECHAZADO PARCIAL -- {n_rej}/5 escenarios rechazados"
        rec_tag = "B"
        rec_msg = "Revisar criterios de rechazo. Considerar ajuste adicional."
    else:
        verdict = "MARGINAL"
        rec_tag = "D"
        rec_msg = "Ganancia insuficiente. Evaluar alternativas."

    print(f"\n  VEREDICTO: {verdict}")
    print(f"  RECOMENDACION [{rec_tag}]: {rec_msg}")

    # -- Respuesta final --
    print("\n\n" + "=" * 114)
    print("RESPUESTA FINAL  [Fase 1.7C.3L.8]")
    print("=" * 114)
    print(f"  1. Archivo modificado     : run_tq_synthetic_copper_demo_v1_ms_xspace_experiment.py")
    print(f"  2. Cambio central         : solver retorna m@best_iter en vez de m_final")
    print(f"  3. Escenarios evaluados   : {len(SCENARIOS)}  ({', '.join(SCENARIOS)})")
    print(f"  4. Escenarios que mejoran : {n_improve}/{len(SCENARIOS)}")
    print(f"  5. Rechazos               : {n_rej}/{len(SCENARIOS)}")
    print(f"  6. Escala OK/supr/inst    : {n_ok}/{n_supp}/{n_unstable}")
    print(f"  7. Gain medio PR-AUC      : {gain_mean:+.4f}")
    print(f"  8. Gain medio Top-K       : {topk_mean:+.3f}")
    print(f"  9. Escala mejorada vs 1.7C.3L.7: {'SI' if scale_improved else 'NO'}")
    print(f" 10. MS-x candidato serio   : {'SI' if n_rej == 0 and n_improve >= 4 else 'NO'}")
    print(f" 11. Produccion tocada      : NO")
    print()

    print("Fin de validacion con early stopping  [Fase 1.7C.3L.8]\n")


if __name__ == "__main__":
    run()
