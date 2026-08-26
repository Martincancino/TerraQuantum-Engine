"""
FASE 18 — El experimento que cierra la rotación de 90° (ACAD-1).

Esta fase MIDE; la Fase 19 corrige. No toca una sola línea de producción.

────────────────────────────────────────────────────────────────────────────
EL DEFECTO, EN UNA LÍNEA
────────────────────────────────────────────────────────────────────────────
La INGESTA guarda el easting en el slot ``x_m`` y el northing en ``z_m``
(``services/gravity_import_service.py:131`` — *"Internal convention: x_m slot =
east/lon, z_m slot = north/lat"*; ``:350`` para UTM). El MOTOR MAGNÉTICO
documenta lo contrario (``exploration/magnetometry.py:31`` — *"x=Norte,
z=Este"*) y construye su vector de campo como
``f̂ = (cos I·cos D, sin I, cos I·sin D)`` con ``# x = Norte`` en la componente
0 (``magnetometry.py:92-97``). El empalme (``geophysics_service.py:2107``)
copia ``[o.x_m, o.y_m, o.z_m]`` **sin permutar**.

Gravimetría es invariante (sólo usa la componente vertical del prisma de Nagy,
simétrica bajo x↔z), así que el defecto es EXCLUSIVAMENTE magnético.

────────────────────────────────────────────────────────────────────────────
QUÉ MIDE ESTE SCRIPT
────────────────────────────────────────────────────────────────────────────
PARTE A — Mecanismo exacto, sin inversión. Compara tres cosas sobre la misma
  geometría: (1) una referencia analítica INDEPENDIENTE escrita en coordenadas
  geográficas explícitas (Norte, Este, Abajo), que no llama a
  ``field_unit_vector``; (2) el motor de producción alimentado con la
  convención que DOCUMENTA (col0=Norte), que es la que arman los harness de
  DO-27 y Raglan; (3) el motor alimentado con la convención que el IMPORTADOR
  realmente entrega (col0=Este). Ajusta después qué par (I', D') reproduce
  exactamente la salida corrupta.

PARTE B — Camino de producción COMPLETO: CSV con cabeceras en español →
  ``import_gravity_csv_v1(data_kind="magnetic")`` → ``auto_grid`` →
  ``GeophysicsInvertInput`` → ``run_magnetic_inversion``. Dos brazos: el
  código tal cual está, y un brazo de control con ``field_unit_vector``
  parcheado a la convención del dato. El parche es un INSTRUMENTO DE MEDIDA,
  no un arreglo: no se escribe en producción.

PARTE C — Reversibilidad. Prueba que la corrección propuesta para la Fase 19
  es un re-etiquetado exacto, de modo que los benchmarks DO-27 y Raglan
  conservan sus números si se voltean sus harness en el mismo cambio.

Uso:
    py -3.14 scripts/validation/fase18_axis_convention_experiment.py [--part A|B|C|all]

Salida: ``scripts/validation/fase18_axis_convention_report.json``
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from exploration.magnetometry import MagnetometryForward  # noqa: E402

REPORT_PATH = Path(__file__).with_name("fase18_axis_convention_report.json")

# ── Sitios. Chile = defaults de producción (geophysics_schema.py:577-586).
#    Los dos árticos son el IGRF REAL de los benchmarks, leído de sus reportes.
SITES = [
    ("chile", -30.0, 2.0,
     "defaults de producción (schemas/geophysics_schema.py:577-586)"),
    ("do27_artico", 83.8, 25.4,
     "IGRF real DO-27 (scripts/validation/do27_validation_report.json)"),
    ("raglan_artico", 83.0, -32.0,
     "IGRF real Raglan (scripts/validation/raglan_validation_report.json)"),
    ("declinacion_45", -30.0, 45.0,
     "DISCRIMINADOR: si el defecto es una REFLEXIÓN sobre el azimut 45°, aquí "
     "el efecto es EXACTAMENTE cero; si fuera una rotación de 90°, no lo sería"),
]

B0_NT = 23500.0


# ──────────────────────────────────────────────────────────────────────────────
# Referencia independiente: el dipolo TMI escrito en coordenadas GEOGRÁFICAS
# ──────────────────────────────────────────────────────────────────────────────
def f_hat_geographic(inclination_deg: float, declination_deg: float) -> np.ndarray:
    """f̂ en el marco (Norte, Este, Abajo).

    Implementación DELIBERADAMENTE independiente de
    ``exploration.magnetometry.field_unit_vector``: si ésta llamara a aquélla el
    experimento sería tautológico, que es justo el defecto que la Fase 17
    encontró en 7 tests del repositorio.
    """
    incl = math.radians(float(inclination_deg))
    decl = math.radians(float(declination_deg))
    return np.array([
        math.cos(incl) * math.cos(decl),   # Norte
        math.cos(incl) * math.sin(decl),   # Este
        math.sin(incl),                    # Abajo (+)
    ], dtype=np.float64)


def truth_tmi(st_n, st_e, body_n, body_e, body_depth,
              inclination_deg, declination_deg, kappa, volume_m3):
    """Anomalía TMI de un dipolo inducido, en coordenadas geográficas.

    ΔT = κ·(B0·V/4π)·[3(f̂·r̂)² − 1]/r³   (Blakely 1995, cap. 5; μ0 cancela al
    proyectar sobre el campo ambiente). Sensores en superficie (profundidad 0).
    """
    f = f_hat_geographic(inclination_deg, declination_deg)
    d_n = np.asarray(body_n, dtype=float) - np.asarray(st_n, dtype=float)
    d_e = np.asarray(body_e, dtype=float) - np.asarray(st_e, dtype=float)
    d_d = float(body_depth) - 0.0
    r2 = d_n ** 2 + d_e ** 2 + d_d ** 2
    f_dot_r = f[0] * d_n + f[1] * d_e + f[2] * d_d
    prefactor = B0_NT * float(volume_m3) / (4.0 * math.pi)
    return float(kappa) * prefactor * (3.0 * f_dot_r ** 2 - r2) / r2 ** 2.5


def engine_tmi(st_n, st_e, body_n, body_e, body_depth,
               inclination_deg, declination_deg, assembly, kappa, cell_m,
               f_hat_override=None):
    """TMI con el MOTOR DE PRODUCCIÓN, ensamblando las coordenadas de dos maneras.

    ``assembly='motor'``      → col0=Norte, col2=Este. Es la convención que
      ``magnetometry.py:31`` DOCUMENTA y la que arman a mano los harness de
      DO-27 (``ingest_do27.py:100``) y Raglan (``raglan_harness.py:104``).
    ``assembly='produccion'`` → col0=Este, col2=Norte. Es lo que el importador
      entrega de verdad, y lo que ``geophysics_service.py:2107`` copia sin tocar.

    Sensores y vóxeles se ensamblan SIEMPRE con el mismo criterio: la geometría
    relativa queda internamente consistente en los dos brazos. Lo único que
    cambia entre ellos es qué eje geográfico cree el motor que es el Norte.
    """
    fwd = MagnetometryForward(
        dx=cell_m, dy=cell_m, dz=cell_m,
        cutoff_radius=1e9,                       # sin recorte: geometría completa
        inclination_deg=inclination_deg,
        declination_deg=declination_deg,
        field_intensity_nt=B0_NT,
        near_field_mode="dipole",
    )
    if f_hat_override is not None:
        fwd.f_hat = np.asarray(f_hat_override, dtype=np.float64)

    st_n = np.asarray(st_n, dtype=float)
    st_e = np.asarray(st_e, dtype=float)
    zeros = np.zeros_like(st_n)
    if assembly == "motor":
        sensors = np.column_stack([st_n, zeros, st_e])
        vox = (np.array([body_n]), np.array([body_depth]), np.array([body_e]))
    elif assembly == "produccion":
        sensors = np.column_stack([st_e, zeros, st_n])
        vox = (np.array([body_e]), np.array([body_depth]), np.array([body_n]))
    else:
        raise ValueError(f"assembly desconocido: {assembly!r}")

    kernel = fwd.build_sparse_kernel(vox[0], vox[1], vox[2], sensors)
    return np.asarray(kernel.dot(np.array([float(kappa)]))).ravel()


def azimuth_max_min(values, st_n, st_e):
    """Azimut geográfico (0°=Norte, 90°=Este) del vector min→max del mapa TMI.

    OJO: se evalúa sobre una malla discreta, así que el resultado está
    CUANTIZADO a las direcciones que la malla permite. Es el número que pide el
    plan, pero el número exacto es ``fit_field_angles``.
    """
    values = np.asarray(values, dtype=float)
    i_max, i_min = int(np.argmax(values)), int(np.argmin(values))
    d_n = float(st_n[i_max] - st_n[i_min])
    d_e = float(st_e[i_max] - st_e[i_min])
    if d_n == 0.0 and d_e == 0.0:
        return None
    return float(math.degrees(math.atan2(d_e, d_n)) % 360.0)


def _wrap180(angle: float) -> float:
    return float(((angle + 180.0) % 360.0) - 180.0)


def fit_field_angles(target, st_n, st_e, body_n, body_e, body_depth,
                     kappa, volume_m3, true_inclination):
    """Ajusta el par (I', D') cuyo mapa VERDADERO reproduce ``target``.

    El dipolo sólo ve (f̂·r̂)², así que (I, D) y (−I, D+180) dan el MISMO mapa.
    Se canonicaliza al ramal con el signo de inclinación del sitio real, que es
    el único con sentido físico para ese hemisferio.
    """
    def rms(incl, decl):
        model = truth_tmi(st_n, st_e, body_n, body_e, body_depth,
                          incl, decl, kappa, volume_m3)
        return float(np.sqrt(np.mean((model - target) ** 2)))

    # Semilla por barrido grueso de 1°: el residuo tiene dos mínimos globales
    # (los dos ramales ±f̂) y el descenso local solo desde uno de ellos.
    best_err, best_i, best_d = float("inf"), 0.0, 0.0
    for incl in np.arange(-90.0, 90.001, 1.0):
        for decl in np.arange(-180.0, 180.0, 1.0):
            err = rms(incl, decl)
            if err < best_err:
                best_err, best_i, best_d = err, float(incl), float(decl)

    # Refinamiento local. A latitud ártica cos I ≈ 0,1 y el residuo es CASI PLANO
    # en D: un descenso por retícula con paso fijo se queda corto (medido: 0,28°
    # de sesgo en DO-27). Nelder-Mead sí baja hasta el mínimo real.
    from scipy.optimize import minimize
    opt = minimize(
        lambda v: rms(float(np.clip(v[0], -90.0, 90.0)), float(v[1])),
        x0=np.array([best_i, best_d], dtype=float),
        method="Nelder-Mead",
        options={"xatol": 1e-9, "fatol": 1e-18, "maxiter": 20000, "maxfev": 20000},
    )
    if float(opt.fun) < best_err:
        best_err = float(opt.fun)
        best_i = float(np.clip(opt.x[0], -90.0, 90.0))
        best_d = float(opt.x[1])

    if (best_i < 0.0) != (float(true_inclination) < 0.0):
        best_i, best_d = -best_i, _wrap180(best_d + 180.0)
    return best_i, _wrap180(best_d), best_err


# ──────────────────────────────────────────────────────────────────────────────
# PARTE A — el mecanismo, exacto y sin inversión
# ──────────────────────────────────────────────────────────────────────────────
def part_a(cell_m=50.0, kappa=0.05, n_side=21, spacing=50.0, depth=200.0):
    volume = cell_m ** 3
    axis = (np.arange(n_side) - (n_side - 1) / 2.0) * spacing
    grid_n, grid_e = np.meshgrid(axis, axis, indexing="ij")
    st_n, st_e = grid_n.ravel(), grid_e.ravel()

    # Dos posiciones del cuerpo. La CENTRADA es simétrica bajo la reflexión
    # x↔z, así que por sí sola no distingue «error de declinación» de «espejo
    # geométrico»; la DESCENTRADA sí, y es el control que lo decide.
    placements = [("centrado", 0.0, 0.0), ("descentrado", 250.0, -150.0)]

    rows = []
    for site, incl, decl, note in SITES:
        for place, body_n, body_e in placements:
            truth = truth_tmi(st_n, st_e, body_n, body_e, depth,
                              incl, decl, kappa, volume)
            motor = engine_tmi(st_n, st_e, body_n, body_e, depth,
                               incl, decl, "motor", kappa, cell_m)
            prod = engine_tmi(st_n, st_e, body_n, body_e, depth,
                              incl, decl, "produccion", kappa, cell_m)

            ptp = float(np.ptp(truth))
            rms_truth = float(np.sqrt(np.mean(truth ** 2)))
            fit_i, fit_d, fit_rms = fit_field_angles(
                prod, st_n, st_e, body_n, body_e, depth, kappa, volume, incl)

            f_true = f_hat_geographic(incl, decl)
            # f̂ que el motor aplica DE HECHO, reexpresado en el marco geográfico:
            # la componente 0 (que el motor cree Norte) multiplica el easting.
            f_prod_geo = np.array([f_true[1], f_true[0], f_true[2]])

            rows.append({
                "site": site,
                "placement": place,
                "inclination_deg": incl,
                "declination_deg": decl,
                "note": note,
                "body_north_m": body_n,
                "body_east_m": body_e,
                # Control de que la referencia independiente y el motor coinciden
                # cuando al motor se le da la convención que él documenta.
                "motor_vs_referencia_max_abs_nT": float(np.max(np.abs(motor - truth))),
                "truth_ptp_nT": ptp,
                "truth_rms_nT": rms_truth,
                "azimut_maxmin_verdad_deg": azimuth_max_min(truth, st_n, st_e),
                "azimut_maxmin_produccion_deg": azimuth_max_min(prod, st_n, st_e),
                "error_rms_nT": float(np.sqrt(np.mean((prod - truth) ** 2))),
                "error_rms_sobre_señal": float(
                    np.sqrt(np.mean((prod - truth) ** 2)) / rms_truth),
                "pearson_r": float(np.corrcoef(prod, truth)[0, 1]),
                # El número exacto: qué campo aplica producción en realidad.
                "I_efectiva_ajustada_deg": fit_i,
                "D_efectiva_ajustada_deg": fit_d,
                "D_efectiva_predicha_deg": _wrap180(90.0 - decl),
                "residuo_del_ajuste_nT": fit_rms,
                "rotacion_declinacion_deg": _wrap180(fit_d - decl),
                # Índice de ceguera: cuánto se mueve f̂ en el marco geográfico.
                "indice_ceguera": float(np.linalg.norm(f_prod_geo - f_true)),
                "indice_ceguera_forma_cerrada": float(
                    math.sqrt(2.0) * math.cos(math.radians(incl))
                    * abs(math.sin(math.radians(decl)) - math.cos(math.radians(decl)))),
            })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# PARTE B — el camino de producción completo, CSV → importador → motor
# ──────────────────────────────────────────────────────────────────────────────
def _write_magnetic_csv(path, st_e_utm, st_n_utm, tmi_nt, elevation=2500.0):
    """CSV con las cabeceras en español del corpus real (Este_UTM/Norte_UTM/...).

    Se escribe con los alias que el importador reconoce sin ayuda
    (``_UTM_EASTING_ALIASES`` / ``_UTM_NORTHING_ALIASES`` /
    ``MAGNETIC_COLUMN_PRIORITY``), para que el experimento pase por el mismo
    auto-mapeo que un usuario.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["estacion", "este_utm", "norte_utm", "cota_msnm", "tmi_nt"])
        for i, (e, n, t) in enumerate(zip(st_e_utm, st_n_utm, tmi_nt), start=1):
            writer.writerow([f"ST{i:04d}", f"{e:.3f}", f"{n:.3f}",
                             f"{elevation:.2f}", f"{t:.6f}"])


