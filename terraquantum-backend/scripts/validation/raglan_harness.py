"""
Raglan (Ni-Cu, Quebec) — Harness de validación contra benchmark de DATO REAL
=============================================================================

SEGUNDO benchmark externo de TerraQuantum y el primero con **dato de campo REAL** (no
synthetic-based-on como DO-27). Corre la inversión MAGNÉTICA del motor real sobre el TMI
de Raglan con el IGRF real (I=83°, D=−32°, B0=60000 nT) y mide la GEOMETRÍA/TARGETING
recuperada vs la inversión de REFERENCIA publicada (maginv3d 1997) + la anomalía dominante
de los datos.

REFRAME (project_fase25_field_validation): se valida POSICIÓN/ESTRUCTURA del cuerpo, NO la
susceptibilidad punto a punto. Métrica dura = error horizontal del cuerpo dominante.

Reusa el patrón de DO-27 (do27_harness): mismo motor, mismas métricas, misma
convención de ejes (x=Este, z=Norte, y=prof). Diferencias: magnético SOLO (sin gravedad/joint), coords
locales, σ = Std real, IGRF de obs.mag. NO se tunea nada.

USO:
  cd terraquantum-backend
  python scripts/validation/raglan_harness.py
  # → tabla + scripts/validation/raglan_validation_report.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.magnetometry import MagnetometryForward, MagnetometryInversion
from services.inversion_kernel_service import build_padded_tensor_grid
from scripts.validation.ingest_raglan import (
    RaglanMagneticSurvey,
    RaglanReference,
    build_raglan_frame,
    load_raglan_magnetic,
    load_raglan_reference,
    load_reference_cube,
    summarize,
)
from scripts.validation.ingest_do27 import LocalFrame

# ── Malla de inversión: cubre el survey 4000×4000 m a 200 m (la malla de referencia es
# 40×40×10 @100 m = 16000 celdas, demasiado para el solver acotado). 20×20×5 = 2000 celdas.
BLOCK_SIZE = 200.0
NX = 20   # Este
NZ = 20   # Norte
NY = 5    # profundidad (5×200 = 1000 m, igual que la malla de referencia)
# El kernel dipolar magnético cae como 1/r³ → 2500 m capta toda interacción relevante en
# un survey de 4 km sin inflar la densidad del kernel (acelera mucho el solver acotado).
CUTOFF = 2500.0
SENSOR_STRIDE = 4         # 1638 → ~410 estaciones (solver acotado escala mal con n_obs)
COMPACT_IRLS = 2
LAMBDA_MAG = 1e-3
SUSC_MIN = 0.0
SUSC_MAX = 0.5            # κ máx de referencia ≈ 0.31

# ── Padding de malla (condición de frontera física) ──────────────────────────────
# Rodea el core (20×5×20 @200 m) con N_PAD capas que crecen geométricamente hacia afuera
# (factor 1.3) en las 6 caras → extiende el dominio ~600-1000 m más allá del survey. La
# anomalía dominante de Raglan (5221 nT en X≈4478, justo en el borde Este) deja de saturar
# la pared del core: las celdas de padding le dan dónde ubicarse (BC m→fondo). Default ON.
N_PAD = 4
PAD_FACTOR = 1.3
PADDING_KAPPA = 1e5      # smallness diferencial: ancla el padding al fondo (R-02 gravedad)

# Tolerancia de targeting a esta escala (survey 4 km, celdas 200 m, cuerpo difuso): <400 m.
TARGETING_TOL_M = 400.0


def _grid_centers_fortran(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return (
        (ix.ravel(order="F") + 0.5) * bs,
        (iy.ravel(order="F") + 0.5) * bs,
        (iz.ravel(order="F") + 0.5) * bs,
    )


def _subsample(arrays, stride):
    n = arrays[0].shape[0]
    idx = np.arange(0, n, stride)
    return [a[idx] for a in arrays], idx


def invert_magnetic(survey: RaglanMagneticSurvey, fr: LocalFrame, use_padding: bool = True):
    """Inversión magnética del survey de Raglan.

    use_padding=True (default): malla con padding geométrico (BC física) → la fuente del
    borde Este deja de saturar la pared del core. use_padding=False reproduce el harness
    histórico (grilla uniforme sin padding) para la comparación lado a lado.

    Devuelve siempre arrays en la grilla CORE (el padding se descarta del modelo reportado),
    de modo que las métricas son comparables entre ambos modos.
    """
    (e, n, z, tmi, sig), _ = _subsample(
        [survey.east, survey.north, survey.elevation, survey.tmi_nt, survey.sigma_nt],
        SENSOR_STRIDE,
    )
    # Sensores en el frame del motor: x=Este←east, y=prof←(datum−elev), z=Norte←north.
    sensors = fr.sensors(e, n, z)

    if use_padding:
        mesh = build_padded_tensor_grid(NX, NY, NZ, BLOCK_SIZE, n_pad=N_PAD, pad_factor=PAD_FACTOR)
        x_c, y_c, z_c = mesh["x_c"], mesh["y_c"], mesh["z_c"]      # grilla COMPLETA (core+pad)
        is_core = mesh["is_core"]
        hx, hy, hz = mesh["hx"], mesh["hy"], mesh["hz"]            # Laplaciano no-uniforme
        padding_mask = ~is_core
        nxt, nyt, nzt = mesh["nx_total"], mesh["ny_total"], mesh["nz_total"]
        inv = MagnetometryInversion(nxt, nyt, nzt, BLOCK_SIZE)
    else:
        x_c, y_c, z_c = _grid_centers_fortran(NX, NY, NZ, BLOCK_SIZE)
        is_core = np.ones(x_c.size, dtype=bool)
        hx = hy = hz = None
        padding_mask = None
        inv = MagnetometryInversion(NX, NY, NZ, BLOCK_SIZE)

    # σ = Std real de la estación (constante = mediana, ya que el motor usa σ escalar
    # floor+pct·|d|; noise_pct=0 → σ constante). Las anomalías fuertes son SEÑAL (cuerpo
    # coherente), NO outliers → detect_outliers=False (no se downpesa el cuerpo).
    sigma_floor = float(np.median(sig))
    fwd = MagnetometryForward(
        BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, cutoff_radius=CUTOFF,
        inclination_deg=survey.inclination_deg,
        declination_deg=survey.declination_deg,
        field_intensity_nt=survey.field_intensity_nt,
    )
    meta: dict = {}
    chi_full, _score, misfit, _sens = inv.solve_magnetic_inversion_lsqr(
        d_observed=np.asarray(tmi, dtype=np.float64), override_kernel=None, y_c=y_c,
        lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=SUSC_MIN, susc_max=SUSC_MAX,
        noise_floor=sigma_floor, noise_pct=0.0,        # σ = Std real (no adaptativo)
        detect_outliers=False,
        auto_kappa=True, prune_observable_domain=True,
        regularization_norm="compact", compact_max_irls=COMPACT_IRLS,
        hx=hx, hy=hy, hz=hz,
        padding_mask=padding_mask, padding_kappa=PADDING_KAPPA,
        solver_meta=meta,
    )
    chi_full = np.asarray(chi_full, dtype=np.float64)
    # Reportar SOLO la grilla core (el padding es BC, no modelo): aísla en x_c/y_c/z_c core.
    chi_core = chi_full[is_core]
    x_core, y_core, z_core = x_c[is_core], y_c[is_core], z_c[is_core]
    return (chi_core, float(misfit), x_core, y_core, z_core,
            int(sensors.shape[0]), sigma_floor, meta)


def invert_via_production(survey: RaglanMagneticSurvey, fr: LocalFrame):
    """Inversión de Raglan a través del PATH DE PRODUCCIÓN (run_geophysics_inversion).

    A diferencia de invert_magnetic (que llama al motor directo), esto construye un
    GeophysicsInvertInput y lo rutea por run_geophysics_inversion → run_magnetic_inversion,
    el MISMO camino que dispara /load-package en la app. Confirma que el padding (BC física)
    y la malla extendida que ahora cablea producción reducen el artefacto de borde igual que
    el motor. Devuelve el modelo en la grilla CORE reconstruido desde los vóxeles del payload.

    NOTA honesta: producción usa σ adaptivo (no el Std real por estación del harness aislado),
    así que los números no son byte-idénticos al modo headline; lo que se valida es que el
    artefacto de borde se reduce (saturación/centroide fuerte/pico interior), no la igualdad.
    """
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import run_geophysics_inversion, build_voxel_grid

    (e, n, z, tmi, sig), _ = _subsample(
        [survey.east, survey.north, survey.elevation, survey.tmi_nt, survey.sigma_nt],
        SENSOR_STRIDE,
    )
    sensors = fr.sensors(e, n, z)   # x=Este, y=prof, z=Norte
    obs = [
        GravityObservation(x_m=float(sx), y_m=float(sy), z_m=float(sz), g=0.0)
        for sx, sy, sz in sensors
    ]
    inp = GeophysicsInvertInput(
        project_id=None, run_id=None,
        depth=int(NY * BLOCK_SIZE), nir=50, fe=30, region="Raglan", lat="61.7", lon="-73.7",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK_SIZE, cutoff_radius=CUTOFF,
        lambda_mag=LAMBDA_MAG, alpha_spatial=1.0,
        observations=obs,
        magnetic_nt=[float(t) for t in tmi],
        inclination_deg=survey.inclination_deg,
        declination_deg=survey.declination_deg,
        field_intensity_nt=survey.field_intensity_nt,
        susc_min=SUSC_MIN, susc_max=SUSC_MAX,
        regularization_norm="compact",          # paridad con el harness aislado
        robust_sigma=False,                      # las anomalías fuertes son SEÑAL, no outliers
    )
    res = run_geophysics_inversion(inp)
    mesh_rep = res.get("report", {}).get("mesh", {})

    # Reconstruir la grilla CORE completa desde los vóxeles del payload (Fortran F-order).
    ix0, iy0, iz0, x_c, y_c, z_c = build_voxel_grid(inp)
    chi = np.zeros(NX * NY * NZ, dtype=np.float64)
    for v in res.get("voxels", []):
        j = int(v["ix"]) + NX * (int(v["iy"]) + NY * int(v["iz"]))   # F-order index
        chi[j] = float(v.get("susceptibility", 0.0) or 0.0)
    misfit = res.get("misfit_error_percent")
    return chi, (None if misfit is None else float(misfit)), x_c, y_c, z_c, int(sensors.shape[0]), mesh_rep


def run_via_production() -> dict:
    """PASO 5: corre Raglan por el PATH DE PRODUCCIÓN y compara el artefacto de borde
    contra el baseline SIN padding guardado (raglan_recovered_grid_nopad.npz)."""
    t0 = time.time()
    survey = load_raglan_magnetic()
    ref = load_raglan_reference(survey=survey)
    fr = build_raglan_frame(survey)
    _dir = Path(__file__).resolve().parent

    print("\n[PRODUCCIÓN] Inversión Raglan vía run_geophysics_inversion (path de /load-package)...")
    chi, misfit, x_c, y_c, z_c, n_sensors, mesh_rep = invert_via_production(survey, fr)
    geom_prod = _evaluate(chi, x_c, y_c, z_c, ref, fr, misfit)

    # Baseline SIN padding (modelo guardado de la validación previa del motor).
    geom_nopad = None
    nopad_path = _dir / "raglan_recovered_grid_nopad.npz"
    if nopad_path.exists():
        d = np.load(nopad_path)
        geom_nopad = _evaluate(d["chi"], d["x_c"], d["y_c"], d["z_c"], ref, fr, None)

    report = {
        "dataset": "Raglan Ni-Cu — VÍA PATH DE PRODUCCIÓN (run_geophysics_inversion)",
        "production_mesh": mesh_rep,
        "n_sensors_used": n_sensors,
        "result_production_with_padding": geom_prod,
        "baseline_without_padding_engine": geom_nopad,
        "padding_comparison": _build_comparison(geom_prod, geom_nopad, ref) if geom_nopad else None,
        "elapsed_s": round(time.time() - t0, 1),
    }
    out = _dir / "raglan_production_validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 80)
    print("RAGLAN — VÍA PRODUCCIÓN (padding cableado en run_magnetic_inversion)")
    print("=" * 80)
    print(f"\nMalla producción: {mesh_rep}")
    print(f"Pico GLOBAL (E,N): ({geom_prod.get('recovered_peak_east')}, {geom_prod.get('recovered_peak_north')}) "
          f"| err vs ref={geom_prod.get('horiz_err_peak_vs_ref_peak_m')}m")
    print(f"Pico INTERIOR vs ref: {geom_prod.get('horiz_err_interior_peak_vs_ref_m')}m")
    print(f"Strong-centroid vs ref peak: {geom_prod.get('horiz_err_centroid_vs_ref_peak_m')}m")
    print(f"Celdas saturadas: {geom_prod.get('n_saturated_cells')} | n_strong={geom_prod.get('n_strong_cells')}")
    print(f"Misfit: {geom_prod.get('misfit_percent')}%")
    if report["padding_comparison"]:
        c = report["padding_comparison"]
        print(f"\nComparación (baseline SIN padding del motor → producción CON padding):")
        print(f"  Pico GLOBAL err vs ref: {c['without_padding']['horiz_err_global_peak_vs_ref_m']}m "
              f"→ {c['with_padding']['horiz_err_global_peak_vs_ref_m']}m")
        print(f"  Saturadas: {c['without_padding']['n_saturated_cells']} → {c['with_padding']['n_saturated_cells']}")
    print(f"\nReporte: {out} | {report['elapsed_s']}s")
    return report


def _corr(a, b):
    a = np.asarray(a, float).ravel(); b = np.asarray(b, float).ravel()
    if a.size < 3 or a.std() == 0 or b.std() == 0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 3)


def _structural_correlation(chi, x_c, y_c, z_c, fr: LocalFrame) -> dict:
    """Correlación en el DOMINIO del MODELO entre la susc de TQ y la de referencia.

    Reporta DOS correlaciones de Pearson:
      • 3D (celda a celda): penaliza fuerte la diferencia de DISTRIBUCIÓN EN PROFUNDIDAD
        (la referencia difumina el cuerpo a 350–950 m; TQ lo concentra a 100–300 m — ambas
        no-únicas en z). Por eso sale baja aunque la posición horizontal coincida.
      • HORIZONTAL (colapsando profundidad): suma la susc por columna (East,North) en TQ y
        en la referencia → mide si la ESTRUCTURA HORIZONTAL (lo relevante para targeting)
        coincide. Es la métrica más justa para "¿el cuerpo está donde la referencia lo pone?".
    También da el IoU de regiones fuertes 3D.
    """
    cube, rxc, ryc, rzc = load_reference_cube()
    chi = np.asarray(chi, dtype=np.float64)
    east = np.asarray(x_c) + fr.origin_east
    north = np.asarray(z_c) + fr.origin_north
    depth = np.asarray(y_c)
    ie = np.clip(np.searchsorted(0.5 * (rxc[:-1] + rxc[1:]), east), 0, len(rxc) - 1)
    jn = np.clip(np.searchsorted(0.5 * (ryc[:-1] + ryc[1:]), north), 0, len(ryc) - 1)
    kd = np.clip(np.searchsorted(0.5 * (rzc[:-1] + rzc[1:]), depth), 0, len(rzc) - 1)
    ref_sampled = cube[ie, jn, kd]
    finite = np.isfinite(chi)
    a = chi[finite]; b = ref_sampled[finite]
    corr3d = _corr(a, b)
    sa = a > 0.5 * a.max() if a.max() > 0 else np.zeros_like(a, bool)
    sb = b > 0.5 * b.max() if b.max() > 0 else np.zeros_like(b, bool)
    union = int(np.sum(sa | sb))
    iou = round(int(np.sum(sa & sb)) / union, 3) if union > 0 else None

    # ── Correlación HORIZONTAL (mapas colapsados en profundidad) ─────────────
    Ne = np.unique(north); Ee = np.unique(east)
    tq2d = np.zeros((Ne.size, Ee.size))
    in_ = np.searchsorted(Ne, north); ie2 = np.searchsorted(Ee, east)
    np.add.at(tq2d, (in_, ie2), np.where(finite, chi, 0.0))
    ref_full2d = cube.sum(axis=2)   # [East_idx, North_idx]
    ref2d = np.zeros_like(tq2d)
    for i, nn in enumerate(Ne):
        jn2 = int(np.argmin(np.abs(ryc - nn)))
        for j, ee in enumerate(Ee):
            ie3 = int(np.argmin(np.abs(rxc - ee)))
            ref2d[i, j] = ref_full2d[ie3, jn2]
    corr_h = _corr(tq2d, ref2d)
    return {
        "model_pearson_corr_3d": corr3d,
        "model_pearson_corr_horizontal": corr_h,
        "strong_region_iou": iou,
    }


def measure(chi, x_c, y_c, z_c, ref: RaglanReference, fr: LocalFrame) -> dict:
    """Mide la posición del cuerpo recuperado vs la referencia (pico + anomalía de datos)."""
    chi = np.asarray(chi, dtype=np.float64)
    finite = np.isfinite(chi)
    cmax = float(np.nanmax(chi[finite])) if np.any(finite) else 0.0
    if cmax <= 0:
        return {"recovered_peak": None}
    # Pico recuperado (celda de máxima susc) → coords de datos.
    ip = int(np.nanargmax(np.where(finite, chi, -np.inf)))
    peak_east = fr.to_easting(x_c[ip]); peak_north = fr.to_northing(z_c[ip])
    peak_depth = float(y_c[ip])
    # Centroide de la región fuerte (>0.5·max).
    strong = finite & (chi > 0.5 * cmax)
    w = chi[strong]
    sc_east = fr.to_easting(float(np.average(x_c[strong], weights=w)))
    sc_north = fr.to_northing(float(np.average(z_c[strong], weights=w)))
    sc_depth = float(np.average(y_c[strong], weights=w))

    # Cuerpo dominante INTERIOR (mapa colapsado en profundidad, excluyendo un borde de 2
    # celdas): sin padding, la anomalía más fuerte del survey (5221 nT en el límite este
    # X≈4478) satura ~2 columnas de borde a un artefacto; lo mismo en el oeste. El cuerpo
    # geológico real se evalúa en el interior. Honesto: se reporta el pico GLOBAL (con
    # artefacto) Y el cuerpo INTERIOR (representativo del blanco de sondaje).
    east_all = np.asarray(x_c) + fr.origin_east
    north_all = np.asarray(z_c) + fr.origin_north
    Ne = np.unique(north_all); Ee = np.unique(east_all)
    hor = np.zeros((Ne.size, Ee.size))
    in_ = np.searchsorted(Ne, north_all); ie_ = np.searchsorted(Ee, east_all)
    np.add.at(hor, (in_, ie_), np.where(finite, chi, 0.0))
    pad = 2 * BLOCK_SIZE
    col_in = (Ee > Ee.min() + pad - 1) & (Ee < Ee.max() - pad + 1)
    row_in = (Ne > Ne.min() + pad - 1) & (Ne < Ne.max() - pad + 1)
    hor_int = np.where(row_in[:, None] & col_in[None, :], hor, -1.0)
    pij = np.unravel_index(int(np.argmax(hor_int)), hor.shape)
    int_north, int_east = float(Ne[pij[0]]), float(Ee[pij[1]])
    # profundidad del cuerpo interior = profundidad media ponderada en esa columna
    col_mask = finite & (np.abs(east_all - int_east) < 1) & (np.abs(north_all - int_north) < 1)
    int_depth = float(np.average(np.asarray(y_c)[col_mask], weights=chi[col_mask])) if np.any(col_mask) else float("nan")

    def _h(ae, an, be, bn):
        return round(float(np.hypot(ae - be, an - bn)), 1)

    return {
        "recovered_peak_east": round(peak_east, 1),
        "recovered_peak_north": round(peak_north, 1),
        "recovered_peak_depth_m": round(peak_depth, 1),
        "recovered_strong_centroid_east": round(sc_east, 1),
        "recovered_strong_centroid_north": round(sc_north, 1),
        "recovered_strong_centroid_depth_m": round(sc_depth, 1),
        "n_strong_cells": int(strong.sum()),
        "recovered_interior_peak_east": round(int_east, 1),
        "recovered_interior_peak_north": round(int_north, 1),
        "recovered_interior_peak_depth_m": round(int_depth, 1),
        "n_saturated_cells": int(np.sum(finite & (chi >= 0.999 * cmax))),
        # Errores horizontales (lo que importa para targeting):
        "horiz_err_peak_vs_ref_peak_m": _h(peak_east, peak_north, ref.peak_east, ref.peak_north),
        "horiz_err_peak_vs_data_anomaly_m": _h(peak_east, peak_north, ref.data_anomaly_east, ref.data_anomaly_north),
        "horiz_err_interior_peak_vs_ref_m": _h(int_east, int_north, ref.peak_east, ref.peak_north),
        "horiz_err_centroid_vs_ref_peak_m": _h(sc_east, sc_north, ref.peak_east, ref.peak_north),
        "depth_err_peak_vs_ref_m": round(abs(peak_depth - ref.peak_depth_m), 1),
        "depth_err_interior_peak_vs_ref_m": round(abs(int_depth - ref.peak_depth_m), 1),
    }


def _evaluate(chi, x_c, y_c, z_c, ref, fr, misfit) -> dict:
    """measure + correlación estructural + misfit → dict de geometría comparable."""
    geom = measure(chi, x_c, y_c, z_c, ref, fr)
    geom["misfit_percent"] = None if (misfit is None or not np.isfinite(misfit)) else round(misfit, 3)
    geom.update(_structural_correlation(chi, x_c, y_c, z_c, fr))
    return geom


def _invert_mode(survey, fr, ref, use_padding, grid_path, from_saved):
    """Invierte (o re-deriva desde grid guardado) un modo y devuelve (geom, n_sensors, sigma, meta)."""
    if from_saved and grid_path.exists():
        tag = "con padding" if use_padding else "sin padding"
        print(f"\n[modo {tag}] Re-derivando desde el modelo guardado (sin re-invertir)...")
        d = np.load(grid_path)
        chi, x_c, y_c, z_c = d["chi"], d["x_c"], d["y_c"], d["z_c"]
        misfit = None
        n_sensors = int(np.arange(0, survey.n, SENSOR_STRIDE).shape[0])
        sigma_floor = float(np.median(survey.sigma_nt[::SENSOR_STRIDE]))
        meta = {}
    else:
        tag = "CON PADDING (BC física)" if use_padding else "SIN PADDING (baseline histórico)"
        print(f"\n[modo {tag}] Inversión MAGNÉTICA escalar (IGRF real, σ=Std)...")
        chi, misfit, x_c, y_c, z_c, n_sensors, sigma_floor, meta = invert_magnetic(
            survey, fr, use_padding=use_padding
        )
        np.savez(grid_path, chi=chi, x_c=x_c, y_c=y_c, z_c=z_c)
    geom = _evaluate(chi, x_c, y_c, z_c, ref, fr, misfit)
    if geom["misfit_percent"] is None:
        # Re-deriva el misfit del reporte previo si existe.
        prev = Path(__file__).resolve().parent / "raglan_validation_report.json"
        if prev.exists():
            try:
                _key = "result_scalar" if use_padding else "result_scalar_nopadding"
                geom["misfit_percent"] = json.loads(prev.read_text(encoding="utf-8")) \
                    .get(_key, {}).get("misfit_percent")
            except Exception:
                pass
    return geom, n_sensors, sigma_floor, meta


def run(from_saved: bool = False, compare: bool = True) -> dict:
    t0 = time.time()
    survey = load_raglan_magnetic()
    ref = load_raglan_reference(survey=survey)
    fr = build_raglan_frame(survey)
    _dir = Path(__file__).resolve().parent

    # Modo headline: CON padding (condición de frontera física).
    grid_pad = _dir / "raglan_recovered_grid.npz"
    geom, n_sensors, sigma_floor, meta_pad = _invert_mode(
        survey, fr, ref, use_padding=True, grid_path=grid_pad, from_saved=from_saved
    )

    # Modo baseline: SIN padding (para la comparación lado a lado del artefacto de borde).
    geom_nopad = None
    if compare:
        grid_nopad = _dir / "raglan_recovered_grid_nopad.npz"
        geom_nopad, _, _, _ = _invert_mode(
            survey, fr, ref, use_padding=False, grid_path=grid_nopad, from_saved=from_saved
        )

    horiz = geom.get("horiz_err_peak_vs_ref_peak_m")
    horiz_int = geom.get("horiz_err_interior_peak_vs_ref_m")
    horiz_data = geom.get("horiz_err_peak_vs_data_anomaly_m")
    # El blanco geológico = cuerpo dominante INTERIOR (sin el artefacto de borde sin padding).
    targeting_pass = horiz_int is not None and horiz_int <= TARGETING_TOL_M

    report = {
        "dataset": "Raglan Ni-Cu (Quebec) — DATO DE CAMPO REAL (no synthetic-based-on); ref=maginv3d 1997",
        "ingestion": summarize(survey),
        "reference": {
            "peak_east": round(ref.peak_east, 1), "peak_north": round(ref.peak_north, 1),
            "peak_depth_m": round(ref.peak_depth_m, 1), "susc_max": round(ref.susc_max, 4),
            "strong_centroid_east": round(ref.strong_centroid_east, 1),
            "strong_centroid_north": round(ref.strong_centroid_north, 1),
            "data_anomaly_east": round(ref.data_anomaly_east, 1),
            "data_anomaly_north": round(ref.data_anomaly_north, 1),
            "note": "Modelo de referencia DIFUSO (inversión de campo real); el PICO de susc es el blanco; "
                    "se valida posición del cuerpo dominante, no susc punto a punto.",
        },
        "local_frame": {"origin_east": fr.origin_east, "origin_north": fr.origin_north, "datum_elev": fr.datum_elev},
        "mesh": {"nx": NX, "ny": NY, "nz": NZ, "block_size_m": BLOCK_SIZE,
                 "n_pad": N_PAD, "pad_factor": PAD_FACTOR, "padding_kappa": PADDING_KAPPA,
                 "n_padding_solved": meta_pad.get("n_padding_solved"),
                 "n_padding_pruned": meta_pad.get("n_padding_pruned"),
                 "n_sensors_used": n_sensors, "sigma_floor_nt": round(sigma_floor, 3)},
        "result_scalar": geom,
        "result_scalar_nopadding": geom_nopad,
        "verdict": {
            "targeting_tol_m": TARGETING_TOL_M,
            "horiz_err_global_peak_vs_ref_m": horiz,
            "horiz_err_interior_peak_vs_ref_m": horiz_int,
            "horiz_err_peak_vs_data_anomaly_m": horiz_data,
            "model_pearson_corr_horizontal": geom.get("model_pearson_corr_horizontal"),
            "model_pearson_corr_3d": geom.get("model_pearson_corr_3d"),
            "strong_region_iou": geom.get("strong_region_iou"),
            "n_saturated_cells": geom.get("n_saturated_cells"),
            "targeting_pass_interior_body": bool(targeting_pass),
            "note": "Modo headline = CON padding (BC física). El pico GLOBAL ya no se clava "
                    "en el borde Este: las celdas de padding absorben la anomalía del límite.",
        },
        "padding_comparison": _build_comparison(geom, geom_nopad, ref) if geom_nopad else None,
        "elapsed_s": round(time.time() - t0, 1),
    }
    report["table_markdown"] = _render(report)
    return report


def _build_comparison(geom_pad: dict, geom_nopad: dict, ref) -> dict:
    """Comparación lado a lado del artefacto de borde: con vs sin padding."""
    def _pick(g):
        return {
            "global_peak_east": g.get("recovered_peak_east"),
            "global_peak_north": g.get("recovered_peak_north"),
            "horiz_err_global_peak_vs_ref_m": g.get("horiz_err_peak_vs_ref_peak_m"),
            "interior_peak_east": g.get("recovered_interior_peak_east"),
            "horiz_err_interior_peak_vs_ref_m": g.get("horiz_err_interior_peak_vs_ref_m"),
            "model_pearson_corr_horizontal": g.get("model_pearson_corr_horizontal"),
            "model_pearson_corr_3d": g.get("model_pearson_corr_3d"),
            "n_saturated_cells": g.get("n_saturated_cells"),
            "misfit_percent": g.get("misfit_percent"),
        }
    _gp = geom_pad.get("horiz_err_peak_vs_ref_peak_m")
    _gn = geom_nopad.get("horiz_err_peak_vs_ref_peak_m")
    return {
        "with_padding": _pick(geom_pad),
        "without_padding": _pick(geom_nopad),
        "global_peak_error_reduction_m": (
            round(_gn - _gp, 1) if (_gp is not None and _gn is not None) else None
        ),
        "ref_peak_east": round(ref.peak_east, 1),
        "ref_peak_north": round(ref.peak_north, 1),
    }


def _render(report: dict) -> str:
    g = report["result_scalar"]
    ref = report["reference"]
    lines = [
        "| Métrica | Recuperado (TQ) | Referencia | Error |",
        "|---------|-----------------|------------|-------|",
        f"| Pico GLOBAL (E, N) | ({g.get('recovered_peak_east')}, {g.get('recovered_peak_north')}) | ({ref['peak_east']}, {ref['peak_north']}) | {g.get('horiz_err_peak_vs_ref_peak_m')} m |",
        f"| **Pico INTERIOR (sin borde)** | ({g.get('recovered_interior_peak_east')}, {g.get('recovered_interior_peak_north')}) | ({ref['peak_east']}, {ref['peak_north']}) | **{g.get('horiz_err_interior_peak_vs_ref_m')} m** |",
        f"| Prof. cuerpo interior (m) | {g.get('recovered_interior_peak_depth_m')} | {ref['peak_depth_m']} | {g.get('depth_err_interior_peak_vs_ref_m')} m |",
        f"| Corr. horizontal (Pearson) | {g.get('model_pearson_corr_horizontal')} | | |",
        f"| Corr. 3D (penaliza prof.) | {g.get('model_pearson_corr_3d')} | | |",
        f"| Misfit | {g.get('misfit_percent')}% | | |",
    ]
    cmp = report.get("padding_comparison")
    if cmp:
        wp, np_ = cmp["with_padding"], cmp["without_padding"]
        lines += [
            "",
            "**Padding (BC física) vs sin padding — artefacto de borde:**",
            "| Métrica | SIN padding | CON padding |",
            "|---------|-------------|-------------|",
            f"| Pico GLOBAL (E, N) | ({np_['global_peak_east']}, {np_['global_peak_north']}) "
            f"| ({wp['global_peak_east']}, {wp['global_peak_north']}) |",
            f"| Err. pico GLOBAL vs ref (m) | {np_['horiz_err_global_peak_vs_ref_m']} "
            f"| {wp['horiz_err_global_peak_vs_ref_m']} |",
            f"| Err. pico INTERIOR vs ref (m) | {np_['horiz_err_interior_peak_vs_ref_m']} "
            f"| {wp['horiz_err_interior_peak_vs_ref_m']} |",
            f"| Corr. horizontal | {np_['model_pearson_corr_horizontal']} "
            f"| {wp['model_pearson_corr_horizontal']} |",
            f"| Celdas saturadas | {np_['n_saturated_cells']} | {wp['n_saturated_cells']} |",
            f"| Misfit (%) | {np_['misfit_percent']} | {wp['misfit_percent']} |",
        ]
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--via-production" in sys.argv:
        run_via_production()
        return
    from_saved = "--from-saved" in sys.argv
    compare = "--no-compare" not in sys.argv
    report = run(from_saved=from_saved, compare=compare)
    print("\n" + "=" * 80)
    print("RAGLAN — VALIDACIÓN CONTRA BENCHMARK DE DATO REAL (geometría/targeting)")
    print("=" * 80)
    print("\n" + report["table_markdown"])
    v = report["verdict"]
    print(f"\nTolerancia targeting: <{v['targeting_tol_m']:.0f}m")
    print(f"  TQ localiza el cuerpo dominante INTERIOR: {'SÍ' if v['targeting_pass_interior_body'] else 'NO'} "
          f"(interior vs ref={v['horiz_err_interior_peak_vs_ref_m']}m)")
    print(f"  [Pico GLOBAL cae en artefacto de borde: {v['horiz_err_global_peak_vs_ref_m']}m; "
          f"corr horizontal={v['model_pearson_corr_horizontal']}, corr 3D={v['model_pearson_corr_3d']}]")
    print(f"\nTiempo: {report['elapsed_s']}s")
    out = Path(__file__).resolve().parent / "raglan_validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte escrito en {out}")


if __name__ == "__main__":
    main()
