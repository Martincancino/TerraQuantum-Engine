"""
TerraQuantum — Análisis de Umbrales Adaptativos por Arquitectura

Desagrega la evaluación de umbrales adaptativos para analizar el rendimiento
sobre arquitecturas individuales fuertes (highest_score, etc.).
Evalúa además la viabilidad de una salida de máscara dual:
- Candidate Core (ej. P90)
- Candidate Envelope (ej. P85)

Mantiene la separación estricta entre la physical_absolute_mask (fixed_0_15)
y las máscaras candidatas relativas.
No modifica servicios productivos ni usa datos reales.
"""
import math, os, sys, time
from typing import Dict, Tuple
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    NX, NY, NZ, BLOCK_SIZE, BASE_DENSITY
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

ARCHITECTURES = [
    ("baseline_unweighted",      0.00, 1.00),
    ("low_weight_guardrail",     0.50, 0.50),
    ("depth_anchor",             0.75, 1.00),
    ("balanced_corr_depth",      0.75, 2.00),
    ("max_iou_candidate",        1.00, 0.25),
    ("alt_top_score",            1.00, 0.50),
    ("highest_score",            1.00, 2.00),
]

STRONG_ARCHITECTURES = [
    "highest_score", "balanced_corr_depth", "depth_anchor", "alt_top_score"
]

STRATEGIES = [
    "fixed_0_15", "fixed_0_10", "fixed_0_075", "fixed_0_05",
    "relative_peak_20pct", "relative_peak_25pct", "relative_peak_30pct", "relative_peak_40pct",
    "percentile_85", "percentile_90", "percentile_92_5", "percentile_95",
    "otsu_positive_contrast",
    "oracle_best_f1_threshold", "oracle_best_iou_threshold"
]

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

def solve_exp(kernel, g_obs, beta, alpha_spatial):
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
    Ga = sp.vstack([Gt, ls * Wst], format="csr")
    da = np.concatenate([gn, np.zeros(n_v)])
    r = lsqr(Ga, da, damp=LAMBDA_MAG, iter_lim=250, show=False)
    m = r[0] * W
    return m

def sweep_thresholds(contrast_rec, mask_true, n_steps=200):
    mn = float(np.min(contrast_rec)); mx = float(np.max(contrast_rec))
    if mx <= mn: return 0.0, 0.0, mn, mn
    thresholds = np.linspace(mn, mx, n_steps)
    bf1 = 0.0; biou = 0.0; tf1 = mn; tiou = mn
    n_true = int(np.sum(mask_true))
    for t in thresholds:
        pred = contrast_rec >= t
        tp = int(np.sum(pred & mask_true))
        fp = int(np.sum(pred & ~mask_true))
        prec = tp / max(tp + fp, 1)
        rec = tp / max(n_true, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-15)
        iou = tp / max(tp + fp + (n_true - tp), 1)
        if f1 > bf1: bf1 = f1; tf1 = float(t)
        if iou > biou: biou = iou; tiou = float(t)
    return bf1, biou, tf1, tiou

def get_otsu_threshold(vals):
    pvals = vals[vals > 0]
    if len(pvals) == 0: return 0.0
    hist, bin_edges = np.histogram(pvals, bins=256)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    total = len(pvals); sum_total = np.sum(bin_centers * hist)
    sumB, wB, varMax, threshold = 0.0, 0.0, 0.0, 0.0
    for t in range(256):
        wB += hist[t]; wF = total - wB
        if wB == 0: continue
        if wF == 0: break
        sumB += bin_centers[t] * hist[t]
        mB = sumB / wB; mF = (sum_total - sumB) / wF
        varBetween = wB * wF * (mB - mF) ** 2
        if varBetween > varMax:
            varMax = varBetween; threshold = bin_centers[t]
    return threshold