def part_b(site_keys=("chile", "do27_artico"), geometrias=None):
    """Corre :func:`_part_b_one_geometry` sobre DOS geometrías de survey.

    ``alargada_21x13`` (1200 × 720 m) es la que hace decisivo el tramo B1: con
    spans distintos, un intercambio de ejes saltaría a la vista. Pero le cuesta
    fit al brazo de CONTROL (misfit 22 % en vez de 1 %), y elegir sólo la
    geometría que favorece la conclusión sería exactamente el vicio que este
    repositorio persigue. Por eso se corre TAMBIÉN ``cuadrada_17x17``
    (960 × 960 m), donde el control ajusta al 1 % — y donde B1 no discrimina,
    que es la otra cara del mismo compromiso. Las dos se publican.
    """
    if geometrias is None:
        geometrias = [
            ("alargada_21x13", dict(n_east=21, n_north=13, nx=22, ny=10, nz=14)),
            ("cuadrada_17x17", dict(n_east=17, n_north=17, nx=20, ny=10, nz=20)),
        ]
    merged = {"b1_contrato_ingesta": [], "b2_dato": [], "b3_modelo": [],
              "configuracion": []}
    for nombre, kwargs in geometrias:
        one = _part_b_one_geometry(site_keys=site_keys, **kwargs)
        one["configuracion"]["geometria"] = nombre
        merged["configuracion"].append(one["configuracion"])
        for key in ("b1_contrato_ingesta", "b2_dato", "b3_modelo"):
            for row in one[key]:
                row["geometria"] = nombre
                merged[key].append(row)
    return merged


