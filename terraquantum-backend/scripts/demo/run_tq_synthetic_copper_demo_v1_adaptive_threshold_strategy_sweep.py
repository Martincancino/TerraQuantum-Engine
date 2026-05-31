"""
TerraQuantum — Evaluación de Estrategias de Umbral Adaptativo

Evalúa estrategias heurísticas y estadísticas para calcular un umbral
de "adaptive candidate mask" sin conocer el ground truth.
Permite separar la máscara física absoluta de una máscara de targeting relativa.

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
    print("TerraQuantum — Evaluación de Estrategias de Umbral Adaptativo")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s.")

    scenarios = generate_scenarios()
    np.random.seed(42)

    db = {s: [] for s in STRATEGIES}

    print("\n[2] Evaluando estrategias sobre inversiones...")
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

            for strat in STRATEGIES:
                t, mask_pred = apply_strategy(strat, cr, mp)
                iou, f1, prec, rec, n_sel = compute_metrics(mask_pred, mp)
                db[strat].append({
                    "sc": sc_name, "arch": a_name,
                    "t": t, "iou": iou, "f1": f1, "prec": prec, "rec": rec, "n_sel": n_sel
                })

    print("\n\n[3] Calculando resúmenes por estrategia...")
    summary = []
    for strat in STRATEGIES:
        vals = db[strat]
        iou_arr = [v["iou"] for v in vals]
        f1_arr = [v["f1"] for v in vals]
        prec_arr = [v["prec"] for v in vals]
        rec_arr = [v["rec"] for v in vals]
        t_arr = [v["t"] for v in vals]
        n_arr = [v["n_sel"] for v in vals]
        
        summary.append({
            "name": strat,
            "m_iou": np.mean(iou_arr),
            "m_f1": np.mean(f1_arr),
            "m_prec": np.mean(prec_arr),
            "m_rec": np.mean(rec_arr),
            "w_iou": np.min(iou_arr),
            "w_f1": np.min(f1_arr),
            "m_sel": np.mean(n_arr),
            "t_min": np.min(t_arr),
            "t_max": np.max(t_arr),
            "bal": abs(np.mean(prec_arr) - np.mean(rec_arr))
        })

    print("\n" + "=" * 130)
    print("TABLA RESUMEN POR ESTRATEGIA (Media de 35 runs)")
    print("-" * 130)
    print(f"{'Estrategia':<26} | {'mIoU':>6} | {'mF1':>6} | {'mPrec':>6} | {'mRec':>6} | {'wIoU':>6} | {'wF1':>6} | {'mSelVxl':>8} | {'t_min':>7} | {'t_max':>7}")
    print("-" * 130)
    for s in summary:
        print(f"{s['name']:<26} | {s['m_iou']:>6.4f} | {s['m_f1']:>6.4f} | {s['m_prec']:>6.4f} | {s['m_rec']:>6.4f} | "
              f"{s['w_iou']:>6.4f} | {s['w_f1']:>6.4f} | {s['m_sel']:>8.0f} | {s['t_min']:>7.4f} | {s['t_max']:>7.4f}")

    print("\n" + "=" * 130)
    print("RANKINGS")
    print("-" * 130)
    for title, key, rev in [
        ("Mejores por Mean IoU", "m_iou", True),
        ("Mejores por Mean F1", "m_f1", True),
        ("Mejores por Worst-Case IoU", "w_iou", True),
        ("Mejor equilibrio Precision/Recall (|P-R| ~ 0)", "bal", False)
    ]:
        ranked = sorted(summary, key=lambda x: x[key], reverse=rev)
        print(f"\n  {title}:")
        for i, s in enumerate(ranked[:5]):
            val_str = f"{s[key]:.4f}"
            print(f"    {i+1}. {s['name']:<26} = {val_str}")

    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)
    
    no_oracle = [s for s in summary if not s["name"].startswith("oracle")]
    best_iou_strat = max(no_oracle, key=lambda x: x["m_iou"])
    best_f1_strat = max(no_oracle, key=lambda x: x["m_f1"])
    oracle_iou = next(s for s in summary if s["name"] == "oracle_best_iou_threshold")
    oracle_f1 = next(s for s in summary if s["name"] == "oracle_best_f1_threshold")

    iou_gap = oracle_iou["m_iou"] - best_iou_strat["m_iou"]
    f1_gap = oracle_f1["m_f1"] - best_f1_strat["m_f1"]

    print(f"  • Oracle F1: {oracle_f1['m_f1']:.4f}  |  Mejor Estrategia F1: '{best_f1_strat['name']}' ({best_f1_strat['m_f1']:.4f})")
    print(f"  • Oracle IoU: {oracle_iou['m_iou']:.4f} |  Mejor Estrategia IoU: '{best_iou_strat['name']}' ({best_iou_strat['m_iou']:.4f})")
    
    if iou_gap < 0.05 and f1_gap < 0.05:
        print(f"  ✅ '{best_f1_strat['name']}' y '{best_iou_strat['name']}' se acercan razonablemente al Oracle.")
    else:
        print(f"  ⚠  Ninguna estrategia adaptativa emula perfectamente al Oracle (Gap > 5%).")

    # Fixed vs Relative vs Percentile
    best_fixed = max([s for s in no_oracle if s["name"].startswith("fixed")], key=lambda x: x["m_iou"])
    best_rel = max([s for s in no_oracle if s["name"].startswith("relative")], key=lambda x: x["m_iou"])
    best_pct = max([s for s in no_oracle if s["name"].startswith("percentile")], key=lambda x: x["m_iou"])

    print(f"\n  • Mejor Fixed: {best_fixed['name']} (IoU={best_fixed['m_iou']:.4f})")
    print(f"  • Mejor Relative: {best_rel['name']} (IoU={best_rel['m_iou']:.4f})")
    print(f"  • Mejor Percentile: {best_pct['name']} (IoU={best_pct['m_iou']:.4f})")

    if best_rel["m_iou"] > best_fixed["m_iou"] * 1.1:
        print("  ✅ Los umbrales relativos/adaptativos superan ampliamente a los fijos.")
    else:
        print("  ⚠  Los umbrales relativos no mejoran sustancialmente los fijos en promedio.")

    pct_range = best_pct["t_max"] - best_pct["t_min"]
    rel_range = best_rel["t_max"] - best_rel["t_min"]
    if pct_range < rel_range * 0.8:
        print("  ✅ Los percentiles generan umbrales más estables y predecibles entre escenarios.")
    else:
        print("  ⚠  Los percentiles fluctúan tanto como los umbrales relativos.")

    print("\nRECOMENDACIÓN TÉCNICA:")
    if best_iou_strat["m_iou"] < 0.10:
        print("  -> Ninguna estrategia de umbral duro es suficientemente robusta (IoU < 0.10).")
        print("  -> Conviene mostrar el CAMPO CONTINUO + BANDA DE INCERTIDUMBRE (ej. Heatmap) en vez de una máscara discreta.")
    else:
        print(f"  -> La estrategia '{best_iou_strat['name']}' es la más sólida para la 'Adaptive Candidate Mask'.")
        print("  -> Mantener physical_absolute_mask (fixed_0_15) intacta.")
        print("  -> Exponer la Adaptive Mask en el frontend solo como herramienta visual relativa (targeting),")
        print("     nunca confundiéndola con volumen físico confirmado.")

    print("\nFin de la evaluación de estrategias de umbral adaptativo.\n")

if __name__ == "__main__":
    run()