def apply_strategy(strat_name, cr, mask_true):
    c_max = float(np.max(cr))
    if strat_name == "fixed_0_15": t = 0.15
    elif strat_name == "fixed_0_10": t = 0.10
    elif strat_name == "fixed_0_075": t = 0.075
    elif strat_name == "fixed_0_05": t = 0.05
    elif strat_name == "relative_peak_20pct": t = c_max * 0.20
    elif strat_name == "relative_peak_25pct": t = c_max * 0.25
    elif strat_name == "relative_peak_30pct": t = c_max * 0.30
    elif strat_name == "relative_peak_40pct": t = c_max * 0.40
    elif strat_name.startswith("percentile_"):
        pct = float(strat_name[11:].replace("_", "."))
        t = float(np.percentile(cr, pct))
    elif strat_name == "otsu_positive_contrast":
        t = get_otsu_threshold(cr)
    elif strat_name == "oracle_best_f1_threshold":
        _, _, t, _ = sweep_thresholds(cr, mask_true)
    elif strat_name == "oracle_best_iou_threshold":
        _, _, _, t = sweep_thresholds(cr, mask_true)
    else:
        raise ValueError(f"Unknown {strat_name}")
    return t, cr >= t

def compute_metrics(mask_pred, mask_true):
    tp = int(np.sum(mask_pred & mask_true))
    fp = int(np.sum(mask_pred & ~mask_true))
    n_true = int(np.sum(mask_true))
    fn = n_true - tp
    prec = tp / max(tp + fp, 1)
    rec = tp / max(n_true, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-15)
    iou = tp / max(tp + fp + fn, 1)
    return iou, f1, prec, rec, int(np.sum(mask_pred))