def _part_b_one_geometry(site_keys=("chile", "do27_artico"),
           n_east=21, n_north=13, spacing=60.0,
           depth=220.0, kappa=0.30, body_offset_n=120.0, body_offset_e=-90.0,
           utm_e0=380_000.0, utm_n0=7_400_000.0,
           nx=22, ny=10, nz=14, block=60):
    """El camino de producción COMPLETO, en tres tramos.

    B1 — CONTRATO DE LA INGESTA. Un CSV con cabeceras en español entra por
      ``import_gravity_csv_v1`` y se comprueba, número a número, en qué slot
      cae cada columna. La malla de estaciones es DELIBERADAMENTE asimétrica
      (21 × 13): si el importador confundiera los ejes, los spans (1200 m y
      720 m) saldrían intercambiados y el chequeo lo vería. Con malla cuadrada
      el defecto sería invisible — la misma lección que el gate de la Fase 19
      exige para el ZIP.

    B2 — EL DATO. ``sensor_coords`` se arma exactamente como en
      ``geophysics_service.py:2107`` a partir de las observaciones que el
      importador devolvió, y se corre el forward de producción. Se mide qué
      campo aplica de hecho el motor sobre datos que entraron por la puerta
      del usuario.

    B3 — EL MODELO. La inversión magnética de producción, dos brazos:
      ``produccion``      — el código tal como está hoy.
      ``convencion_dato`` — control con ``field_unit_vector`` parcheado a
        ``(cos I·sin D, sin I, cos I·cos D)``, que es f̂ escrito en la
        convención que la ingesta entrega. El parche es un INSTRUMENTO DE
        MEDIDA, no un arreglo: no se escribe en producción y se restaura
        siempre en un ``finally``.
    """
    import exploration.magnetometry as magmod
    from services.gravity_import_service import import_gravity_csv_v1
    from services.geophysics_service import run_magnetic_inversion
    from schemas.geophysics_schema import (
        GeophysicsInvertInput, GravityObservation,
    )

    original_field_unit_vector = magmod.field_unit_vector

    def patched_field_unit_vector(inclination_deg, declination_deg):
        incl = math.radians(float(inclination_deg))
        decl = math.radians(float(declination_deg))
        return np.array([
            math.cos(incl) * math.sin(decl),   # x = ESTE (convención del dato)
            math.sin(incl),                    # y = profundidad (+ abajo)
            math.cos(incl) * math.cos(decl),   # z = NORTE
        ], dtype=np.float64)

    axis_e = np.arange(n_east) * spacing
    axis_n = np.arange(n_north) * spacing
    grid_n, grid_e = np.meshgrid(axis_n, axis_e, indexing="ij")
    st_n, st_e = grid_n.ravel(), grid_e.ravel()
    body_n = float(axis_n.mean() + body_offset_n)
    body_e = float(axis_e.mean() + body_offset_e)

    # Cuerpo = cubo de 100 m representado por 8 dipolos de celda de 50 m.
    cell = 50.0
    volume = cell ** 3
    corners = [(body_n + dn, body_e + de, depth + dd)
               for dn in (-cell / 2, cell / 2)
               for de in (-cell / 2, cell / 2)
               for dd in (-cell / 2, cell / 2)]

    out = {"b1_contrato_ingesta": [], "b2_dato": [], "b3_modelo": [],
           "configuracion": {
               "estaciones": int(n_east * n_north),
               "malla_estaciones_ExN": [n_east, n_north],
               "spacing_m": spacing,
               "span_este_m": float(axis_e.max() - axis_e.min()),
               "span_norte_m": float(axis_n.max() - axis_n.min()),
               "cuerpo": "cubo de 100 m, 8 dipolos de celda 50 m",
               "kappa_si": kappa,
               "profundidad_m": depth,
               "malla_inversion_nx_ny_nz": [nx, ny, nz],
               "block_size_m": block,
               "nota_malla": (
                   "nx≠nz a propósito. La malla se DECLARA en vez de tomar el "
                   "auto_grid: con el auto_grid de este CSV (34×36×34 a 29 m) el "
                   "solver GPCG termina por (max_outer) en LOS DOS brazos, con "
                   "misfit 47–58 % y el pico pegado a 14,5 m de profundidad — no "
                   "discrimina nada. El endpoint acepta nx/ny/nz del paquete "
                   "(api/gravity_import_api.py:1731-1733), así que una malla "
                   "declarada sigue siendo el camino de producción."),
           }}

    tmpdir = Path(tempfile.mkdtemp(prefix="fase18_"))
    for site, incl, decl, _note in SITES:
        if site not in site_keys:
            continue

        truth = np.zeros_like(st_n)
        for (b_n, b_e, b_d) in corners:
            truth = truth + truth_tmi(st_n, st_e, b_n, b_e, b_d,
                                      incl, decl, kappa, volume)

        csv_path = tmpdir / f"fase18_{site}.csv"
        _write_magnetic_csv(csv_path, st_e + utm_e0, st_n + utm_n0, truth)

        imported = import_gravity_csv_v1(
            str(csv_path), strict=False, allow_g_raw=False, data_kind="magnetic")
        if str(imported.status).lower() not in ("ok", "success", "warning"):
            out["b1_contrato_ingesta"].append(
                {"site": site, "error": f"import status={imported.status}",
                 "errors": list(imported.errors)})
            continue

        obs = imported.observations
        got_x = np.array([o.x_m for o in obs])
        got_z = np.array([o.z_m for o in obs])
        # Lo que el CSV llevaba, normalizado al origen SW como hace el importador.
        esperado_este = (st_e + utm_e0) - float(np.min(st_e + utm_e0))
        esperado_norte = (st_n + utm_n0) - float(np.min(st_n + utm_n0))

        out["b1_contrato_ingesta"].append({
            "site": site,
            "n_observaciones": len(obs),
            "metodo_transformacion": (
                imported.coordinate_transform.method
                if imported.coordinate_transform else None),
            # El número: el slot x_m sigue al ESTE, no al Norte.
            "max_abs_x_m_menos_este_m": float(np.max(np.abs(got_x - esperado_este))),
            "max_abs_z_m_menos_norte_m": float(np.max(np.abs(got_z - esperado_norte))),
            "max_abs_x_m_menos_norte_m": float(np.max(np.abs(got_x - esperado_norte))),
            "span_x_m": float(np.ptp(got_x)),
            "span_z_m": float(np.ptp(got_z)),
            "span_este_csv_m": float(np.ptp(esperado_este)),
            "span_norte_csv_m": float(np.ptp(esperado_norte)),
            "veredicto": (
                "x_m = ESTE y z_m = NORTE"
                if float(np.max(np.abs(got_x - esperado_este))) < 1e-6
                else "el slot x_m NO es el este"),
        })

        # ── B2 — el dato, con el empalme literal de geophysics_service.py:2107 ──
        sensor_coords = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)
        body_x_local = (body_e + utm_e0) - float(np.min(st_e + utm_e0))
        body_z_local = (body_n + utm_n0) - float(np.min(st_n + utm_n0))

        fwd = MagnetometryForward(
            dx=cell, dy=cell, dz=cell, cutoff_radius=1e9,
            inclination_deg=incl, declination_deg=decl,
            field_intensity_nt=B0_NT, near_field_mode="dipole")
        pred = np.zeros(len(obs))
        for (b_n, b_e, b_d) in corners:
            v_x = np.array([(b_e + utm_e0) - float(np.min(st_e + utm_e0))])
            v_z = np.array([(b_n + utm_n0) - float(np.min(st_n + utm_n0))])
            v_y = np.array([b_d])
            pred = pred + np.asarray(
                fwd.build_sparse_kernel(v_x, v_y, v_z, sensor_coords)
                .dot(np.array([float(kappa)]))).ravel()

        fit_i, fit_d, fit_rms = fit_field_angles(
            pred, st_n, st_e, body_n, body_e, depth, kappa * 8.0, volume, incl)
        out["b2_dato"].append({
            "site": site,
            "inclination_deg": incl, "declination_deg": decl,
            "azimut_maxmin_verdad_deg": azimuth_max_min(truth, st_n, st_e),
            "azimut_maxmin_produccion_deg": azimuth_max_min(pred, st_n, st_e),
            "pearson_r": float(np.corrcoef(pred, truth)[0, 1]),
            "error_rms_sobre_senal": float(
                np.sqrt(np.mean((pred - truth) ** 2))
                / np.sqrt(np.mean(truth ** 2))),
            "I_efectiva_ajustada_deg": fit_i,
            "D_efectiva_ajustada_deg": fit_d,
            "D_efectiva_predicha_deg": _wrap180(90.0 - decl),
            "residuo_del_ajuste_nT": fit_rms,
            "senal_ptp_nT": float(np.ptp(truth)),
        })

        # ── B3 — el modelo ────────────────────────────────────────────────────
        # Réplica del ruteo magnético del endpoint (gravity_import_api.py:1745-1750).
        magnetic_nt = [float(o.g) for o in obs]
        observations = [GravityObservation(x_m=o.x_m, y_m=o.y_m, z_m=o.z_m, g=0.0)
                        for o in obs]
        params = GeophysicsInvertInput(
            depth=int(ny * block), nir=83, fe=79, region="norte_chile",
            nx=nx, ny=ny, nz=nz, block_size=block, cutoff_radius=2000.0,
            lambda_mag=0.0, alpha_spatial=1.0,
            observations=observations, magnetic_nt=magnetic_nt,
            inclination_deg=incl, declination_deg=decl,
            field_intensity_nt=B0_NT, susc_min=0.0, susc_max=1.0,
            enable_focusing=True,
        )

        for arm in ("produccion", "convencion_dato"):
            magmod.field_unit_vector = (
                patched_field_unit_vector if arm == "convencion_dato"
                else original_field_unit_vector)
            t0 = time.perf_counter()
            try:
                result = run_magnetic_inversion(params)
            except Exception as exc:   # pragma: no cover - diagnóstico
                out["b3_modelo"].append({"site": site, "arm": arm, "error": repr(exc)})
                continue
            finally:
                magmod.field_unit_vector = original_field_unit_vector
            elapsed = time.perf_counter() - t0

            voxels = result.get("voxels") or []
            if not voxels:
                out["b3_modelo"].append({
                    "site": site, "arm": arm, "error": "sin voxeles anomalos",
                    "misfit_error_percent": result.get("misfit_error_percent")})
                continue

            susc = np.array([float(v["susceptibility"]) for v in voxels])
            vox_x = np.array([float(v["x_m"]) for v in voxels])
            vox_y = np.array([float(v["y_m"]) for v in voxels])
            vox_z = np.array([float(v["z_m"]) for v in voxels])
            top = int(np.argmax(susc))
            weights = susc / susc.sum()

            def _errs(x, y, z):
                d_e = float(x) - body_x_local     # slot x_m = Este
                d_n = float(z) - body_z_local     # slot z_m = Norte
                return (float(math.hypot(d_e, d_n)), float(y) - depth,
                        float(math.degrees(math.atan2(d_e, d_n)) % 360.0))

            err_h, err_z, az = _errs(vox_x[top], vox_y[top], vox_z[top])
            err_hc, err_zc, az_c = _errs(float(vox_x @ weights),
                                         float(vox_y @ weights),
                                         float(vox_z @ weights))
            out["b3_modelo"].append({
                "site": site, "arm": arm,
                "inclination_deg": incl, "declination_deg": decl,
                "err_horizontal_pico_m": err_h,
                "err_profundidad_pico_m": err_z,
                "azimut_error_pico_deg": az,
                "err_horizontal_centroide_m": err_hc,
                "err_profundidad_centroide_m": err_zc,
                "azimut_error_centroide_deg": az_c,
                "susc_max_si": float(susc.max()),
                "n_voxeles_anomalos": len(voxels),
                "misfit_error_percent": result.get("misfit_error_percent"),
                "segundos": round(elapsed, 1),
            })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# PARTE C — la corrección de la Fase 19 es un re-etiquetado exacto
