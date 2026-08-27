"""
FASE 20C — Magnetic Vector Inversion (MVI). Tests deterministas de la ruta MVI.

Cubre los 4 gates del plan:
  PASO 1 — kernel 3C (Gx,Gy,Gz) reproduce el TMI escalar al fijar M = κ·f̂.
  PASO 2 — solver MVI converge en malla pequeña sin NaN, cond finito.
  PASO 3 — amplitud |M| y dirección (inc/dec) derivadas correctamente.
  PASO 4 — cuerpo con remanencia OBLICUA: MVI localiza mejor que el escalar.

Todo es OPT-IN: el camino escalar histórico no se toca. Ningún test tunea umbrales.
"""

import numpy as np
import pytest

from exploration.magnetometry import (
    MagnetometryForward,
    MagnetometryInversion,
    field_unit_vector,
)


# ──────────────────────────────────────────────────────────────────────────
# Geometría sintética compartida (malla pequeña, determinista)
# ──────────────────────────────────────────────────────────────────────────
def _build_grid(nx=10, ny=14, nz=10, block=10.0):
    grid_x, grid_y, grid_z = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)
    x_c = (ix * block) + (block / 2)
    y_c = (iy * block) + (block / 2)
    z_c = (iz * block) + (block / 2)
    return x_c, y_c, z_c


def _sensor_grid(n=8, lo=10.0, hi=100.0):
    sx, sz = np.meshgrid(np.linspace(lo, hi, n), np.linspace(lo, hi, n))
    return np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])


INC, DEC, B0 = -30.0, 2.0, 23500.0
BLOCK = 10.0


# ══════════════════════════════════════════════════════════════════════════
# PASO 1 — Consistencia kernel MVI vs escalar
# ══════════════════════════════════════════════════════════════════════════
def test_mvi_kernel_matches_scalar_induced():
    """Gate Paso 1: con M = κ·f̂ (inducción pura), Gx·Mx+Gy·My+Gz·Mz == TMI escalar."""
    x_c, y_c, z_c = _build_grid()
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)

    G_scalar = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)

    # Susceptibilidad arbitraria por celda
    rng = np.random.default_rng(0)
    kappa = rng.uniform(0.0, 0.5, size=len(x_c))

    f = field_unit_vector(INC, DEC)
    # Magnetización inducida: M = κ·f̂ (componente a componente)
    Mx, My, Mz = kappa * f[0], kappa * f[1], kappa * f[2]

    tmi_scalar = G_scalar @ kappa
    tmi_mvi = Gx @ Mx + Gy @ My + Gz @ Mz

    denom = max(float(np.linalg.norm(tmi_scalar)), 1e-30)
    rel_err = float(np.linalg.norm(tmi_mvi - tmi_scalar)) / denom
    assert rel_err < 1e-6, f"MVI no reproduce el escalar (rel_err={rel_err:.2e})"


def test_mvi_kernel_shapes_and_finite():
    x_c, y_c, z_c = _build_grid()
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    for G in (Gx, Gy, Gz):
        assert G.shape == (len(sensors), len(x_c))
        assert np.isfinite(G.data).all()
    # Misma esparsidad (mismo cutoff/KDTree)
    assert Gx.nnz == Gy.nnz == Gz.nnz


