"""
TerraQuantum — Diagnóstico de Calibración de Umbrales y Ranking Espacial

Determina si la baja IoU de las arquitecturas candidatas se debe a:
1. Mala recuperación espacial real del solver, o
2. Mala calibración del umbral fijo actual de anomalía física.

Calcula ROC-AUC, PR-AUC, top-k overlap y umbrales óptimos por F1/IoU
para cada combinación arquitectura × escenario sintético.

No modifica servicios productivos ni usa datos reales.
"""
import math, os, sys, time
from typing import Dict
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, BACKEND_ROOT)

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    centroid_weighted, BASE_DENSITY, TOTAL_VOXELS, NX, NY, NZ, BLOCK_SIZE,
)

# Grilla
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
CURRENT_CONTRAST_THR = 0.15  # density >= 2.75 => contrast >= 0.15
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
    return m  # contrast only, postprocessing done externally


# ---------------------------------------------------------------------------
# Métricas de curva
# ---------------------------------------------------------------------------
def compute_roc_auc(scores, labels):
    """Trapezoidal ROC-AUC sin sklearn."""
    order = np.argsort(-scores)
    labels_s = labels[order]
    P = int(np.sum(labels)); N = len(labels) - P
    if P == 0 or N == 0:
        return 0.5
    tp = 0; fp = 0; auc = 0.0; tp_prev = 0; fp_prev = 0
    prev_score = scores[order[0]] + 1
    for i in range(len(labels_s)):
        if scores[order[i]] != prev_score:
            auc += 0.5 * (fp - fp_prev) * (tp + tp_prev)
            tp_prev = tp; fp_prev = fp; prev_score = scores[order[i]]
        if labels_s[i]:
            tp += 1
        else:
            fp += 1
    auc += 0.5 * (fp - fp_prev) * (tp + tp_prev)
    return auc / (P * N)

def compute_pr_auc(scores, labels):
    """Trapezoidal PR-AUC sin sklearn."""
    order = np.argsort(-scores)
    labels_s = labels[order]
    P = int(np.sum(labels))
    if P == 0:
        return 0.0
    tp = 0; precisions = []; recalls = []
    for i in range(len(labels_s)):
        if labels_s[i]:
            tp += 1
        p = tp / (i + 1); r = tp / P
        precisions.append(p); recalls.append(r)
    # Trapezoidal
    auc = 0.0
    for i in range(1, len(recalls)):
        auc += 0.5 * (recalls[i] - recalls[i-1]) * (precisions[i] + precisions[i-1])
    return auc

def sweep_thresholds(contrast_rec, mask_true, n_steps=200):
    """Barre umbrales y devuelve mejores F1, IoU y sus thresholds."""
    mn = float(np.min(contrast_rec)); mx = float(np.max(contrast_rec))
    if mx <= mn:
        return 0.0, 0.0, mn, mn
    thresholds = np.linspace(mn, mx, n_steps)
    best_f1 = 0.0; best_iou = 0.0; thr_f1 = mn; thr_iou = mn
    n_true = int(np.sum(mask_true))
    for t in thresholds:
        pred = contrast_rec >= t
        tp = int(np.sum(pred & mask_true))
        fp = int(np.sum(pred & ~mask_true))
        fn = n_true - tp
        prec = tp / max(tp + fp, 1)
        rec = tp / max(n_true, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-15)
        union = tp + fp + fn
        iou = tp / max(union, 1)
        if f1 > best_f1:
            best_f1 = f1; thr_f1 = float(t)
        if iou > best_iou:
            best_iou = iou; thr_iou = float(t)
    return best_f1, best_iou, thr_f1, thr_iou

def top_k_overlap(scores, labels, k):
    if k <= 0:
        return 0.0
    top_idx = set(np.argsort(-scores)[:k].tolist())
    true_idx = set(np.where(labels)[0].tolist())
    return len(top_idx & true_idx) / k