# ──────────────────────────────────────────────────────────────────────────────
def part_c(cell_m=50.0, kappa=0.05, n_side=15, spacing=70.0, depth=260.0):
    """¿Cuánto costaría a DO-27 y Raglan que la Fase 19 cambie f̂?

    Si el motor pasa a f̂ = (cos I·sin D, sin I, cos I·cos D) Y su harness pasa a
    ensamblar col0=Este, la configuración física es la misma re-etiquetada, así
    que el dato predicho debe ser IDÉNTICO. Esto es lo que permite prometer que
    los benchmarks conservan sus números.
    """
    volume = cell_m ** 3
    axis = (np.arange(n_side) - (n_side - 1) / 2.0) * spacing
    grid_n, grid_e = np.meshgrid(axis, axis, indexing="ij")
    st_n, st_e = grid_n.ravel(), grid_e.ravel()
    body_n, body_e = 210.0, -140.0

    rows = []
    for site, incl, decl, _note in SITES:
        incl_r, decl_r = math.radians(incl), math.radians(decl)
        f_data_convention = np.array([
            math.cos(incl_r) * math.sin(decl_r),   # x = Este
            math.sin(incl_r),
            math.cos(incl_r) * math.cos(decl_r),   # z = Norte
        ])
        hoy = engine_tmi(st_n, st_e, body_n, body_e, depth, incl, decl,
                         "motor", kappa, cell_m)
        fase19 = engine_tmi(st_n, st_e, body_n, body_e, depth, incl, decl,
                            "produccion", kappa, cell_m,
                            f_hat_override=f_data_convention)
        verdad = truth_tmi(st_n, st_e, body_n, body_e, depth, incl, decl,
                           kappa, volume)
        rows.append({
            "site": site,
            "harness_hoy_vs_fase19_max_abs_nT": float(np.max(np.abs(hoy - fase19))),
            "fase19_vs_referencia_max_abs_nT": float(np.max(np.abs(fase19 - verdad))),
            "señal_ptp_nT": float(np.ptp(verdad)),
        })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# PARTE D — MUTACIÓN. ¿El experimento falla si se rompe lo que dice defender?