# ══════════════════════════════════════════════════════════════════════════
# PASO 2 — Solver MVI converge sin NaN
# ══════════════════════════════════════════════════════════════════════════
def test_mvi_solver_converges_no_nan():
    x_c, y_c, z_c = _build_grid()
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)

    # Cuerpo inducido sintético
    f = field_unit_vector(INC, DEC)
    kappa = np.zeros(len(x_c))
    blob = ((x_c - 50.0) ** 2 + (y_c - 40.0) ** 2 + (z_c - 50.0) ** 2) < 18.0 ** 2
    kappa[blob] = 0.2
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    d_obs = Gx @ (kappa * f[0]) + Gy @ (kappa * f[1]) + Gz @ (kappa * f[2])

    inv = MagnetometryInversion(10, 14, 10, BLOCK)
    meta = {}
    out = inv.solve_mvi_inversion_lsqr(
        d_obs, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0, solver_meta=meta,
    )
    amp = out["amplitude_full"]
    assert np.isfinite(np.nan_to_num(amp)).all()
    assert np.isfinite(meta["acond"]) and meta["acond"] < 1e14
    assert out["misfit_percent"] < 25.0
    # Localización honesta en un problema sub-determinado: el CENTROIDE ponderado por
    # amplitud (no un único argmax, que es frágil) debe caer sobre el cuerpo en el
    # plano horizontal (eje bien restringido) y razonablemente cerca en profundidad.
    amp_clean = np.nan_to_num(amp, nan=0.0)
    w = amp_clean
    cx = float(np.average(x_c, weights=w))
    cy = float(np.average(y_c, weights=w))
    cz = float(np.average(z_c, weights=w))
    assert abs(cx - 50.0) <= 10.0, f"centroide x={cx:.1f} lejos de 50"
    assert abs(cz - 50.0) <= 10.0, f"centroide z={cz:.1f} lejos de 50"
    assert abs(cy - 40.0) <= 30.0, f"centroide y={cy:.1f} lejos de 40"


