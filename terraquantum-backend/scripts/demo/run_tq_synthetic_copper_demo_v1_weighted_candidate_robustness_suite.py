"""
TerraQuantum — Validación Robusta de Arquitecturas Candidatas de Inversión Ponderada

Evalúa 7 arquitecturas (beta, alpha_spatial) sobre 5 escenarios sintéticos.
lambda_mag fijo en 0.00005 (impacto marginal confirmado por barrido previo).
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
from services.geophysics_service import estimate_grade_from_geophysics
from scripts.demo.benchmark_tq_synthetic_copper_demo_v1_recovery import (
    centroid_weighted, CUTOFF_DENSITY, CUTOFF_VISUAL_SCORE, BASE_DENSITY,
    TOTAL_VOXELS, NX, NY, NZ, BLOCK_SIZE,
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

PHYSICAL_CONTRAST_THRESHOLD = 0.15
LAMBDA_MAG = 0.00005

ARCHITECTURES = [
    ("baseline_unweighted",      0.00, 1.00),
    ("low_weight_guardrail",     0.50, 0.50),
    ("depth_anchor",             0.75, 1.00),
    ("balanced_corr_depth",      0.75, 2.00),
    ("max_iou_candidate",        1.00, 0.25),
    ("alt_top_score_candidate",  1.00, 0.50),
    ("highest_score_candidate",  1.00, 2.00),
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
    gm = kernel @ m; res = g_obs - gm
    res_l2 = float(np.linalg.norm(res))
    ve = np.abs(kernel.T @ res)
    mve = float(np.max(ve)) if len(ve) > 0 else 0.0
    prob = np.clip(1.0 - (ve / mve), 0, 1) if mve > 0 else np.ones(n_v)
    ed = np.clip(BASE_DENSITY + m, 2.6, 4.2)
    ds = np.clip((ed - 2.6) / 1.6, 0, 1)
    vs = prob * ds
    return ed, vs, prob, res_l2

def compute_metrics(ct, ed, vs, prob, res_l2):
    cr = ed - BASE_DENSITY
    cw_t = centroid_weighted(x_c, y_c, z_c, ct)
    gr = estimate_grade_from_geophysics(ed, prob, 83, 79, "norte_chile")
    mr = (ed >= CUTOFF_DENSITY) | (vs >= CUTOFF_VISUAL_SCORE)
    nr = int(np.sum(mr))
    rs = np.where(mr, prob * np.maximum(ed - 2.6, 0) * np.maximum(gr, 0.01), -1.0)
    bi = int(np.argmax(rs)) if nr > 0 else -1
    bt_y = float(y_c[bi]) if bi >= 0 else float("nan")
    corr = float(np.corrcoef(ct, cr)[0, 1]) if np.std(cr) > 0 else 0.0
    mt = ct > 0.05; mp = ct >= PHYSICAL_CONTRAST_THRESHOLD
    inter = int(np.sum(mt & mr)); union = int(np.sum(mt | mr))
    iou = inter / max(union, 1)
    rec = inter / max(int(np.sum(mt)), 1)
    prec = inter / max(nr, 1)
    f1 = 2*prec*rec / max(prec+rec, 1e-15)
    ip = int(np.sum(mp & mr))
    pp = ip / max(nr, 1); rp = ip / max(int(np.sum(mp)), 1)
    crp = np.maximum(cr, 0.0)
    cw = centroid_weighted(x_c, y_c, z_c, crp)
    ye = cw[1] - cw_t[1] if math.isfinite(cw[1]) and math.isfinite(cw_t[1]) else float("nan")
    sm = iy_arr <= 3
    smp = 100.0 * float(np.sum(crp[sm])) / max(float(np.sum(crp)), 1e-15)
    return {"corr": corr, "iou": iou, "recall": rec, "prec": prec, "f1": f1,
            "prec_phys": pp, "recall_phys": rp, "cw_y": cw[1], "y_err": ye,
            "abs_y_err": abs(ye) if math.isfinite(ye) else 999.0,
            "sh_mass_pct": smp, "bt_y": bt_y, "res_l2": res_l2,
            "max_dens": float(np.max(ed)), "anom": nr}

def mmn(a):
    a = np.array(a); mn, mx = np.min(a), np.max(a)
    return np.zeros_like(a) if mx == mn else (a - mn) / (mx - mn)

def run():
    print("=" * 130)
    print("TerraQuantum — Validación Robusta de Arquitecturas Candidatas")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s. NNZ={kernel.nnz:,}")

    scenarios = generate_scenarios()
    np.random.seed(42)

    # db[arch_name][sc_name] = metrics
    db = {a[0]: {} for a in ARCHITECTURES}

    print("\n[2] Ejecutando escenarios x arquitecturas...")
    total = len(scenarios) * len(ARCHITECTURES)
    idx = 0
    for sc_name, ct in scenarios.items():
        cw_t = centroid_weighted(x_c, y_c, z_c, ct)
        g_exact = kernel @ ct
        ns = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, ns, size=g_exact.shape)
        for a_name, beta, alpha in ARCHITECTURES:
            idx += 1
            sys.stdout.write(f"\r    {idx}/{total} {sc_name} / {a_name}          ")
            sys.stdout.flush()
            ed, vs, prob, rl2 = solve_exp(kernel, g_obs, beta, alpha)
            db[a_name][sc_name] = compute_metrics(ct, ed, vs, prob, rl2)

    print("\n\n[3] Resultados por escenario:")
    for sc_name in scenarios:
        print(f"\n  ── {sc_name} ──")
        print(f"  {'Arquitectura':<26} | {'Corr':>7} | {'IoU':>7} | {'F1':>7} | {'y_err':>8} | {'sh%':>6} | {'PPrec':>6} | {'bt_y':>6}")
        print("  " + "-" * 95)
        for a_name, _, _ in ARCHITECTURES:
            m = db[a_name][sc_name]
            print(f"  {a_name:<26} | {m['corr']:>7.4f} | {m['iou']:>7.4f} | {m['f1']:>7.4f} | {m['y_err']:>+8.1f} | {m['sh_mass_pct']:>5.1f}% | {m['prec_phys']:>5.1%} | {m['bt_y']:>6.1f}")

    # Resumen por arquitectura
    print("\n" + "=" * 130)
    print("RESUMEN POR ARQUITECTURA (agregado de 5 escenarios)")
    print("-" * 130)
    summary = []
    for a_name, beta, alpha in ARCHITECTURES:
        vals = list(db[a_name].values())
        s = {
            "name": a_name, "beta": beta, "alpha": alpha,
            "mc": np.mean([v["corr"] for v in vals]),
            "mi": np.mean([v["iou"] for v in vals]),
            "mf": np.mean([v["f1"] for v in vals]),
            "may": np.mean([v["abs_y_err"] for v in vals]),
            "way": np.max([v["abs_y_err"] for v in vals]),
            "ms": np.mean([v["sh_mass_pct"] for v in vals]),
            "mpp": np.mean([v["prec_phys"] for v in vals]),
            "mrp": np.mean([v["recall_phys"] for v in vals]),
        }
        summary.append(s)

    print(f"{'Arquitectura':<26} | {'mCorr':>7} | {'mIoU':>7} | {'mF1':>7} | {'m|y_err|':>8} | {'w|y_err|':>8} | {'mSh%':>6} | {'mPPrec':>7} | {'mPRec':>7}")
    print("-" * 130)
    for s in summary:
        print(f"{s['name']:<26} | {s['mc']:>7.4f} | {s['mi']:>7.4f} | {s['mf']:>7.4f} | {s['may']:>7.1f}m | {s['way']:>7.1f}m | {s['ms']:>5.1f}% | {s['mpp']:>6.1%} | {s['mrp']:>6.1%}")

    # Score robusto compuesto
    # robust_score = 0.25*N(mc) + 0.20*N(mi) + 0.15*N(mf) + 0.15*N(mpp) + 0.10*N(mrp) - 0.10*N(may) - 0.05*N(way)
    nc = mmn([s["mc"] for s in summary])
    ni = mmn([s["mi"] for s in summary])
    nf = mmn([s["mf"] for s in summary])
    npp = mmn([s["mpp"] for s in summary])
    nrp = mmn([s["mrp"] for s in summary])
    nay = mmn([s["may"] for s in summary])
    nwy = mmn([s["way"] for s in summary])
    for j, s in enumerate(summary):
        s["rscore"] = 0.25*nc[j] + 0.20*ni[j] + 0.15*nf[j] + 0.15*npp[j] + 0.10*nrp[j] - 0.10*nay[j] - 0.05*nwy[j]

    ranked = sorted(summary, key=lambda x: x["rscore"], reverse=True)

    print("\n" + "=" * 130)
    print("RANKING ROBUSTO GENERAL")
    print("Score = 0.25*N(mCorr) + 0.20*N(mIoU) + 0.15*N(mF1) + 0.15*N(mPPrec) + 0.10*N(mPRec) - 0.10*N(m|y_err|) - 0.05*N(w|y_err|)")
    print("-" * 130)
    for i, s in enumerate(ranked):
        print(f"  {i+1}. {s['name']:<26} Score={s['rscore']:.3f}  (b={s['beta']:.2f}, a={s['alpha']:.2f})")

    print("\nMEJOR POR CATEGORÍA:")
    best_corr = max(summary, key=lambda x: x["mc"])
    best_depth = min(summary, key=lambda x: x["may"])
    best_iou = max(summary, key=lambda x: x["mi"])
    best_worst = min(summary, key=lambda x: x["way"])
    print(f"  Forma (Corr)       : {best_corr['name']} (mCorr={best_corr['mc']:.4f})")
    print(f"  Profundidad (|y|)  : {best_depth['name']} (m|y_err|={best_depth['may']:.1f}m)")
    print(f"  IoU                : {best_iou['name']} (mIoU={best_iou['mi']:.4f})")
    print(f"  Peor caso (w|y|)   : {best_worst['name']} (w|y_err|={best_worst['way']:.1f}m)")

    # Diagnóstico
    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)

    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else winner
    if winner["rscore"] > runner["rscore"] * 1.15:
        print(f"  ✅ '{winner['name']}' domina de forma robusta (score {winner['rscore']:.3f} vs segundo {runner['rscore']:.3f}).")
    else:
        print(f"  ⚠  No hay un ganador claro. '{winner['name']}' ({winner['rscore']:.3f}) y '{runner['name']}' ({runner['rscore']:.3f}) son cercanos.")

    # Beta alto en shallow
    for a_name, beta, _ in ARCHITECTURES:
        if beta >= 1.0:
            sh_yerr = db[a_name].get("shallow_body", {}).get("abs_y_err", 0)
            if sh_yerr > 50:
                print(f"  ⚠  '{a_name}' (beta={beta}) FALLA en shallow_body (|y_err|={sh_yerr:.1f}m).")
    # Beta bajo en deep
    for a_name, beta, _ in ARCHITECTURES:
        if beta <= 0.50:
            dp_yerr = db[a_name].get("deep_body", {}).get("abs_y_err", 0)
            if dp_yerr > 80:
                print(f"  ⚠  '{a_name}' (beta={beta}) FALLA en deep_body (|y_err|={dp_yerr:.1f}m).")

    # Tradeoff
    if best_corr["name"] != best_depth["name"]:
        print(f"  ⚠  Tradeoff: '{best_corr['name']}' maximiza forma, '{best_depth['name']}' maximiza profundidad.")

    # best_target_y
    all_bt = []
    all_cw = []
    for a_name, _, _ in ARCHITECTURES:
        for m in db[a_name].values():
            if math.isfinite(m["bt_y"]): all_bt.append(m["bt_y"])
            if math.isfinite(m["cw_y"]): all_cw.append(m["cw_y"])
    if all_bt and all_cw and np.mean(all_bt) < np.mean(all_cw) * 0.75:
        print("  ⚠  best_target_y sigue SISTEMÁTICAMENTE SESGADO somero respecto al centroide volumétrico.")
        print("     Esto es un problema de la heurística de ranking, separado del depth weighting.")

    # Recomendación
    print("\nRECOMENDACIÓN TÉCNICA:")
    if winner["rscore"] > runner["rscore"] * 1.15 and winner["way"] < 80:
        print(f"  -> Implementar '{winner['name']}' (beta={winner['beta']:.2f}, alpha={winner['alpha']:.2f}) como parámetro productivo único.")
    elif winner["way"] > 100:
        print("  -> Ninguna arquitectura tiene un peor caso aceptable.")
        print("  -> Se recomienda modelo recomendado + banda de incertidumbre, o parametrización adaptativa futura.")
    else:
        print(f"  -> Implementar '{winner['name']}' (beta={winner['beta']:.2f}, alpha={winner['alpha']:.2f}) como modelo recomendado,")
        print("     con banda de incertidumbre informada por los otros candidatos del ranking.")

    print("\nFin de la suite de validación robusta no productiva.\n")

if __name__ == "__main__":
    run()