# ──────────────────────────────────────────────────────────────────────────────
def part_d(cell_m=50.0, kappa=0.05, n_side=17, spacing=60.0, depth=230.0):
    """Cuatro mutaciones. Un experimento que sólo sabe decir «sí» no mide nada.

    M1 — QUITAR EL DEFECTO. Con f̂ escrito en la convención del dato, el brazo
      de producción debe reportar rotación 0° y coincidir con la referencia
      geográfica. Si el harness siguiera diciendo 86°, estaría midiéndose a sí
      mismo.
    M2 — REFLEXIÓN, NO ROTACIÓN. En D=45° la rotación medida debe ser
      exactamente 0. Si el harness dijera 90° ahí, el mecanismo sería una
      rotación y la forma cerrada D_ef = 90 − D estaría mal.
    M3 — ENSAMBLADO INCONSISTENTE. Permutando SÓLO los sensores y no los
      vóxeles, el resultado NO debe ser reproducible por ningún par (I', D').
      Es la mutación que puede matar la Parte A: si el ajustador encajara
      cualquier cosa a residuo cero, el «D_ef = 88,000° exacto» no probaría nada.
    M4 — EL DEFECTO ES SÓLO MAGNÉTICO. La misma permutación consistente sobre
      el forward GRAVIMÉTRICO no debe cambiar nada. Si la gravedad también se
      moviera, el diagnóstico estaría mal atribuido.
    """
    from exploration.gravimetry import GravimetryForward

    volume = cell_m ** 3
    axis = (np.arange(n_side) - (n_side - 1) / 2.0) * spacing
    grid_n, grid_e = np.meshgrid(axis, axis, indexing="ij")
    st_n, st_e = grid_n.ravel(), grid_e.ravel()
    body_n, body_e = 190.0, -130.0
    zeros = np.zeros_like(st_n)

    out = []

    # ── M1 ────────────────────────────────────────────────────────────────────
    for site, incl, decl, _n in SITES:
        incl_r, decl_r = math.radians(incl), math.radians(decl)
        f_dato = np.array([math.cos(incl_r) * math.sin(decl_r),
                           math.sin(incl_r),
                           math.cos(incl_r) * math.cos(decl_r)])
        sin_defecto = engine_tmi(st_n, st_e, body_n, body_e, depth, incl, decl,
                                 "produccion", kappa, cell_m,
                                 f_hat_override=f_dato)
        fit_i, fit_d, fit_rms = fit_field_angles(
            sin_defecto, st_n, st_e, body_n, body_e, depth, kappa, volume, incl)
        rot = _wrap180(fit_d - decl)
        out.append({
            "mutacion": "M1_defecto_quitado", "site": site,
            "rotacion_medida_deg": rot,
            "residuo_del_ajuste_nT": fit_rms,
            "esperado": "rotación 0°",
            "caza": bool(abs(rot) < 1e-3),
        })

    # ── M2 ────────────────────────────────────────────────────────────────────
    # Ya está en la Parte A como el sitio `declinacion_45`; aquí se aísla y se
    # contrasta con la predicción de la hipótesis RIVAL (rotación rígida de 90°).
    incl, decl = -30.0, 45.0
    verdad = truth_tmi(st_n, st_e, body_n, body_e, depth, incl, decl, kappa, volume)
    prod = engine_tmi(st_n, st_e, body_n, body_e, depth, incl, decl,
                      "produccion", kappa, cell_m)
    rival = truth_tmi(st_n, st_e, body_n, body_e, depth, incl, decl + 90.0,
                      kappa, volume)
    out.append({
        "mutacion": "M2_reflexion_no_rotacion", "site": "declinacion_45",
        "produccion_vs_verdad_max_abs_nT": float(np.max(np.abs(prod - verdad))),
        "hipotesis_rival_rotacion90_vs_verdad_max_abs_nT": float(np.max(np.abs(rival - verdad))),
        "senal_ptp_nT": float(np.ptp(verdad)),
        "esperado": "producción == verdad (0), y la hipótesis rival NO (≫0)",
        "caza": bool(np.max(np.abs(prod - verdad)) < 1e-9
                     and np.max(np.abs(rival - verdad)) > 0.1 * np.ptp(verdad)),
    })

    # ── M3 ────────────────────────────────────────────────────────────────────
    # Sensores permutados, vóxel NO: una geometría revuelta que ninguna (I', D')
    # puede explicar. Si el ajustador la explicara, la Parte A no probaría nada.
    for site, incl, decl, _n in SITES[:2]:
        fwd = MagnetometryForward(dx=cell_m, dy=cell_m, dz=cell_m,
                                  cutoff_radius=1e9, inclination_deg=incl,
                                  declination_deg=decl, field_intensity_nt=B0_NT,
                                  near_field_mode="dipole")
        sensores_permutados = np.column_stack([st_e, zeros, st_n])
        vox_sin_permutar = (np.array([body_n]), np.array([depth]), np.array([body_e]))
        revuelto = np.asarray(
            fwd.build_sparse_kernel(*vox_sin_permutar, sensores_permutados)
            .dot(np.array([kappa]))).ravel()
        _fi, _fd, fit_rms = fit_field_angles(
            revuelto, st_n, st_e, body_n, body_e, depth, kappa, volume, incl)
        ptp = float(np.ptp(revuelto))
        out.append({
            "mutacion": "M3_ensamblado_inconsistente", "site": site,
            "residuo_del_ajuste_nT": fit_rms,
            "residuo_relativo": fit_rms / ptp if ptp else None,
            "senal_ptp_nT": ptp,
            "esperado": "residuo ≫ 0: NINGÚN (I',D') lo reproduce",
            "caza": bool(ptp > 0 and fit_rms / ptp > 1e-3),
        })

    # ── M4 ────────────────────────────────────────────────────────────────────
    grav = GravimetryForward(dx=cell_m, dy=cell_m, dz=cell_m, cutoff_radius=1e9)
    g_motor = np.asarray(grav.build_sparse_kernel(
        np.array([body_n]), np.array([depth]), np.array([body_e]),
        np.column_stack([st_n, zeros, st_e])).dot(np.array([1.0]))).ravel()
    g_prod = np.asarray(grav.build_sparse_kernel(
        np.array([body_e]), np.array([depth]), np.array([body_n]),
        np.column_stack([st_e, zeros, st_n])).dot(np.array([1.0]))).ravel()
    denom = float(np.max(np.abs(g_motor))) or 1.0
    rel = float(np.max(np.abs(g_prod - g_motor))) / denom
    out.append({
        "mutacion": "M4_gravimetria_invariante", "site": "n/a",
        "max_abs_relativo": rel,
        "esperado": "≈0: la gravedad NO ve la permutación",
        "caza": bool(rel < 1e-10),
    })
    return out