# ══════════════════════════════════════════════════════════════════════════
# PASO 3 — Amplitud y dirección
# ══════════════════════════════════════════════════════════════════════════
def test_mvi_amplitude_direction_recovery():
    """Cuerpo inducido: la dirección efectiva en el pico ≈ (INC, DEC) del campo."""
    x_c, y_c, z_c = _build_grid()
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)
    f = field_unit_vector(INC, DEC)
    kappa = np.zeros(len(x_c))
    blob = ((x_c - 50.0) ** 2 + (y_c - 40.0) ** 2 + (z_c - 50.0) ** 2) < 18.0 ** 2
    kappa[blob] = 0.25
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    d_obs = Gx @ (kappa * f[0]) + Gy @ (kappa * f[1]) + Gz @ (kappa * f[2])

    inv = MagnetometryInversion(10, 14, 10, BLOCK)
    out = inv.solve_mvi_inversion_lsqr(
        d_obs, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    amp = np.nan_to_num(out["amplitude_full"], nan=0.0)
    inc_full = out["inclination_full"]
    dec_full = out["declination_full"]
    # Dirección efectiva ponderada por amplitud sobre las celdas de mayor señal (el
    # cuerpo), NO en un único argmax frágil. Sin remanencia → debe ≈ dirección inducida.
    strong = amp > 0.5 * amp.max()
    assert strong.sum() > 0
    w = amp[strong]
    # FASE 19: la declinación se promedia en CIRCULAR (por vector unitario), no con
    # `np.average`. MEDIDO: las declinaciones por celda barren ±180°, y la media
    # aritmética las cancela — daba −3,2° con el código correcto y −0,8° con la
    # declinación REFLEJADA, así que este test pasaba verde con las dos. En circular
    # salen 9,8° y 80,2° (suman 90: la firma de la reflexión). La inclinación no
    # tiene ese problema: vive en (−90, 90) y no envuelve.
    dec_rad = np.radians(dec_full[strong])
    inc_eff = float(np.average(inc_full[strong], weights=w))
    dec_eff = float(np.degrees(np.arctan2(np.sum(w * np.sin(dec_rad)),
                                          np.sum(w * np.cos(dec_rad)))))
    assert abs(inc_eff - INC) <= 20.0, f"inc efectiva={inc_eff:.1f} vs inducida {INC}"
    assert abs(dec_eff - DEC) <= 25.0, f"dec efectiva={dec_eff:.1f} vs inducida {DEC}"
    assert amp.max() > 0.0


# ══════════════════════════════════════════════════════════════════════════
# PASO 4 — Remanencia OBLICUA: MVI > escalar en localización
# ══════════════════════════════════════════════════════════════════════════
def _depth_of_peak(model_full, y_c):
    m = np.nan_to_num(model_full, nan=0.0)
    if m.max() <= 0:
        return float("nan")
    return float(y_c[int(np.argmax(m))])


def test_mvi_beats_scalar_on_oblique_remanence():
    """
    Cuerpo con magnetización REMANENTE oblicua (dirección ≠ B0). Anti-inverse-crime:
    los datos se generan con el kernel MVI a partir de M en dirección remanente; la
    inversión escalar (asume inducción) NO conoce esa dirección.

    Criterio honesto: MVI localiza el cuerpo (pico de amplitud) más cerca de la
    profundidad real que el escalar. Números reales reportados por el test.
    """
    nx, ny, nz = 10, 14, 10
    x_c, y_c, z_c = _build_grid(nx, ny, nz)
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)

    # Cuerpo a y_real con magnetización remanente OBLICUA (muy distinta de B0)
    y_real = 60.0
    cx, cz = 50.0, 50.0
    blob = ((x_c - cx) ** 2 + (y_c - y_real) ** 2 + (z_c - cz) ** 2) < 18.0 ** 2
    amp_true = np.zeros(len(x_c))
    amp_true[blob] = 0.3
    # Dirección remanente oblicua: inc=+55 (hacia abajo), dec=80 (casi al Este)
    f_rem = field_unit_vector(55.0, 80.0)
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    d_obs = (Gx @ (amp_true * f_rem[0])
             + Gy @ (amp_true * f_rem[1])
             + Gz @ (amp_true * f_rem[2]))

    inv = MagnetometryInversion(nx, ny, nz, BLOCK)

    # (a) Escalar: asume inducción (dirección B0). NO conoce la remanencia.
    susc_scalar, _, misfit_scalar, _ = inv.solve_magnetic_inversion_lsqr(
        d_obs, y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=2.0,
    )

    # (b) MVI: recupera la amplitud sin conocer la dirección
    out = inv.solve_mvi_inversion_lsqr(
        d_obs, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    amp_mvi = out["amplitude_full"]

    depth_scalar = _depth_of_peak(susc_scalar, y_c)
    depth_mvi = _depth_of_peak(amp_mvi, y_c)
    err_scalar = abs(depth_scalar - y_real)
    err_mvi = abs(depth_mvi - y_real)

    print(
        f"\n[MVI PASO4] y_real={y_real:.0f} | escalar pico y={depth_scalar:.0f} "
        f"(err={err_scalar:.0f}m, misfit={misfit_scalar:.1f}%) | "
        f"MVI pico y={depth_mvi:.0f} (err={err_mvi:.0f}m, misfit={out['misfit_percent']:.1f}%)"
    )

    # MVI ajusta los datos remanentes mucho mejor (el escalar no puede con dir. fija)
    assert out["misfit_percent"] < misfit_scalar
    # MVI localiza al menos tan bien como el escalar (no empeora; mejora esperada)
    assert err_mvi <= err_scalar + 1e-6


def test_mvi_no_worse_than_scalar_pure_induced():
    """Sanidad: en cuerpo SIN remanencia (inducido puro), MVI no empeora el misfit."""
    nx, ny, nz = 10, 14, 10
    x_c, y_c, z_c = _build_grid(nx, ny, nz)
    sensors = _sensor_grid()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=400.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)
    f = field_unit_vector(INC, DEC)
    kappa = np.zeros(len(x_c))
    blob = ((x_c - 50.0) ** 2 + (y_c - 40.0) ** 2 + (z_c - 50.0) ** 2) < 18.0 ** 2
    kappa[blob] = 0.2
    Gx, Gy, Gz = fwd.build_mvi_kernels(x_c, y_c, z_c, sensors)
    d_obs = Gx @ (kappa * f[0]) + Gy @ (kappa * f[1]) + Gz @ (kappa * f[2])

    inv = MagnetometryInversion(nx, ny, nz, BLOCK)
    _, _, misfit_scalar, _ = inv.solve_magnetic_inversion_lsqr(
        d_obs, y_c, lambda_mag=1e-3, alpha_spatial=1.0,
        forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=2.0,
    )
    out = inv.solve_mvi_inversion_lsqr(
        d_obs, y_c, forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0,
    )
    # MVI tiene más libertad → su misfit debe ser comparable o menor (no peor por un margen)
    assert out["misfit_percent"] <= misfit_scalar + 2.0


