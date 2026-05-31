"""
scripts/validation/synthetic_cases.py
======================================
Suite de validación sintética para GravimetryForward + GravimetryInversion.

Casos disponibles:
  - synthetic_single_body : cuerpo único centrado (referencia)
  - synthetic_deep_body   : cuerpo único profundo (menor señal en superficie)
  - synthetic_two_bodies  : dos cuerpos separados en x/z

Ejecutar desde la raíz del backend:
    python scripts/validation/synthetic_cases.py
"""

import json
import os
import sys

import numpy as np

# Permite importar desde la raíz del proyecto sin instalación de paquete
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from exploration.gravimetry import GravimetryForward, GravimetryInversion  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes globales (grilla, sensores, inversión)
# ---------------------------------------------------------------------------
NX, NY, NZ = 12, 8, 12
BLOCK_SIZE  = 10.0

BASE_DENSITY          = 2.6    # t/m³ (fondo uniforme)
BODY_DENSITY_CONTRAST = 0.6    # contraste: 3.2 - 2.6

N_SENSORS_X = 8
N_SENSORS_Z = 8

LAMBDA_MAG    = 1e-5
ALPHA_SPATIAL = 1.0
CUTOFF_RADIUS = 800.0

OUTPUT_DIR = os.path.join("tmp", "validation")

# ---------------------------------------------------------------------------
# Definición de casos
# ---------------------------------------------------------------------------
# Cada caso es un dict con:
#   name          : identificador único (→ <name>_metrics.json)
#   bodies        : lista de dicts {cx, cy, cz, radius, contrast}
#   pass_center   : umbral máximo de center_error_m
#   pass_corr     : umbral mínimo de correlation
#   pass_overlap  : umbral mínimo de top_overlap_score