def main():
    # La consola de Windows abre en cp1252 y el reporte lleva acentos y cajas.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", default="all", choices=["A", "B", "C", "D", "all"])
    args = parser.parse_args()

    # Correr una parte suelta NO debe borrar las otras: el reporte se funde.
    report = {}
    if REPORT_PATH.exists():
        try:
            report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        except Exception:
            report = {}
    report.update({"fase": 18, "defecto": "ACAD-1",
                   "generado": time.strftime("%Y-%m-%d %H:%M:%S")})

    if args.part in ("A", "all"):
        print("── PARTE A — mecanismo exacto ─────────────────────────────────")
        report["parte_a"] = part_a()
        for r in report["parte_a"]:
            print(f"  {r['site']:<16} {r['placement']:<12} "
                  f"D={r['declination_deg']:>6.1f}° → D_ef={r['D_efectiva_ajustada_deg']:>8.3f}° "
                  f"(pred {r['D_efectiva_predicha_deg']:>7.2f}°)  "
                  f"rot={r['rotacion_declinacion_deg']:>8.3f}°  "
                  f"r={r['pearson_r']:>7.4f}  ceguera={r['indice_ceguera']:.4f}")

    if args.part in ("C", "all"):
        print("── PARTE C — reversibilidad ───────────────────────────────────")
        report["parte_c"] = part_c()
        for r in report["parte_c"]:
            print(f"  {r['site']:<16} harness_hoy vs fase19: "
                  f"{r['harness_hoy_vs_fase19_max_abs_nT']:.3e} nT   "
                  f"(señal {r['señal_ptp_nT']:.3f} nT)")

    if args.part in ("B", "all"):
        print("── PARTE B — camino de producción completo ────────────────────")
        parte_b = part_b()
        report["parte_b"] = parte_b
        print("  B1 — contrato de la ingesta")
        for r in parte_b["b1_contrato_ingesta"]:
            if "error" in r:
                print(f"     {r['site']:<16} ERROR {r['error']}")
                continue
            print(f"     {r['geometria']:<16} {r['site']:<14} |x_m−Este|={r['max_abs_x_m_menos_este_m']:.2e} m  "
                  f"|x_m−Norte|={r['max_abs_x_m_menos_norte_m']:.1f} m  "
                  f"span(x,z)=({r['span_x_m']:.0f},{r['span_z_m']:.0f}) "
                  f"CSV(E,N)=({r['span_este_csv_m']:.0f},{r['span_norte_csv_m']:.0f})  "
                  f"→ {r['veredicto']}")
        print("  B2 — el dato que sale del empalme")
        for r in parte_b["b2_dato"]:
            print(f"     {r['geometria']:<16} {r['site']:<14} D={r['declination_deg']:>6.1f}° → "
                  f"D_ef={r['D_efectiva_ajustada_deg']:>8.3f}° "
                  f"(pred {r['D_efectiva_predicha_deg']:>7.2f}°)  "
                  f"r={r['pearson_r']:>7.4f}  "
                  f"err/señal={r['error_rms_sobre_senal']:.4f}  "
                  f"azV={r['azimut_maxmin_verdad_deg']:.1f}° azP={r['azimut_maxmin_produccion_deg']:.1f}°")
        print("  B3 — el modelo recuperado")
        for r in parte_b["b3_modelo"]:
            if "error" in r:
                print(f"     {r.get('site'):<16} {r.get('arm','-'):<16} ERROR {r['error']}")
                continue
            print(f"     {r['geometria']:<16} {r['site']:<14} {r['arm']:<16} "
                  f"err_horiz={r['err_horizontal_pico_m']:>7.1f} m  "
                  f"err_prof={r['err_profundidad_pico_m']:>7.1f} m  "
                  f"misfit={r['misfit_error_percent']:>6.2f}%  "
                  f"κmax={r['susc_max_si']:.4f}  n={r['n_voxeles_anomalos']}")

    if args.part in ("D", "all"):
        print("── PARTE D — mutación ─────────────────────────────────────────")
        report["parte_d"] = part_d()
        cazadas = sum(1 for r in report["parte_d"] if r["caza"])
        for r in report["parte_d"]:
            print(f"     {'CAZA' if r['caza'] else 'NO CAZA':<8} {r['mutacion']:<30} "
                  f"{r['site']:<16} esperado: {r['esperado']}")
        print(f"     MUTACIÓN: {cazadas}/{len(report['parte_d'])}")

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print(f"\nReporte → {REPORT_PATH}")


if __name__ == "__main__":
    main()
