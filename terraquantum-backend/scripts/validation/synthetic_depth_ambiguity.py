"""
SINTÉTICO — Cuantificar el valor del ANCLA cuando z SÍ está mal (régimen LdM)
=============================================================================

Los tres experimentos DO-27 (somero / malla profunda / cobertura dispersa) midieron
algo honesto pero NEGATIVO: en DO-27 la profundidad YA está bien resuelta (~31 m) y
ni una malla 4× más profunda ni quitar estaciones la hacen hundir. DO-27 NO tiene la
enfermedad de z, así que NO puede mostrar la cura. La pregunta de venta del ancla
("cuando z está mal, ¿1 pozo la colapsa?") quedó sin número.

Este script construye un caso SINTÉTICO diseñado a propósito para reproducir el
hundimiento que se vio en Laguna del Maule (cuerpo profundo, cobertura regional
dispersa, anomalía de onda larga, malla con espacio libre debajo) y poner número a:

    unconstrained (auto naïf)  →  +guardrails (setup sano)  →  +1 ancla dura

═══════════════════════════════════════════════════════════════════════════════
  DOS BLINDAJES NO NEGOCIABLES (sin ellos el número es mentira)
═══════════════════════════════════════════════════════════════════════════════
1. NO inverse crime. El dato NO se genera con el operador de la inversión. Se genera
   con la gravedad ANALÍTICA de forma cerrada de una ESFERA enterrada (sin malla),
   un operador estructuralmente distinto del kernel Nagy-prisma + masa-puntual del
   motor. Se invierte en malla más gruesa y con ruido realista añadido. El cuerpo
   verdadero (esfera) NO es representable como una celda → no hay auto-engaño.

2. La enfermedad DEBE exhibirse. Si el caso unconstrained NO da error de z grande,
   el dataset no reproduce el problema y el número de la cura no significa nada. El
   script MIDE el z-error del caso unconstrained y marca DISEASE_PRESENT antes de
   reportar la cura. Si la enfermedad no aparece → hay que rediseñar el caso (más
   profundo / más disperso / malla más profunda), NO maquillar el resultado.

═══════════════════════════════════════════════════════════════════════════════
  PRE-REGISTRO (criterio escrito ANTES de ver el resultado — ver PREREG abajo)
═══════════════════════════════════════════════════════════════════════════════
  H1  El caso unconstrained (auto naïf: L2 + malla profunda + bounds saturables)
      debe dar z-error GRANDE (umbral DISEASE_Z_THRESHOLD_M). Si no → caso inválido.
  H2  Los guardrails de setup (compacto + malla capada a profundidad resoluble) deben
      REDUCIR el z-error respecto a unconstrained (mide cuánto era setup malo).
  H3  Añadir 1 ancla dura en el cuerpo verdadero debe reducir el z-error residual
      respecto a +guardrails (mide cuánto aporta el pozo cuando z aún está mal).

NO se tunea nada para pasar. Mismos datos, mismos sensores, mismo ruido en las 3
configuraciones. Lo único que cambia es la columna bajo test. Backend-only.

USO:
  cd terraquantum-backend
  python scripts/validation/synthetic_depth_ambiguity.py
  # → imprime el pre-registro, la tabla y escribe synthetic_depth_ambiguity_report.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import GravimetryForward, GravimetryInversion
from scripts.validation.do27_harness import _grid_centers_fortran
from services.field_validation_service import estimate_location_error

# ══════════════════════════════════════════════════════════════════════════════
#  PARÁMETROS DEL CASO SINTÉTICO  (frame local: x=Este, y=profundidad↓, z=Norte)
# ══════════════════════════════════════════════════════════════════════════════
SEED = 20260628                 # reproducibilidad (jitter de estaciones + ruido)

# --- Geofísica del problema ---------------------------------------------------
BASE_DENSITY = 2.67             # t/m³ roca caja
DELTA_RHO = 0.50                # t/m³ contraste del cuerpo (intrusivo DENSO, Δρ>0)

# --- Cuerpo verdadero: ESFERA enterrada (operador analítico, sin malla) --------
# Profundidad del centroide ≫ espaciado de estaciones → ambigüedad de z real.
BODY_X = 6000.0                 # Norte (centro horizontal del survey)
BODY_Z = 6000.0                 # Este
BODY_DEPTH = 3000.0             # profundidad del centroide bajo superficie (m)
BODY_RADIUS = 800.0             # radio de la esfera (m)

# --- Cobertura: regional + DISPERSA (tipo LdM) --------------------------------
SURVEY_L = 12000.0              # extensión del survey por lado (m)
N_SIDE = 14                     # 14×14 = 196 estaciones → espaciado ~920 m
STATION_JITTER = 120.0          # jitter aleatorio para romper aliasing de grilla
NOISE_MGAL = 0.02               # ruido gaussiano realista de gravímetro (mGal)

# --- Malla de inversión -------------------------------------------------------
BLOCK = 650.0                   # tamaño de celda (m) — MÁS GRUESO que cualquier
                                #   escala del cuerpo (no inverse crime)
NX = NZ = 20                    # 20×650 = 13.0 km cubre el survey + margen
NY_DEEP = 14                    # malla PROFUNDA (auto naïf): 9.1 km → espacio libre
                                #   muy por debajo del cuerpo (3 km) para que z se hunda
NY_CAP = 8                      # malla CAPADA (guardrail): 5.2 km — contiene el cuerpo
                                #   con margen, pero sin sótano libre donde hundirse
CUTOFF = 20000.0               # capta toda la interacción a escala regional

# --- Bounds petrofísicos (IDÉNTICOS en las 3 configs — no se usa la verdad) ----
DENSITY_MIN = BASE_DENSITY       # cuerpo es contraste POSITIVO (denso)
DENSITY_MAX = 3.80               # generoso/saturable (verdad 3.17 queda holgada)

# --- Regularización -----------------------------------------------------------
LAMBDA_GRAV = 1e-3
DEPTH_BETA = 2.0                 # depth-weighting estándar (constante en las 3)
COMPACT_IRLS = 2

# --- Pre-registro: umbral de "enfermedad" -------------------------------------
DISEASE_Z_THRESHOLD_M = 400.0    # z-error que consideramos "grande" (≫ 31 m de DO-27).
                                 #   Si unconstrained < esto → el caso NO reproduce la
                                 #   enfermedad y el resto del experimento es inválido.

PREREG = {
    "H1_disease": (f"unconstrained (L2 + malla {NY_DEEP*BLOCK:.0f} m + bounds saturables) "
                   f"debe dar z-error > {DISEASE_Z_THRESHOLD_M:.0f} m. Si no, caso inválido."),
    "H2_guardrails": "compacto + malla capada a profundidad resoluble debe REDUCIR el z-error.",
    "H3_anchor": "1 ancla dura en el cuerpo verdadero debe reducir el z-error residual.",
    "no_tuning": "mismos datos/sensores/ruido en las 3 configs; sólo cambia la columna bajo test.",
}


# ══════════════════════════════════════════════════════════════════════════════
#  BLINDAJE 1 — Forward ANALÍTICO independiente (esfera, sin malla)
# ══════════════════════════════════════════════════════════════════════════════
def sphere_gravity_ms2(sensors: np.ndarray, *, x0, y0, z0, radius, delta_rho) -> np.ndarray:
    """Componente vertical (profundidad↓) de la gravedad de una esfera enterrada.

    g_y(p) = G · M · (y0 − y_s) / R³   con   M = Δρ·(4/3)π a³   (R = |p − centro|)

    Forma cerrada exacta — NO suma de prismas, NO malla. Estructuralmente distinto del
    kernel de la inversión (Nagy + masa puntual sobre celdas) → evita el inverse crime.
    Devuelve m/s² (el motor gravimétrico opera en SI, igual que producción).
    """
    G = 6.67430e-11
    mass_kg = (delta_rho * 1000.0) * (4.0 / 3.0) * np.pi * radius**3
    dx = sensors[:, 0] - x0
    dy = sensors[:, 1] - y0           # y_s − y0 (sensor en superficie y_s≈0; y0>0 ⇒ <0)
    dz = sensors[:, 2] - z0
    r3 = (dx * dx + dy * dy + dz * dz) ** 1.5
    return -G * mass_kg * dy / r3      # −dy>0 para cuerpo bajo el sensor ⇒ anomalía +


def build_survey(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, float]:
    """Estaciones regionales dispersas (con jitter) + dato sintético con ruido.

    Devuelve (sensors[n,3], g_obs[n] en m/s², sigma_g en m/s²).
    """
    axis = np.linspace(0.0, SURVEY_L, N_SIDE)
    gx, gz = np.meshgrid(axis, axis, indexing="ij")
    x = gx.ravel() + rng.uniform(-STATION_JITTER, STATION_JITTER, gx.size)
    z = gz.ravel() + rng.uniform(-STATION_JITTER, STATION_JITTER, gz.size)
    y = np.zeros_like(x)               # superficie plana (y=profundidad=0)
    sensors = np.column_stack([x, y, z]).astype(np.float64)

    g_clean = sphere_gravity_ms2(
        sensors, x0=BODY_X, y0=BODY_DEPTH, z0=BODY_Z,
        radius=BODY_RADIUS, delta_rho=DELTA_RHO,
    )
    noise_ms2 = NOISE_MGAL * 1e-5      # mGal → m/s²
    g_obs = g_clean + rng.normal(0.0, noise_ms2, g_clean.size)
    sigma_g = max(noise_ms2, 1e-12)    # σ verdadero (lo conocemos: lo inyectamos)
    return sensors, g_obs, sigma_g


# ══════════════════════════════════════════════════════════════════════════════
#  Inversión parametrizable (la malla y la norma son las únicas variables)
# ══════════════════════════════════════════════════════════════════════════════
def invert(sensors, g_obs, sigma_g, *, ny, regularization_norm,
           boreholes=None, anchor_mode="soft"):
    inv = GravimetryInversion(NX, ny, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    x_c, y_c, z_c = _grid_centers_fortran(NX, ny, NZ, BLOCK)
    meta: dict = {}
    rho_full, _score, misfit, _sens = inv.solve_inversion_lsqr(
        g_obs, None, y_c,
        lambda_mag=LAMBDA_GRAV, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors,
        x_c=x_c, z_c=z_c,
        density_min=DENSITY_MIN, density_max=DENSITY_MAX,
        noise_floor=sigma_g, noise_pct=0.02,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm=regularization_norm, compact_max_irls=COMPACT_IRLS,
        # Fase 4: `depth_beta` se elimino de solve_inversion_lsqr (era inerte: Ws lo cancelaba).
        boreholes=boreholes, anchor_mode=anchor_mode,
        solver_meta=meta,
    )
    return np.asarray(rho_full, dtype=np.float64), float(misfit), (x_c, y_c, z_c), meta


def measure(rho, grid, *, ny) -> dict:
    x_c, y_c, z_c = grid
    loc = estimate_location_error(
        rho, x_c, y_c, z_c, (BODY_X, BODY_DEPTH, BODY_Z), base_density=BASE_DENSITY,
    )
    # Saturación al PISO: fracción de celdas de la capa más profunda cerca de density_max.
    deep_layer = y_c >= (ny - 0.5) * BLOCK
    sat = np.isfinite(rho) & (rho >= DENSITY_MAX - 1e-3)
    floor_sat_frac = float(np.mean(sat[deep_layer])) if np.any(deep_layer) else 0.0
    return {
        "z_error_m": loc.get("depth_error_m"),
        "horizontal_error_m": loc.get("horizontal_error_m"),
        "recovered_depth_m": loc.get("recovered_y_m"),
        "true_depth_m": round(BODY_DEPTH, 1),
        "n_strong": loc.get("n_strong"),
        "floor_saturation_frac": round(floor_sat_frac, 3),
    }


def build_anchor() -> np.ndarray:
    """1 sondaje vertical en (BODY_X, BODY_Z) intersectando la esfera de techo a base,
    anclado a la densidad VERDADERA del cuerpo (= lo que un pozo real leería)."""
    y_top = BODY_DEPTH - BODY_RADIUS
    y_bot = BODY_DEPTH + BODY_RADIUS
    anchor_density = BASE_DENSITY + DELTA_RHO
    return np.array([[BODY_X, BODY_Z, y_top, y_bot, anchor_density]], dtype=np.float64)


# ══════════════════════════════════════════════════════════════════════════════
#  Orquestación
# ══════════════════════════════════════════════════════════════════════════════
def run() -> dict:
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    sensors, g_obs, sigma_g = build_survey(rng)
    anchor = build_anchor()

    peak_mgal = float(np.max(np.abs(g_obs))) / 1e-5
    print(f"\nSurvey: {sensors.shape[0]} estaciones sobre {SURVEY_L/1000:.0f} km "
          f"(espaciado ~{SURVEY_L/(N_SIDE-1):.0f} m)")
    print(f"Cuerpo verdadero: esfera r={BODY_RADIUS:.0f} m, centroide {BODY_DEPTH:.0f} m, "
          f"Δρ={DELTA_RHO:+.2f} t/m³")
    print(f"Anomalía pico ≈ {peak_mgal:.3f} mGal | ruido {NOISE_MGAL} mGal "
          f"(SNR pico ≈ {peak_mgal/NOISE_MGAL:.0f})")

    print("\n[A] unconstrained (auto naïf: L2 · malla profunda) ...")
    rho_a, mf_a, grid_a, meta_a = invert(
        sensors, g_obs, sigma_g, ny=NY_DEEP, regularization_norm="L2")
    ma = measure(rho_a, grid_a, ny=NY_DEEP)
    ma.update(misfit_percent=round(mf_a, 3), mesh_depth_m=NY_DEEP * BLOCK,
              n_sat_upper=meta_a.get("n_sat_upper"))
    print(f"   z-error = {ma['z_error_m']} m | prof recuperada = {ma['recovered_depth_m']} m "
          f"(verdad {ma['true_depth_m']} m) | saturación piso = {ma['floor_saturation_frac']}")

    # ── BLINDAJE 2: ¿se exhibe la enfermedad? (chequeo ANTES de medir la cura) ──
    disease_present = (ma["z_error_m"] is not None
                       and ma["z_error_m"] >= DISEASE_Z_THRESHOLD_M)
    print(f"\n   ⇒ DISEASE_PRESENT = {disease_present}  "
          f"(z-error {ma['z_error_m']} m {'≥' if disease_present else '<'} "
          f"umbral {DISEASE_Z_THRESHOLD_M:.0f} m)")
    if not disease_present:
        print("   ⚠ El caso NO reproduce la enfermedad de z. La cura medida abajo NO es "
              "válida — hay que rediseñar el caso (más profundo / disperso / malla más "
              "profunda), no maquillar.")

    print("\n[B] +guardrails (compacto · malla capada a prof. resoluble) ...")
    rho_b, mf_b, grid_b, _ = invert(
        sensors, g_obs, sigma_g, ny=NY_CAP, regularization_norm="compact")
    mb = measure(rho_b, grid_b, ny=NY_CAP)
    mb.update(misfit_percent=round(mf_b, 3), mesh_depth_m=NY_CAP * BLOCK)
    print(f"   z-error = {mb['z_error_m']} m | prof recuperada = {mb['recovered_depth_m']} m")

    print("\n[C] +1 ancla dura (B + sondaje en el cuerpo verdadero) ...")
    rho_c, mf_c, grid_c, meta_c = invert(
        sensors, g_obs, sigma_g, ny=NY_CAP, regularization_norm="compact",
        boreholes=anchor, anchor_mode="hard")
    mc = measure(rho_c, grid_c, ny=NY_CAP)
    mc.update(misfit_percent=round(mf_c, 3), mesh_depth_m=NY_CAP * BLOCK,
              n_anchored_voxels=meta_c.get("n_anchored_voxels"))
    print(f"   z-error = {mc['z_error_m']} m | prof recuperada = {mc['recovered_depth_m']} m")

    def _delta(a, b):
        za, zb = a.get("z_error_m"), b.get("z_error_m")
        return None if (za is None or zb is None) else round(za - zb, 1)

    report = {
        "case": "SINTÉTICO — ambigüedad de z en régimen LdM (cuerpo profundo + cobertura dispersa)",
        "blindajes": {
            "no_inverse_crime": ("dato generado por gravedad analítica de esfera (forma cerrada, "
                                 "sin malla); inversión con kernel Nagy+masa-puntual sobre malla "
                                 f"de {BLOCK:.0f} m + ruido {NOISE_MGAL} mGal."),
            "disease_must_show": (f"unconstrained z-error debe ser ≥ {DISEASE_Z_THRESHOLD_M:.0f} m; "
                                  f"medido = {ma['z_error_m']} m ⇒ DISEASE_PRESENT={disease_present}."),
        },
        "prereg": PREREG,
        "disease_present": disease_present,
        "ground_truth": {
            "body_xz_m": [BODY_X, BODY_Z], "centroid_depth_m": BODY_DEPTH,
            "radius_m": BODY_RADIUS, "delta_rho_t_m3": DELTA_RHO,
            "true_density_t_m3": round(BASE_DENSITY + DELTA_RHO, 3),
        },
        "survey": {"n_stations": int(sensors.shape[0]), "extent_m": SURVEY_L,
                   "spacing_m": round(SURVEY_L / (N_SIDE - 1), 1),
                   "peak_anomaly_mgal": round(peak_mgal, 3), "noise_mgal": NOISE_MGAL},
        "config": {"block_m": BLOCK, "nx": NX, "nz": NZ,
                   "ny_deep": NY_DEEP, "ny_cap": NY_CAP,
                   "density_bounds": [DENSITY_MIN, DENSITY_MAX], "depth_beta": DEPTH_BETA},
        "results": {
            "A_unconstrained": ma,
            "B_guardrails": mb,
            "C_anchor": mc,
        },
        "deltas": {
            "guardrails_gain_A_to_B_m": _delta(ma, mb),
            "anchor_gain_B_to_C_m": _delta(mb, mc),
            "total_gain_A_to_C_m": _delta(ma, mc),
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = render_table(report)
    return report


def render_table(report: dict) -> str:
    r = report["results"]
    rows = [
        ("unconstrained (auto naïf)", r["A_unconstrained"]),
        ("+guardrails (setup sano)", r["B_guardrails"]),
        ("+1 ancla dura", r["C_anchor"]),
    ]
    h = ("| Configuración | z-error | prof recuperada | err horiz | sat. piso | misfit |\n"
         "|---------------|---------|-----------------|-----------|-----------|--------|")
    lines = [h]

    def _m(v, suf="m"):
        return "—" if v is None else f"{v:.1f}{suf}"
    for name, d in rows:
        lines.append(
            f"| {name} | {_m(d.get('z_error_m'))} | {_m(d.get('recovered_depth_m'))} | "
            f"{_m(d.get('horizontal_error_m'))} | {d.get('floor_saturation_frac')} | "
            f"{d.get('misfit_percent')}% |"
        )
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 80)
    print("PRE-REGISTRO (escrito ANTES de correr — no auto-cumplido)")
    print("=" * 80)
    for k, v in PREREG.items():
        print(f"  {k}: {v}")
    print(f"  umbral enfermedad: z-error ≥ {DISEASE_Z_THRESHOLD_M:.0f} m")

    report = run()

    print("\n" + "=" * 80)
    print("SINTÉTICO — VALOR DEL ANCLA CUANDO z SÍ ESTÁ MAL")
    print("=" * 80)
    print(f"\nProfundidad verdadera del centroide: {BODY_DEPTH:.0f} m")
    print(f"Enfermedad reproducida: {'SÍ' if report['disease_present'] else 'NO (caso inválido)'}")
    print("\n" + report["table_markdown"])
    d = report["deltas"]
    print(f"\nGanancia de guardrails (A→B): {d['guardrails_gain_A_to_B_m']} m")
    print(f"Ganancia de 1 ancla (B→C):    {d['anchor_gain_B_to_C_m']} m")
    print(f"Ganancia total (A→C):         {d['total_gain_A_to_C_m']} m")
    print(f"\nTiempo: {report['elapsed_s']}s")

    out = Path(__file__).resolve().parent / "synthetic_depth_ambiguity_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