def run():
    print("=" * 130)
    print("TerraQuantum — Análisis de Umbrales Adaptativos por Arquitectura")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s.")

    scenarios = generate_scenarios()
    np.random.seed(42)

    db = {a: {s: [] for s in STRATEGIES} for a, _, _ in ARCHITECTURES}
    dual_mask_db = {a: [] for a in STRONG_ARCHITECTURES}

    print("\n[2] Evaluando estrategias sobre inversiones fuertes...")
    total = len(scenarios) * len(ARCHITECTURES)
    idx = 0
    for sc_name, ct in scenarios.items():
        mp = ct >= PHYSICAL_CONTRAST_THR
        g_exact = kernel @ ct
        ns = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        for a_name, beta, alpha in ARCHITECTURES:
            idx += 1
            sys.stdout.write(f"\r    {idx}/{total} {sc_name} / {a_name}               ")
            sys.stdout.flush()

            cr = solve_exp(kernel, g_obs, beta, alpha)

            # Strategies
            for strat in STRATEGIES:
                t, mask_pred = apply_strategy(strat, cr, mp)
                iou, f1, prec, rec, n_sel = compute_metrics(mask_pred, mp)
                db[a_name][strat].append({
                    "sc": sc_name, "t": t, "iou": iou, "f1": f1,
                    "prec": prec, "rec": rec, "n_sel": n_sel
                })

            # Dual Mask (Core=P90, Envelope=P85) for strong architectures
            if a_name in STRONG_ARCHITECTURES:
                _, core_mask = apply_strategy("percentile_90", cr, mp)
                _, env_mask = apply_strategy("percentile_85", cr, mp)
                
                c_iou, c_f1, c_prec, c_rec, c_sel = compute_metrics(core_mask, mp)
                e_iou, e_f1, e_prec, e_rec, e_sel = compute_metrics(env_mask, mp)
                
                dual_mask_db[a_name].append({
                    "sc": sc_name,
                    "core_iou": c_iou, "core_f1": c_f1, "core_prec": c_prec, "core_rec": c_rec,
                    "env_iou": e_iou, "env_f1": e_f1, "env_prec": e_prec, "env_rec": e_rec,
                    "added_rec": e_rec - c_rec,
                    "lost_prec": c_prec - e_prec
                })

    print("\n\n[3] Rankings por Arquitecturas Fuertes:")
    for a_name in STRONG_ARCHITECTURES:
        print(f"\n  ── Arquitectura: {a_name} ──")
        summary = []
        for strat in STRATEGIES:
            vals = db[a_name][strat]
            iou_arr = [v["iou"] for v in vals]
            f1_arr = [v["f1"] for v in vals]
            prec_arr = [v["prec"] for v in vals]
            rec_arr = [v["rec"] for v in vals]
            t_arr = [v["t"] for v in vals]
            n_arr = [v["n_sel"] for v in vals]
            
            summary.append({
                "name": strat,
                "m_iou": np.mean(iou_arr), "m_f1": np.mean(f1_arr),
                "m_prec": np.mean(prec_arr), "m_rec": np.mean(rec_arr),
                "w_iou": np.min(iou_arr), "w_f1": np.min(f1_arr),
                "m_sel": np.mean(n_arr),
                "t_rng": np.max(t_arr) - np.min(t_arr),
                "n_rng": np.max(n_arr) - np.min(n_arr),
                "t_min": np.min(t_arr), "t_max": np.max(t_arr),
                "n_min": np.min(n_arr), "n_max": np.max(n_arr)
            })
            
        no_oracle = [s for s in summary if not s["name"].startswith("oracle")]
        ranked_iou = sorted(no_oracle, key=lambda x: x["m_iou"], reverse=True)
        
        print(f"  {'Estrategia':<24} | {'mIoU':>6} | {'mF1':>6} | {'mPrec':>6} | {'mRec':>6} | {'wIoU':>6} | {'wF1':>6} | {'mSelVxl':>8} | {'tRng':>7} | {'nRng':>7}")
        print("  " + "-" * 115)
        for s in ranked_iou[:6]:
            print(f"  {s['name']:<24} | {s['m_iou']:>6.4f} | {s['m_f1']:>6.4f} | {s['m_prec']:>6.4f} | {s['m_rec']:>6.4f} | "
                  f"{s['w_iou']:>6.4f} | {s['w_f1']:>6.4f} | {s['m_sel']:>8.0f} | {s['t_rng']:>7.4f} | {s['n_rng']:>7.0f}")

    print("\n" + "=" * 130)
    print("EVALUACIÓN DE MÁSCARA DUAL (Core=P90 + Envelope=P85)")
    print("-" * 130)
    print(f"{'Arquitectura':<22} | {'cIoU':>6} | {'eIoU':>6} | {'cF1':>6} | {'eF1':>6} | {'cPrec':>6} | {'ePrec':>6} | {'cRec':>6} | {'eRec':>6} | {'+Rec':>6} | {'-Prec':>6}")
    print("-" * 130)
    
    dual_summary = {}
    for a_name in STRONG_ARCHITECTURES:
        vals = dual_mask_db[a_name]
        ds = {k: np.mean([v[k] for v in vals]) for k in vals[0].keys() if k != "sc"}
        dual_summary[a_name] = ds
        print(f"{a_name:<22} | {ds['core_iou']:>6.4f} | {ds['env_iou']:>6.4f} | {ds['core_f1']:>6.4f} | {ds['env_f1']:>6.4f} | "
              f"{ds['core_prec']:>6.4f} | {ds['env_prec']:>6.4f} | {ds['core_rec']:>6.4f} | {ds['env_rec']:>6.4f} | "
              f"+{ds['added_rec']:>5.4f} | -{ds['lost_prec']:>5.4f}")

    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)

    # Specific analysis on highest_score
    hs_summ = []
    for strat in STRATEGIES:
        vals = db["highest_score"][strat]
        hs_summ.append({
            "name": strat,
            "m_iou": np.mean([v["iou"] for v in vals]),
            "w_iou": np.min([v["iou"] for v in vals]),
        })
    
    hs_no_oracle = [s for s in hs_summ if not s["name"].startswith("oracle")]
    hs_best_iou = max(hs_no_oracle, key=lambda x: x["m_iou"])
    hs_best_wiou = max(hs_no_oracle, key=lambda x: x["w_iou"])

    print(f"  • En 'highest_score':")
    if hs_best_iou["name"] == "percentile_90":
        print("    ✅ percentile_90 SIGUE SIENDO LA MEJOR máscara candidata central (Core) en promedio.")
    else:
        print(f"    ⚠  percentile_90 fue desplazada. La mejor ahora es '{hs_best_iou['name']}'.")

    if hs_best_wiou["name"] == "percentile_85":
        print("    ✅ percentile_85 OFRECE LA MEJOR ROBUSTEZ de peor caso (Envelope).")
    else:
        print(f"    ⚠  La mejor robustez de peor caso la da '{hs_best_wiou['name']}' (wIoU={hs_best_wiou['w_iou']:.4f}).")

    hs_fixed05 = next((s for s in hs_no_oracle if s["name"] == "fixed_0_05"), None)
    hs_otsu = next((s for s in hs_no_oracle if s["name"] == "otsu_positive_contrast"), None)
    
    print("\n  • Competidores en 'highest_score':")
    if hs_fixed05 and hs_fixed05["m_iou"] > hs_best_iou["m_iou"] * 0.9:
        print(f"    ⚠  fixed_0_05 compite muy de cerca con {hs_best_iou['name']}.")
    else:
        print(f"    ✅ fixed_0_05 queda lejos de competir (mIoU={hs_fixed05['m_iou']:.4f}).")
        
    if hs_otsu and hs_otsu["m_iou"] > hs_best_iou["m_iou"] * 0.9:
        print(f"    ⚠  Otsu compite muy de cerca con {hs_best_iou['name']}.")
    else:
        print(f"    ✅ Otsu queda lejos de competir (mIoU={hs_otsu['m_iou']:.4f}).")

    # Percentile stability clarification
    print("\n  • Estabilidad numérica vs. Estabilidad volumétrica:")
    print("    Los percentiles muestran fluctuación numérica (tRng > 0), pero su volumen de selección")
    print("    es matemáticamente estable (nRng = 0), a diferencia de fixed o relative_peak.")

    # Dual Mask Analysis
    print("\n  • Análisis Máscara Dual (P90 + P85):")
    ds_hs = dual_summary["highest_score"]
    print(f"    La envolvente (P85) añade un {ds_hs['added_rec'] * 100:.1f}% de recall a costa de perder {ds_hs['lost_prec'] * 100:.1f}% de precisión.")
    
    if ds_hs["added_rec"] > 0.10 and ds_hs["env_iou"] > 0.05:
        print("    ✅ La máscara dual es ALTAMENTE ÚTIL: P85 captura zonas de baja confianza que P90 pierde.")
        dual_recommended = True
    else:
        print("    ⚠  La máscara dual aporta poco valor agregado. P90 captura casi todo lo útil.")
        dual_recommended = False

    print("\nRECOMENDACIÓN TÉCNICA:")
    if dual_recommended:
        print("  -> Se recomienda implementar salida de MÁSCARA DUAL para targeting:")
        print("     - Candidate Core: percentile_90 (Alta confianza, forma principal)")
        print("     - Candidate Envelope: percentile_85 (Baja confianza, halo de extensión máxima)")
    else:
        print("  -> Se recomienda implementar una única máscara: percentile_90.")
    print("  -> Mantener physical_absolute_mask (fixed_0_15) intacta e independiente.")
    print("  -> Dejar claro en el frontend que Core/Envelope NO SON MINERAL CONFIRMADO, sino")
    print("     probabilidades relativas de anomalía geofísica.")

    print("\nFin de la evaluación de umbrales adaptativos por arquitectura.\n")

if __name__ == "__main__":
    run()