def run():
    print("=" * 130)
    print("TerraQuantum — Diagnóstico de Calibración de Umbrales y Ranking Espacial")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s. NNZ={kernel.nnz:,}")

    scenarios = generate_scenarios()
    np.random.seed(42)

    # db[arch][sc] = metrics dict
    db = {a[0]: {} for a in ARCHITECTURES}

    print("\n[2] Ejecutando inversiones y calculando curvas...")
    total = len(scenarios) * len(ARCHITECTURES)
    idx = 0
    for sc_name, ct in scenarios.items():
        mp = ct >= PHYSICAL_CONTRAST_THR
        k_phys = int(np.sum(mp))
        g_exact = kernel @ ct
        ns = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        for a_name, beta, alpha in ARCHITECTURES:
            idx += 1
            sys.stdout.write(f"\r    {idx}/{total} {sc_name} / {a_name}              ")
            sys.stdout.flush()

            cr = solve_exp(kernel, g_obs, beta, alpha)

            # Current threshold metrics
            pred_cur = cr >= CURRENT_CONTRAST_THR
            tp_c = int(np.sum(pred_cur & mp)); fp_c = int(np.sum(pred_cur & ~mp))
            fn_c = k_phys - tp_c
            prec_c = tp_c / max(tp_c + fp_c, 1)
            rec_c = tp_c / max(k_phys, 1)
            f1_c = 2*prec_c*rec_c / max(prec_c+rec_c, 1e-15)
            iou_c = tp_c / max(tp_c + fp_c + fn_c, 1)

            # Curve metrics
            roc = compute_roc_auc(cr, mp)
            pr = compute_pr_auc(cr, mp)
            topk = top_k_overlap(cr, mp, k_phys)
            bf1, biou, tf1, tiou = sweep_thresholds(cr, mp)

            db[a_name][sc_name] = {
                "roc_auc": roc, "pr_auc": pr, "topk": topk,
                "cur_f1": f1_c, "cur_iou": iou_c, "cur_prec": prec_c, "cur_rec": rec_c,
                "best_f1": bf1, "best_iou": biou, "thr_f1": tf1, "thr_iou": tiou,
            }

    # A. Tabla por escenario
    print("\n\n[3] Resultados por escenario:")
    for sc_name in scenarios:
        print(f"\n  ── {sc_name} ──")
        print(f"  {'Arquitectura':<22} | {'ROC':>6} | {'PR':>6} | {'TopK':>6} | {'cF1':>6} | {'cIoU':>6} | {'bF1':>6} | {'bIoU':>6} | {'tF1':>6} | {'tIoU':>6}")
        print("  " + "-" * 100)
        for a_name, _, _ in ARCHITECTURES:
            m = db[a_name][sc_name]
            print(f"  {a_name:<22} | {m['roc_auc']:>6.3f} | {m['pr_auc']:>6.3f} | {m['topk']:>6.3f} | "
                  f"{m['cur_f1']:>6.3f} | {m['cur_iou']:>6.3f} | {m['best_f1']:>6.3f} | {m['best_iou']:>6.3f} | "
                  f"{m['thr_f1']:>6.3f} | {m['thr_iou']:>6.3f}")

    # B. Tabla resumen por arquitectura
    print("\n" + "=" * 130)
    print("RESUMEN POR ARQUITECTURA (media de 5 escenarios)")
    print("-" * 130)
    summary = []
    for a_name, beta, alpha in ARCHITECTURES:
        vals = list(db[a_name].values())
        s = {
            "name": a_name, "beta": beta, "alpha": alpha,
            "m_roc": np.mean([v["roc_auc"] for v in vals]),
            "m_pr": np.mean([v["pr_auc"] for v in vals]),
            "m_topk": np.mean([v["topk"] for v in vals]),
            "m_cf1": np.mean([v["cur_f1"] for v in vals]),
            "m_ciou": np.mean([v["cur_iou"] for v in vals]),
            "m_bf1": np.mean([v["best_f1"] for v in vals]),
            "m_biou": np.mean([v["best_iou"] for v in vals]),
            "m_tf1": np.mean([v["thr_f1"] for v in vals]),
            "r_tf1": (min(v["thr_f1"] for v in vals), max(v["thr_f1"] for v in vals)),
            "m_tiou": np.mean([v["thr_iou"] for v in vals]),
            "r_tiou": (min(v["thr_iou"] for v in vals), max(v["thr_iou"] for v in vals)),
        }
        summary.append(s)

    print(f"{'Arquitectura':<22} | {'mROC':>6} | {'mPR':>6} | {'mTopK':>6} | {'mcF1':>6} | {'mcIoU':>6} | {'mbF1':>6} | {'mbIoU':>6} | {'mThrF1':>7} | {'mThrIoU':>7}")
    print("-" * 130)
    for s in summary:
        print(f"{s['name']:<22} | {s['m_roc']:>6.3f} | {s['m_pr']:>6.3f} | {s['m_topk']:>6.3f} | "
              f"{s['m_cf1']:>6.3f} | {s['m_ciou']:>6.3f} | {s['m_bf1']:>6.3f} | {s['m_biou']:>6.3f} | "
              f"{s['m_tf1']:>7.4f} | {s['m_tiou']:>7.4f}")

    # C. Rankings
    print("\n" + "=" * 130)
    print("RANKINGS POR MÉTRICA")
    print("-" * 130)
    for metric, key, rev in [("PR-AUC", "m_pr", True), ("Top-K Overlap", "m_topk", True),
                              ("Best IoU", "m_biou", True), ("Best F1", "m_bf1", True)]:
        ranked = sorted(summary, key=lambda x: x[key], reverse=rev)
        print(f"\n  {metric}:")
        for i, s in enumerate(ranked):
            print(f"    {i+1}. {s['name']:<22} = {s[key]:.4f}")

    # D. Diagnóstico
    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)

    # 1. ¿Mejora el IoU/F1 con umbral óptimo?
    avg_ciou = np.mean([s["m_ciou"] for s in summary])
    avg_biou = np.mean([s["m_biou"] for s in summary])
    avg_cf1 = np.mean([s["m_cf1"] for s in summary])
    avg_bf1 = np.mean([s["m_bf1"] for s in summary])
    iou_gain = avg_biou / max(avg_ciou, 1e-6)
    f1_gain = avg_bf1 / max(avg_cf1, 1e-6)

    if iou_gain > 2.0 or f1_gain > 2.0:
        print(f"  ✅ SEÑAL ÚTIL EXISTE pero MALA CALIBRACIÓN DE UMBRAL.")
        print(f"     IoU: actual={avg_ciou:.4f} -> óptimo={avg_biou:.4f} (mejora {iou_gain:.1f}x)")
        print(f"     F1:  actual={avg_cf1:.4f} -> óptimo={avg_bf1:.4f} (mejora {f1_gain:.1f}x)")
    elif iou_gain > 1.3:
        print(f"  ⚠  Hay margen de mejora moderado recalibrando el umbral.")
        print(f"     IoU: actual={avg_ciou:.4f} -> óptimo={avg_biou:.4f} ({iou_gain:.1f}x)")
    else:
        print(f"  ❌ El umbral actual ya captura la mayoría de la señal disponible.")
        print(f"     IoU: actual={avg_ciou:.4f} -> óptimo={avg_biou:.4f} ({iou_gain:.1f}x)")

    # 2. ¿PR-AUC y top-k son buenos o malos?
    avg_pr = np.mean([s["m_pr"] for s in summary])
    avg_topk = np.mean([s["m_topk"] for s in summary])
    if avg_pr < 0.15 and avg_topk < 0.15:
        print(f"  ❌ PR-AUC ({avg_pr:.3f}) y Top-K ({avg_topk:.3f}) siguen bajos.")
        print("     El problema PRINCIPAL sigue siendo la recuperación espacial del solver.")
    elif avg_pr > 0.30:
        print(f"  ✅ PR-AUC ({avg_pr:.3f}) indica buena discriminación espacial. El solver recupera señal útil.")
    else:
        print(f"  ⚠  PR-AUC ({avg_pr:.3f}) es moderado. La señal existe pero con ruido significativo.")

    # 3. ¿Es estable el umbral óptimo?
    all_thr_f1 = [v["thr_f1"] for a in db for v in db[a].values()]
    thr_range = max(all_thr_f1) - min(all_thr_f1)
    if thr_range > 0.10:
        print(f"  ⚠  El umbral óptimo por F1 varía entre {min(all_thr_f1):.4f} y {max(all_thr_f1):.4f} (rango={thr_range:.4f}).")
        print("     Un umbral físico global fijo NO es robusto para todos los escenarios/arquitecturas.")
    else:
        print(f"  ✅ El umbral óptimo por F1 es estable (rango={thr_range:.4f}).")

    # 4. ¿Correlación alta pero PR-AUC bajo?
    best_pr = max(summary, key=lambda x: x["m_pr"])
    for s in summary:
        if s["m_pr"] < best_pr["m_pr"] * 0.7:
            pass  # Solo alertar para la de mejor correlación que tiene bajo PR
    # Simplificar: buscar la arquitectura con mayor correlación implícita (ROC-AUC)
    best_roc = max(summary, key=lambda x: x["m_roc"])
    if best_roc["m_pr"] < 0.15:
        print(f"  ⚠  '{best_roc['name']}' tiene el mejor ROC-AUC ({best_roc['m_roc']:.3f}) pero PR-AUC bajo ({best_roc['m_pr']:.3f}).")
        print("     Correlación global no basta para targeting preciso.")

    # Recomendación
    print("\nRECOMENDACIÓN TÉCNICA:")
    if iou_gain > 2.0:
        print("  1. Recalibrar el umbral de anomalía física (contrast threshold) antes de rediseñar el solver.")
        print(f"     Umbral óptimo medio por F1: {np.mean([s['m_tf1'] for s in summary]):.4f}")
        print(f"     Umbral óptimo medio por IoU: {np.mean([s['m_tiou'] for s in summary]):.4f}")
        print("  2. Considerar umbral adaptativo por percentil en lugar de valor absoluto.")
    elif avg_pr < 0.15:
        print("  1. El problema principal es la recuperación espacial del solver, no el umbral.")
        print("  2. Considerar mejoras al forward model o a la regularización antes de recalibrar umbrales.")
    else:
        print("  1. Ambos factores contribuyen: la señal es parcial y el umbral no es óptimo.")
        print("  2. Recalibrar umbral dará mejora inmediata; mejorar solver dará mejora fundamental.")

    winner = max(summary, key=lambda x: x["m_biou"])
    print(f"\n  Arquitectura con mejor señal continua: '{winner['name']}' (mbIoU={winner['m_biou']:.4f}, mPR={winner['m_pr']:.3f})")

    print("\nFin del diagnóstico de calibración no productivo.\n")

if __name__ == "__main__":
    run()
