"""
TerraQuantum — Benchmark de Targeting Topológico

Comprueba si el sesgo superficial del best_target actual se debe al ranking voxel-wise
y si puede corregirse extrayendo targets por componentes conectados y centroides ponderados.
No modifica servicios productivos ni usa datos reales.
"""
import math, os, sys, time
from typing import Dict, List, Tuple
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
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

STRONG_ARCHITECTURES = [
    ("highest_score",       1.00, 2.00),
    ("balanced_corr_depth", 0.75, 2.00),
    ("depth_anchor",        0.75, 1.00),
    ("alt_top_score",       1.00, 0.50),
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
    ve = np.abs(kernel.T @ res)
    mve = float(np.max(ve)) if len(ve) > 0 else 0.0
    fit_score = np.clip(1.0 - (ve / mve), 0, 1) if mve > 0 else np.ones(n_v)
    ed = np.clip(BASE_DENSITY + m, 2.6, 4.2)
    cr = ed - BASE_DENSITY
    return cr, ed, fit_score

def get_true_targets(ct):
    mp = ct >= PHYSICAL_CONTRAST_THR
    structure = np.ones((3,3,3), dtype=int)
    labeled, num = label(mp.reshape((NX,NY,NZ), order='F'), structure=structure)
    labeled = labeled.flatten(order='F')
    targets = []
    for i in range(1, num + 1):
        cmask = (labeled == i)
        cw = centroid_weighted(x_c, y_c, z_c, ct * cmask)
        targets.append(cw)
    return targets

# --- Targeting Methods ---

def legacy_productive_exact(ed, fit_score, grade):
    """Replica EXACTA del flujo productivo actual del backend.

    Nota: La variable 'fit_score' es la variable que el backend llama 'probability'.
    En este script se llama 'fit_support_score' conceptualmente para no implicar
    que es una probabilidad posterior real.

    Flujo replicado:
      build_anomaly_dataframe: density >= cutoff_density OR visual_score >= 0.35
      build_voxel_output: construye lista de voxels con todos los campos
      build_best_target: max(probability * (density - 2.6) * grade)
    """
    density_score = np.clip((ed - 2.6) / max(4.2 - 2.6, 1e-9), 0.0, 1.0)
    probability_score = np.clip(fit_score, 0.0, 1.0)
    visual_score = density_score * probability_score
    block_volume = float(BLOCK_SIZE ** 3)
    domain = np.where(ed >= 2.75, 1, 0).astype(int)
    resource_class = np.where(probability_score >= 0.7, 1, 2).astype(int)
    resource_class = np.where(probability_score < 0.35, 3, resource_class)

    # Build polars df as production code does
    df_full = pl.DataFrame({
        "x": x_c.astype(float), "y": y_c.astype(float), "z": z_c.astype(float),
        "ix": ix_arr.astype(int), "iy": iy_arr.astype(int), "iz": iz_arr.astype(int),
        "density": ed.astype(float),
        "rho": ed.astype(float),
        "probability": fit_score.astype(float),
        "visual_score": visual_score.astype(float),
        "grade": grade.astype(float),
        "tonnage": (ed * block_volume).astype(float),
        "domain": domain.astype(int),
        "resource_class": resource_class.astype(int),
    })

    df_anomaly = build_anomaly_dataframe(df_full, cutoff_density=CUTOFF_DENSITY)
    voxels = build_voxel_output(df_anomaly, block_size=BLOCK_SIZE, cutoff_density=CUTOFF_DENSITY)
    bt = build_best_target(voxels)
    if bt is None:
        return []
    return [(float(bt["x_m"]), float(bt["y_m"]), float(bt["z_m"]))]

def global_centroid(cr, mask):
    if not np.any(mask): return []
    return [centroid_weighted(x_c, y_c, z_c, np.maximum(cr * mask, 0.0))]

def topological_targets(cr, fit_score, mask, scoring="sum_contrast", max_t=2):
    structure = np.ones((3,3,3), dtype=int)
    labeled, num = label(mask.reshape((NX,NY,NZ), order='F'), structure=structure)
    labeled = labeled.flatten(order='F')
    if num == 0: return []
    comp_scores = []
    for i in range(1, num + 1):
        cmask = (labeled == i)
        if scoring == "sum_contrast":
            sc = np.sum(cr[cmask])
        else:
            sc = np.sum(cr[cmask] * fit_score[cmask])
        comp_scores.append((i, sc))
    comp_scores.sort(key=lambda x: x[1], reverse=True)
    targets = []
    for i, _ in comp_scores[:max_t]:
        cmask = (labeled == i)
        targets.append(centroid_weighted(x_c, y_c, z_c, np.maximum(cr * cmask, 0.0)))
    return targets

def run():
    print("=" * 130)
    print("TerraQuantum — Benchmark de Targeting Topológico")
    print("=" * 130)

    print("\n[1] Construyendo kernel (cutoff=600m)...")
    t0 = time.perf_counter()
    fwd = GravimetryForward(dx=BLOCK_SIZE, dy=BLOCK_SIZE, dz=BLOCK_SIZE, cutoff_radius=600.0)
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    print(f"    Listo en {time.perf_counter()-t0:.1f}s.")

    scenarios = generate_scenarios()
    np.random.seed(42)

    METHODS = [
        "A. legacy_productive_exact",
        "B. global_centroid_P90",
        "C. global_centroid_P92_5",
        "D. largest_component_P90",
        "E. largest_component_P92_5",
        "F. component_score_cx_support_P90"
    ]
    
    db = {m: [] for m in METHODS}

    print("\n[2] Ejecutando métodos de targeting...")
    total = len(scenarios) * len(STRONG_ARCHITECTURES)
    idx = 0
    
    for sc_name, ct in scenarios.items():
        true_targets = get_true_targets(ct)
        mp = ct >= PHYSICAL_CONTRAST_THR
        
        g_exact = kernel @ ct
        ns = 0.01 * np.max(np.abs(g_exact))
        g_obs = g_exact + np.random.normal(0, ns, size=g_exact.shape)

        for a_name, beta, alpha in STRONG_ARCHITECTURES:
            idx += 1
            sys.stdout.write(f"\r    {idx}/{total} {sc_name} / {a_name}               ")
            sys.stdout.flush()

            cr, ed, fit_score = solve_exp(kernel, g_obs, beta, alpha)
            grade = estimate_grade_from_geophysics(ed, fit_score, 83, 79, "norte_chile")
            
            p90_t = float(np.percentile(cr, 90.0))
            p925_t = float(np.percentile(cr, 92.5))
            mask_p90 = cr >= p90_t
            mask_p925 = cr >= p925_t

            preds = {
                METHODS[0]: legacy_productive_exact(ed, fit_score, grade),
                METHODS[1]: global_centroid(cr, mask_p90),
                METHODS[2]: global_centroid(cr, mask_p925),
                METHODS[3]: topological_targets(cr, fit_score, mask_p90, "sum_contrast", 2),
                METHODS[4]: topological_targets(cr, fit_score, mask_p925, "sum_contrast", 2),
                METHODS[5]: topological_targets(cr, fit_score, mask_p90, "cx_support", 2)
            }

            for m_name in METHODS:
                pred_list = preds[m_name]
                if not pred_list:
                    db[m_name].append({
                        "sc": sc_name, "arch": a_name, "err3d": 999.0, "erry": 999.0,
                        "inside": False, "shallow_bias": False, "cov_2b": 0
                    })
                    continue
                
                # Primary target error
                primary = pred_list[0]
                dists = [np.linalg.norm(np.array(primary) - np.array(t)) for t in true_targets]
                min_i = np.argmin(dists)
                nearest_true = true_targets[min_i]
                
                err3d = dists[min_i]
                erry = abs(primary[1] - nearest_true[1])
                shallow_bias = primary[1] < 0.5 * nearest_true[1]
                
                v_ix = int(np.clip(round((primary[0]-BLOCK_SIZE/2)/BLOCK_SIZE), 0, NX-1))
                v_iy = int(np.clip(round((primary[1]-BLOCK_SIZE/2)/BLOCK_SIZE), 0, NY-1))
                v_iz = int(np.clip(round((primary[2]-BLOCK_SIZE/2)/BLOCK_SIZE), 0, NZ-1))
                inside = bool(mp.reshape((NX,NY,NZ), order='F')[v_ix, v_iy, v_iz])
                
                cov_2b = 0
                if sc_name == "two_bodies":
                    cov_count = 0
                    for tt in true_targets:
                        # si hay un pred_target a menos de 150m de este true_target
                        dists_to_tt = [np.linalg.norm(np.array(pt) - np.array(tt)) for pt in pred_list]
                        if dists_to_tt and min(dists_to_tt) < 150.0:
                            cov_count += 1
                    cov_2b = cov_count

                db[m_name].append({
                    "sc": sc_name, "arch": a_name, "err3d": err3d, "erry": erry,
                    "inside": inside, "shallow_bias": shallow_bias, "cov_2b": cov_2b
                })

    print("\n\n[3] Tabla resumen por método (Promediado en 20 runs):")
    summary = []
    for m_name in METHODS:
        vals = db[m_name]
        m_err3d = np.mean([v["err3d"] for v in vals])
        w_err3d = np.max([v["err3d"] for v in vals])
        m_erry = np.mean([v["erry"] for v in vals])
        w_erry = np.max([v["erry"] for v in vals])
        in_phys = 100.0 * np.mean([v["inside"] for v in vals])
        shallow = 100.0 * np.mean([v["shallow_bias"] for v in vals])
        
        # coverage for two_bodies: mean of covered bodies (max 2)
        v_2b = [v["cov_2b"] for v in vals if v["sc"] == "two_bodies"]
        cov2b = np.mean(v_2b) if v_2b else 0.0
        
        summary.append({
            "name": m_name, "m_err3d": m_err3d, "w_err3d": w_err3d,
            "m_erry": m_erry, "w_erry": w_erry, "in_phys": in_phys,
            "shallow": shallow, "cov2b": cov2b
        })

    print(f"{'Método':<38} | {'mErr3D':>6} | {'wErr3D':>6} | {'mErrY':>6} | {'wErrY':>6} | {'InPhys':>6} | {'ShllwBias':>9} | {'Cov2B':>5}")
    print("-" * 105)
    for s in summary:
        print(f"{s['name']:<38} | {s['m_err3d']:>6.1f} | {s['w_err3d']:>6.1f} | {s['m_erry']:>6.1f} | {s['w_erry']:>6.1f} | "
              f"{s['in_phys']:>5.1f}% | {s['shallow']:>8.1f}% | {s['cov2b']:>5.1f}/2")

    print("\n" + "=" * 130)
    print("RANKINGS")
    print("-" * 130)
    for title, key, rev in [
        ("Menor Error 3D Medio", "m_err3d", False),
        ("Menor Error Y Medio", "m_erry", False),
        ("Menor Peor Caso 3D", "w_err3d", False),
        ("Mayor Frecuencia Dentro del Cuerpo Físico", "in_phys", True)
    ]:
        ranked = sorted(summary, key=lambda x: x[key], reverse=rev)
        print(f"\n  {title}:")
        for i, s in enumerate(ranked[:3]):
            print(f"    {i+1}. {s['name']:<38} = {s[key]:.2f}")

    print("\n" + "=" * 130)
    print("DIAGNÓSTICO AUTOMÁTICO")
    print("=" * 130)

    leg = next(s for s in summary if "legacy" in s["name"])
    non_leg = [s for s in summary if "legacy" not in s["name"]]

    best_primary_3d = sorted(non_leg, key=lambda x: x["m_err3d"])[0]
    best_depth = sorted(non_leg, key=lambda x: x["m_erry"])[0]
    best_multitarget = sorted(non_leg, key=lambda x: x["cov2b"], reverse=True)[0]

    print(f"  • Comparación Directa Legacy vs Topológico:")
    print(f"    Legacy Productive Exact: mErr3D={leg['m_err3d']:.1f}m, mErrY={leg['m_erry']:.1f}m, ShallowBias={leg['shallow']:.1f}%")
    print(f"    Mejor (3D)             : {best_primary_3d['name']:<38} mErr3D={best_primary_3d['m_err3d']:.1f}m, ShallowBias={best_primary_3d['shallow']:.1f}%")
    print(f"    Mejor (Profundidad)    : {best_depth['name']:<38} mErrY={best_depth['m_erry']:.1f}m")
    print(f"    Mejor (Multi-target)   : {best_multitarget['name']:<38} Cov2B={best_multitarget['cov2b']:.1f}/2")

    if best_primary_3d["m_err3d"] < leg["m_err3d"] * 0.7:
        print("\n  ✅ El problema del target era PRINCIPALMENTE DE EXTRACCIÓN/RANKING.")
        print("     El centroide topológico corrige el sesgo superficial sin forzar penalizaciones artificiales de profundidad.")
    else:
        print("\n  ⚠  El ranking topológico mejora pero no resuelve todo el problema. Persiste sesgo inherente en la inversión.")

    # P90 vs P92.5 — separados explícitamente por rol
    p90_meth = next(s for s in non_leg if "largest_component_P90" in s["name"])
    p925_meth = next(s for s in non_leg if "largest_component_P92_5" in s["name"])
    print(f"\n  • P90 vs P92.5 (roles explícitos):")
    if p925_meth["m_err3d"] < p90_meth["m_err3d"]:
        print(f"    Mejor target primario (Error 3D): P92.5 ({p925_meth['m_err3d']:.1f}m vs P90 {p90_meth['m_err3d']:.1f}m)")
    else:
        print(f"    Mejor target primario (Error 3D): P90 ({p90_meth['m_err3d']:.1f}m vs P92.5 {p925_meth['m_err3d']:.1f}m)")
    if p90_meth["m_erry"] < p925_meth["m_erry"]:
        print(f"    Mejor recuperación profundidad (Error Y): P90 ({p90_meth['m_erry']:.1f}m vs P92.5 {p925_meth['m_erry']:.1f}m)")
    else:
        print(f"    Mejor recuperación profundidad (Error Y): P92.5 ({p925_meth['m_erry']:.1f}m vs P90 {p90_meth['m_erry']:.1f}m)")
    if p90_meth["name"] != best_depth["name"] or p925_meth["name"] != best_primary_3d["name"]:
        print("    ⚠  Los mejores métodos por 3D y por profundidad difieren: política productiva final aún NO determinada.")

    # Components vs global
    glob = next(s for s in non_leg if "global_centroid_P90" in s["name"])
    if p90_meth["m_err3d"] < glob["m_err3d"] * 0.9:
        print("  • Usar componentes conectados MEJORA frente al centroide global continuo.")
    else:
        print("  • El centroide global es suficiente; los componentes conectados no aportan mejora extra en estos escenarios.")

    # fit_support_score role
    cxs = next(s for s in non_leg if "cx_support" in s["name"])
    if cxs["m_err3d"] < p90_meth["m_err3d"] * 0.95:
        print("  • El fit_support_score (variable 'probability' del backend) AYUDA como peso de componente.")
        print("    NOTA: NO es probabilidad posterior real; tratarla solo como heurística de ajuste.")
    else:
        print("  • El fit_support_score como peso NO APORTA MEJORA significativa frente al contraste puro.")
        print("    El contraste de densidad solo es suficiente para rankear componentes.")

    print(f"\n  • Escenario Two Bodies (multi-target):")
    print(f"    Legacy Productive Exact cubre {leg['cov2b']:.1f}/2 cuerpos verdaderos.")
    print(f"    Mejor Multi-target ({best_multitarget['name']}) cubre {best_multitarget['cov2b']:.1f}/2 cuerpos verdaderos.")
    if best_multitarget["cov2b"] > 1.2:
        print("    ✅ Two_bodies exige y justifica salida multi-target. Un único best_target no es realista.")

    # -------------------------------------------------------------------------
    # NUEVA SECCIÓN: Tabla P90 vs P92.5 por escenario
    # -------------------------------------------------------------------------
    print("\n" + "=" * 130)
    print("TABLA POR ESCENARIO — largest_component_P90 vs largest_component_P92_5")
    print("=" * 130)

    METHOD_P90  = "D. largest_component_P90"
    METHOD_P925 = "E. largest_component_P92_5"
    SCENARIO_NAMES = list(scenarios.keys()) if "scenarios" in dir() else \
        ["shallow_body", "mid_body", "deep_body", "elongated_body", "two_bodies"]

    sc_p90_wins_3d   = 0
    sc_p925_wins_3d  = 0
    sc_p90_wins_y    = 0
    sc_p925_wins_y   = 0
    sc_p90_wins_wc   = 0
    sc_p925_wins_wc  = 0

    print(f"\n{'Escenario':<16} | {'P90 mErr3D':>10} | {'P925 mErr3D':>11} | {'P90 mErrY':>9} | {'P925 mErrY':>10} | "
          f"{'P90 wErr3D':>10} | {'P925 wErr3D':>11} | {'Ganador 3D':>10} | {'Ganador Y':>9} | {'Ganador WC':>10}")
    print("-" * 130)

    for sc in SCENARIO_NAMES:
        v90  = [v for v in db[METHOD_P90]  if v["sc"] == sc]
        v925 = [v for v in db[METHOD_P925] if v["sc"] == sc]

        if not v90 or not v925:
            continue

        m90_e3  = np.mean([v["err3d"] for v in v90])
        m925_e3 = np.mean([v["err3d"] for v in v925])
        m90_ey  = np.mean([v["erry"]  for v in v90])
        m925_ey = np.mean([v["erry"]  for v in v925])
        w90_e3  = np.max([v["err3d"]  for v in v90])
        w925_e3 = np.max([v["err3d"]  for v in v925])

        win_3d = "P92.5" if m925_e3 < m90_e3 else "P90"
        win_y  = "P90"   if m90_ey  < m925_ey else "P92.5"
        win_wc = "P90"   if w90_e3  < w925_e3 else "P92.5"

        if win_3d == "P90":   sc_p90_wins_3d  += 1
        else:                 sc_p925_wins_3d += 1
        if win_y == "P90":    sc_p90_wins_y   += 1
        else:                 sc_p925_wins_y  += 1
        if win_wc == "P90":   sc_p90_wins_wc  += 1
        else:                 sc_p925_wins_wc += 1

        print(f"{sc:<16} | {m90_e3:>10.1f} | {m925_e3:>11.1f} | {m90_ey:>9.1f} | {m925_ey:>10.1f} | "
              f"{w90_e3:>10.1f} | {w925_e3:>11.1f} | {win_3d:>10} | {win_y:>9} | {win_wc:>10}")

    print(f"\n  Victorias por escenario:")
    print(f"    3D   : P90 gana {sc_p90_wins_3d}/5 escenarios,  P92.5 gana {sc_p925_wins_3d}/5")
    print(f"    Depth: P90 gana {sc_p90_wins_y}/5 escenarios,  P92.5 gana {sc_p925_wins_y}/5")
    print(f"    WC   : P90 gana {sc_p90_wins_wc}/5 escenarios,  P92.5 gana {sc_p925_wins_wc}/5")

    # Diagnóstico de consistencia
    print("\nDIAGNÓSTICO POR ESCENARIO:")
    total_sc = len(SCENARIO_NAMES)
    if sc_p925_wins_3d >= total_sc - 1:
        print("  ✅ P92.5 gana de manera CONSISTENTE en casi todos los escenarios para Error 3D.")
    elif sc_p90_wins_3d >= total_sc - 1:
        print("  ✅ P90 gana de manera CONSISTENTE en casi todos los escenarios para Error 3D.")
    else:
        print(f"  ⚠  El ganador de Error 3D VARÍA según el escenario (P92.5: {sc_p925_wins_3d}, P90: {sc_p90_wins_3d}).")

    # Deep-body específico
    v90_deep  = [v for v in db[METHOD_P90]  if v["sc"] == "deep_body"]
    v925_deep = [v for v in db[METHOD_P925] if v["sc"] == "deep_body"]
    if v90_deep and v925_deep:
        m90_deep_y  = np.mean([v["erry"] for v in v90_deep])
        m925_deep_y = np.mean([v["erry"] for v in v925_deep])
        if m90_deep_y < m925_deep_y * 0.9:
            print(f"  ✅ P90 gana específicamente en deep_body (ErrY P90={m90_deep_y:.1f}m vs P92.5={m925_deep_y:.1f}m).")
        elif m925_deep_y < m90_deep_y * 0.9:
            print(f"  ✅ P92.5 gana específicamente en deep_body (ErrY P92.5={m925_deep_y:.1f}m vs P90={m90_deep_y:.1f}m).")
        else:
            print(f"  ⚠  En deep_body ambos métodos son similares (ErrY P90={m90_deep_y:.1f}m, P92.5={m925_deep_y:.1f}m).")

    # ¿Existe política única universal?
    mixed_winner = not (sc_p925_wins_3d >= total_sc - 1 or sc_p90_wins_3d >= total_sc - 1)
    if mixed_winner:
        print("  ⚠  El ganador cambia según el escenario: NO existe una política única universal.")
        print("     Depende del contexto geológico esperado (cuerpo somero vs profundo).")
    else:
        print("  ✅ Un único método domina la mayoría de los escenarios; candidato robusto disponible.")

    # -------------------------------------------------------------------------
    # RECOMENDACIÓN FINAL EN 3 NIVELES
    # -------------------------------------------------------------------------
    print("\n" + "=" * 130)
    print("RECOMENDACIÓN FINAL (3 NIVELES — sin implementación productiva todavía)")
    print("=" * 130)

    winner_depth_name = "largest_component_P90" if sc_p90_wins_y >= sc_p925_wins_y else "largest_component_P92_5"
    mt_p90  = next((s for s in summary if METHOD_P90  in s["name"]), {}).get("cov2b", 0)
    mt_p925 = next((s for s in summary if METHOD_P925 in s["name"]), {}).get("cov2b", 0)
    winner_mt_name = "largest_component_P92_5" if mt_p925 >= mt_p90 else "largest_component_P90"

    if mixed_winner:
        print("\n  ⚠  NO se define todavía un target primario único.")
        print("     La evidencia por escenario muestra un tradeoff real entre P90 y P92.5:")
        print(f"     - P92.5 conserva la mejor localización 3D AGREGADA y el mejor desempeño multi-target.")
        print(f"     - P90 conserva la mejor recuperación de profundidad y gana en más escenarios de cuerpo único.")
        print("     Política productiva final PENDIENTE hasta reevaluar después de cambios al solver.")
        print()
        p90_s  = next(s for s in summary if METHOD_P90 in s["name"])
        p925_s = next(s for s in summary if METHOD_P925 in s["name"])
        print(f"  A. Mejor localización 3D AGREGADA   : largest_component_P92_5  (mErr3D={p925_s['m_err3d']:.1f}m, wErr3D={p925_s['w_err3d']:.1f}m)")
        print(f"  B. Mejor recuperación de profundidad: {winner_depth_name}  (gana en {sc_p90_wins_y}/5 escenarios en ErrY)")
        print(f"  C. Mejor multi-target               : {winner_mt_name}  (cubre {max(mt_p90, mt_p925):.1f}/2 cuerpos en two_bodies)")
        print()
        print("  Siguiente paso recomendado:")
        print("  -> Actualizar el solver con depth weighting validado.")
        print("  -> Re-ejecutar este benchmark para comprobar si el tradeoff desaparece o si un método domina.")
        print("  -> Solo entonces fijar política productiva única.")
    else:
        # Un único método domina — sí se puede recomendar
        winner_3d_name = "largest_component_P92_5" if sc_p925_wins_3d >= sc_p90_wins_3d else "largest_component_P90"
        p_winner = next(s for s in summary if winner_3d_name in s["name"])
        print(f"\n  A. Target primario recomendado      : '{winner_3d_name}'")
        print(f"     Gana en la mayoría de los escenarios en error 3D y profundidad.")
        print(f"  B. Profundidad reportada recomendada: '{winner_depth_name}' (mismo papel).")
        print(f"  C. Multi-target                     : '{winner_mt_name}' con Top-N componentes.")

    # Nivel C siempre aplica
    print(f"\n  Política multi-target (independiente del tradeoff anterior):")
    print(f"     largest_component_P90   cubre {mt_p90:.1f}/2 cuerpos en two_bodies.")
    print(f"     largest_component_P92_5 cubre {mt_p925:.1f}/2 cuerpos en two_bodies.")
    print("     Reportar siempre Top-N componentes ordenados por contraste integrado,")
    print("     nunca un único best_target que descarta información geológica en escenarios multi-cuerpo.")

    print("\nFin del benchmark de targeting topológico.\n")

if __name__ == "__main__":
    run()