CASES = [
    {
        "name": "synthetic_single_body",
        "bodies": [
            {"cx": NX * BLOCK_SIZE / 2.0,   # 60 m
             "cy": NY * BLOCK_SIZE / 2.0,   # 40 m
             "cz": NZ * BLOCK_SIZE / 2.0,   # 60 m
             "radius": 20.0,
             "contrast": BODY_DENSITY_CONTRAST},
        ],
        "pass_center":  30.0,
        "pass_corr":     0.35,
        "pass_overlap":  0.30,
    },
    {
        "name": "synthetic_deep_body",
        "bodies": [
            {"cx": NX * BLOCK_SIZE / 2.0,   # 60 m
             "cy": 60.0,                     # profundo
             "cz": NZ * BLOCK_SIZE / 2.0,   # 60 m
             "radius": 20.0,
             "contrast": BODY_DENSITY_CONTRAST},
        ],
        "pass_center":  40.0,
        "pass_corr":     0.25,
        "pass_overlap":  0.20,
    },
    {
        "name": "synthetic_two_bodies",
        "bodies": [
            {"cx": 30.0, "cy": NY * BLOCK_SIZE / 2.0, "cz": 30.0,
             "radius": 15.0, "contrast": BODY_DENSITY_CONTRAST},
            {"cx": 90.0, "cy": NY * BLOCK_SIZE / 2.0, "cz": 90.0,
             "radius": 15.0, "contrast": BODY_DENSITY_CONTRAST},
        ],
        "pass_center":  35.0,
        "pass_corr":     0.25,
        "pass_overlap":  0.20,
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_voxel_grid(nx: int, ny: int, nz: int, dx: float):
    """Grilla aplanada order='F': idx = ix + nx*iy + nx*ny*iz."""
    grid_x, grid_y, grid_z = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)
    x_c = (ix * dx) + (dx / 2.0)
    y_c = (iy * dx) + (dx / 2.0)
    z_c = (iz * dx) + (dx / 2.0)
    return ix, iy, iz, x_c, y_c, z_c


def build_contrast_for_bodies(x_c, y_c, z_c, bodies: list) -> np.ndarray:
    """Suma de cuerpos esféricos; cada uno definido por un dict del caso."""
    contrast = np.zeros(len(x_c), dtype=np.float64)
    for body in bodies:
        r2 = ((x_c - body["cx"])**2
              + (y_c - body["cy"])**2
              + (z_c - body["cz"])**2)
        contrast = np.where(r2 <= body["radius"]**2,
                            contrast + body["contrast"],
                            contrast)
    return contrast


def build_sensor_array(nx: int, nz: int, dx: float, n_sx: int, n_sz: int):
    """Grilla regular de sensores en superficie (y_m = 0)."""
    xs = np.linspace(dx / 2.0, nx * dx - dx / 2.0, n_sx)
    zs = np.linspace(dx / 2.0, nz * dx - dx / 2.0, n_sz)
    XX, ZZ = np.meshgrid(xs, zs)
    x_s = XX.ravel()
    z_s = ZZ.ravel()
    y_s = np.zeros_like(x_s)
    return np.column_stack([x_s, y_s, z_s])


def add_deterministic_noise(g: np.ndarray, scale: float = 0.02) -> np.ndarray:
    """Ruido determinístico sin/cos; reproducible sin random."""
    idx = np.arange(len(g), dtype=np.float64)
    noise = scale * np.abs(g).mean() * (
        0.6 * np.sin(idx * 0.7) + 0.4 * np.cos(idx * 1.3)
    )
    return g + noise


def center_of_mass(weights: np.ndarray, x_c, y_c, z_c) -> np.ndarray:
    """Centro de masa ponderado (solo pesos positivos)."""
    w = np.maximum(weights, 0.0)
    total = w.sum()
    if total <= 0:
        return np.array([x_c.mean(), y_c.mean(), z_c.mean()])
    return np.array([
        (w * x_c).sum() / total,
        (w * y_c).sum() / total,
        (w * z_c).sum() / total,
    ])


def compute_pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Correlación de Pearson entre dos vectores."""
    a0 = a - a.mean()
    b0 = b - b.mean()
    na = float(np.linalg.norm(a0))
    nb = float(np.linalg.norm(b0))
    if na > 0 and nb > 0:
        return float(np.dot(a0, b0) / (na * nb))
    return 0.0


def compute_top_overlap(true_contrast: np.ndarray,
                         est_contrast: np.ndarray,
                         pct: float = 0.05) -> float:
    """
    Solapamiento entre el top <pct> de voxels más intensos del contraste
    verdadero y el contraste invertido.
    """
    top_k = max(1, int(pct * len(true_contrast)))
    true_top = set(np.argsort(true_contrast)[-top_k:].tolist())
    inv_top  = set(np.argsort(est_contrast)[-top_k:].tolist())
    return float(len(true_top & inv_top) / len(true_top))


# ---------------------------------------------------------------------------
# Motor de un caso
# ---------------------------------------------------------------------------

def run_case(case: dict, x_c, y_c, z_c, sensor_coords,
             kernel, forward) -> dict:
    """
    Ejecuta la inversión para un caso y devuelve un dict de resultados.
    Lanza excepción si algo falla (→ status FAIL en main).
    """
    name = case["name"]
    bodies = case["bodies"]

    # Modelo verdadero
    true_contrast = build_contrast_for_bodies(x_c, y_c, z_c, bodies)
    true_density  = BASE_DENSITY + true_contrast
    body_voxels   = int(np.sum(true_contrast > 0))

    # Para casos multi-cuerpo: CoM del contraste combinado como referencia
    true_center = center_of_mass(true_contrast, x_c, y_c, z_c)

    # Forward + ruido determinístico
    g_clean    = kernel @ true_contrast
    g_observed = add_deterministic_noise(g_clean, scale=0.02)

    # Inversión
    inversor = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE)
    est_density, _probability, _misfit_percent = inversor.solve_inversion_lsqr(
        g_observed, kernel,
        lambda_mag=LAMBDA_MAG,
        alpha_spatial=ALPHA_SPATIAL,
    )

    # Métricas
    est_contrast = est_density - BASE_DENSITY
    inv_center   = center_of_mass(np.maximum(est_contrast, 0.0),
                                   x_c, y_c, z_c)
    center_error_m   = float(np.linalg.norm(true_center - inv_center))
    correlation      = compute_pearson(true_contrast, est_contrast)
    top_overlap_score = compute_top_overlap(true_contrast, est_contrast)
    g_modeled        = kernel @ est_contrast
    residual_l2      = float(np.linalg.norm(g_observed - g_modeled))
    true_density_max = float(true_density.max())
    inv_density_max  = float(est_density.max())

    print(f"  [VAL]  Cuerpo(s): {body_voxels} voxels | "
          f"CoM verdadero=({true_center[0]:.1f},{true_center[1]:.1f},{true_center[2]:.1f}) m")
    print(f"  [VAL]  CoM invertido=({inv_center[0]:.1f},{inv_center[1]:.1f},{inv_center[2]:.1f}) m")
    print(f"  [VAL]  center_error={center_error_m:.2f} m | "
          f"correlation={correlation:.4f} | top_overlap={top_overlap_score:.4f}")
    print(f"  [VAL]  density_max: true={true_density_max:.3f} inv={inv_density_max:.3f} t/m³")
    print(f"  [VAL]  residual_l2={residual_l2:.4e}")

    # Veredicto del caso
    passed_center  = center_error_m   <= case["pass_center"]
    passed_corr    = correlation       >= case["pass_corr"]
    passed_overlap = top_overlap_score >= case["pass_overlap"]
    passed_quality = passed_corr or passed_overlap

    if passed_center and passed_quality:
        status = "PASS"
    else:
        status = "WARNING"

    return {
        "case":    name,
        "status":  status,
        "grid":    {"nx": NX, "ny": NY, "nz": NZ, "block_size": BLOCK_SIZE},
        "bodies":  bodies,
        "n_sensors": len(sensor_coords),
        "inversion_params": {
            "lambda_mag": LAMBDA_MAG, "alpha_spatial": ALPHA_SPATIAL,
            "cutoff_radius": CUTOFF_RADIUS,
        },
        "results": {
            "true_center_m":    true_center.tolist(),
            "inv_center_m":     inv_center.tolist(),
            "center_error_m":   round(center_error_m, 3),
            "true_density_max": round(true_density_max, 4),
            "inv_density_max":  round(inv_density_max, 4),
            "correlation":      round(correlation, 6),
            "top_overlap_score": round(top_overlap_score, 6),
            "residual_l2":      round(residual_l2, 6),
        },
        "pass_criteria": {
            "max_center_error_m": case["pass_center"],
            "min_correlation":    case["pass_corr"],
            "min_top_overlap":    case["pass_overlap"],
            "logic": "center_ok AND (correlation >= min_correlation OR top_overlap >= min_top_overlap)",
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("TerraQuantum — Suite de Validación Sintética")
    print(f"  Casos: {len(CASES)} | Grilla: {NX}x{NY}x{NZ} | dx={BLOCK_SIZE} m")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Recursos compartidos por todos los casos
    _ix, _iy, _iz, x_c, y_c, z_c = build_voxel_grid(NX, NY, NZ, BLOCK_SIZE)
    sensor_coords = build_sensor_array(NX, NZ, BLOCK_SIZE, N_SENSORS_X, N_SENSORS_Z)
    print(f"[VAL] Grilla: {NX*NY*NZ} voxels | Sensores: {len(sensor_coords)}")

    forward = GravimetryForward(BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE,
                                cutoff_radius=CUTOFF_RADIUS)
    # El kernel depende solo de las coordenadas de voxels y sensores,
    # no del contraste → se puede reutilizar entre casos.
    kernel = forward.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)

    summary_cases = []
    n_pass = n_warning = n_fail = 0

    for case in CASES:
        name = case["name"]
        print(f"\n{'─'*60}")
        print(f"[VAL] Caso: {name}")
        print(f"{'─'*60}")

        try:
            result = run_case(case, x_c, y_c, z_c, sensor_coords, kernel, forward)

            # JSON individual
            out_path = os.path.join(OUTPUT_DIR, f"{name}_metrics.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"  [VAL] JSON guardado: {out_path}")

            status = result["status"]
            r = result["results"]
            summary_cases.append({
                "case":             name,
                "status":           status,
                "center_error_m":   r["center_error_m"],
                "correlation":      r["correlation"],
                "top_overlap_score": r["top_overlap_score"],
                "residual_l2":      r["residual_l2"],
            })

            icon = "✅" if status == "PASS" else "⚠️ "
            print(
                f"\n  {icon} {status} — {name}\n"
                f"      center_error={r['center_error_m']:.2f} m"
                f" | corr={r['correlation']:.4f}"
                f" | overlap={r['top_overlap_score']:.4f}"
            )

            if status == "PASS":
                n_pass += 1
            else:
                n_warning += 1

        except Exception as exc:  # noqa: BLE001
            print(f"\n  ❌ FAIL — {name} lanzó excepción: {exc}")
            summary_cases.append({
                "case":   name, "status": "FAIL",
                "center_error_m": None, "correlation": None,
                "top_overlap_score": None, "residual_l2": None,
            })
            n_fail += 1

    # Resumen global
    summary = {
        "total_cases": len(CASES),
        "passed":   n_pass,
        "warnings": n_warning,
        "failed":   n_fail,
        "cases":    summary_cases,
    }
    summary_path = os.path.join(OUTPUT_DIR, "validation_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("RESUMEN GLOBAL")
    print(f"  Total: {len(CASES)} | ✅ PASS: {n_pass} | "
          f"⚠️  WARNING: {n_warning} | ❌ FAIL: {n_fail}")
    for sc in summary_cases:
        icon = {"PASS": "✅", "WARNING": "⚠️ ", "FAIL": "❌"}.get(sc["status"], "?")
        extra = (
                f"center={sc['center_error_m']:.2f} m"
                f" | corr={sc['correlation']:.4f}"
                f" | overlap={sc['top_overlap_score']:.4f}"
                if sc["center_error_m"] is not None else "excepción"
            )
        print(f"  {icon} {sc['case']:<30}")
        print(f"       {extra}")
    print(f"\n[VAL] Resumen guardado en: {summary_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