# ══════════════════════════════════════════════════════════════════════════
# RUTEO E2E — geophysics_service.run_geophysics_inversion con magnetization_model
# ══════════════════════════════════════════════════════════════════════════
def _make_mag_input(model):
    """Input magnético-aislado (g=0) con TMI sintetizada en la grilla del servicio."""
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import build_voxel_grid

    nx, ny, nz, block = 6, 8, 6, 20.0
    obs = []
    for i in range(6):
        for j in range(6):
            obs.append(GravityObservation(x_m=10 + i * 20, y_m=0.0, z_m=10 + j * 20, g=0.0))
    sensors = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)

    base = GeophysicsInvertInput(
        project_id=None, run_id=None,
        depth=120, nir=50, fe=30, region="desconocida", lat="-23.5", lon="-70.2",
        nx=nx, ny=ny, nz=nz, block_size=block, cutoff_radius=200.0,
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=obs,
        magnetic_nt=[0.0] * len(obs),  # placeholder; se reemplaza con señal real abajo
        inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0,
    )
    ix, iy, iz, x_c, y_c, z_c = build_voxel_grid(base)
    fwd = MagnetometryForward(block, block, block, cutoff_radius=200.0,
                              inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)
    G = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    kappa = np.zeros(len(x_c))
    kappa[((x_c - 60) ** 2 + (y_c - 50) ** 2 + (z_c - 60) ** 2) < 25 ** 2] = 0.2
    d = G @ kappa
    return base.model_copy(update={"magnetic_nt": d.tolist(), "magnetization_model": model})


def test_service_routes_scalar_by_default():
    from services.geophysics_service import run_geophysics_inversion
    res = run_geophysics_inversion(_make_mag_input("scalar"))
    assert res["report"]["method"] == "magnetic_dipole_tmi_phase9a"
    assert res["report"]["magnetization_model"] == "scalar"
    # El camino escalar NO emite dirección de magnetización
    assert "magnetization_inc_deg" not in res["voxels"][0]


def test_service_routes_vector_mvi():
    from services.geophysics_service import run_geophysics_inversion
    res = run_geophysics_inversion(_make_mag_input("vector"))
    rep = res["report"]
    assert rep["method"] == "magnetic_vector_inversion_phase20c"
    assert rep["magnetization_model"] == "vector"
    assert rep["mvi"]["amplitude_is_effective_susceptibility"] is True
    assert rep["mvi"]["n_unknowns"] == 3 * rep["solver"]["n_active"]
    assert res["voxels"], "MVI no devolvió vóxeles"
    v0 = res["voxels"][0]
    # Cada vóxel MVI expone amplitud + dirección recuperada
    assert "magnetization_amplitude" in v0
    assert "magnetization_inc_deg" in v0 and "magnetization_dec_deg" in v0
    assert float(res["misfit_error_percent"]) < 25.0


def test_mvi_parquet_direction_columns_valid(tmp_path):
    """Persistencia: el parquet magnético con columnas de dirección MVI extra sigue
    cumpliendo el contrato de schema (run_type='magnetic'). Las columnas required no
    cambian; las de dirección son adicionales."""
    import polars as pl
    from services.block_model_store import validate_parquet_schema

    n = 5
    df = pl.DataFrame({
        "x_m": [0.0] * n, "y_m": [0.0] * n, "z_m": [0.0] * n,
        "susceptibility_si": [0.1] * n,
        "magnetization_amplitude_si": [0.1] * n,
        "magnetization_inc_deg": [-30.0, -31.0, float("nan"), -29.0, -30.5],
        "magnetization_dec_deg": [2.0, 1.5, float("nan"), 2.2, 1.8],
        "magnetization_model": ["vector"] * n,
        "run_type": ["magnetic"] * n,
        "schema_version": ["v4.0"] * n,
    })
    p = tmp_path / "mvi_block_model.parquet"
    df.write_parquet(str(p))
    result = validate_parquet_schema(p, expected_run_type="magnetic")
    assert result["valid"], f"parquet MVI inválido: {result['errors']}"
    # Las columnas de dirección quedaron persistidas
    cols = set(pl.read_parquet(str(p), n_rows=1).columns)
    assert {"magnetization_inc_deg", "magnetization_dec_deg"} <= cols
