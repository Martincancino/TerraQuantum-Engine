"""
FASE 5 God-Tier — Tests del backbone volumétrico co-registrado.

Cubre:
  - Construcción desde parquet gravimétrico solo (dims, activos, dense round-trip).
  - Co-registración grav + mag sobre el MISMO retículo (canales alineados al
    mismo active_index; vóxel mag-only → density NaN, susceptibility finita).
  - Round-trip .npz (geometría + canales).
  - Gate de export VDB: retorna None si pyopenvdb no está instalado (non-fatal).
  - Validación de co-registración: spacing distinto → ValueError.
  - voxel_world_centers correcto (origin + spacing).
  - Pipeline export_coregistered_volume.
"""

import importlib.util

import numpy as np
import polars as pl
import pytest

from services.volumetric_service import (
    CoRegisteredVolume,
    build_coregistered_volume_from_parquets,
    export_coregistered_volume,
    export_volume_to_vdb,
)

_HAS_PYOPENVDB = importlib.util.find_spec("pyopenvdb") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: parquets sintéticos con esquema v4 del block model
# ─────────────────────────────────────────────────────────────────────────────

def _make_grid(nx, ny, nz, bs=10.0, ix0=0, iy0=0, iz0=0):
    """Devuelve (ix,iy,iz,x,y,z) F-order para una grilla nx×ny×nz."""
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    ix = gx.flatten(order="F") + ix0
    iy = gy.flatten(order="F") + iy0
    iz = gz.flatten(order="F") + iz0
    x = ix * bs + bs / 2.0
    y = iy * bs + bs / 2.0
    z = iz * bs + bs / 2.0
    return (ix.astype(int), iy.astype(int), iz.astype(int),
            x.astype(float), y.astype(float), z.astype(float))


def _write_gravity_parquet(path, nx=4, ny=3, nz=5, bs=10.0, active_mask=None):
    ix, iy, iz, x, y, z = _make_grid(nx, ny, nz, bs)
    n = len(ix)
    density = np.full(n, 2.6, dtype=float)
    if active_mask is None:
        active_mask = np.ones(n, dtype=bool)
    density[~active_mask] = np.nan
    df = pl.DataFrame({
        "ix": ix, "iy": iy, "iz": iz,
        "x_m": x, "y_m": y, "z_m": z,
        "density_t_m3": density,
        "density": density,
        "density_contrast_t_m3": density - 2.6,
        "posterior_std": np.where(active_mask, 0.05, np.nan),
        "relative_target_score": np.where(active_mask, 0.7, np.nan),
        "doi_index": np.where(active_mask, 0.9, np.nan),
        "sensitivity_proxy": np.where(active_mask, 0.5, np.nan),
        "is_active": active_mask,
        "run_type": ["gravity"] * n,
        "schema_version": ["v4.0"] * n,
    })
    df.write_parquet(str(path))
    return active_mask


def _write_magnetic_parquet(path, nx=4, ny=3, nz=5, bs=10.0, active_mask=None):
    ix, iy, iz, x, y, z = _make_grid(nx, ny, nz, bs)
    n = len(ix)
    susc = np.full(n, 0.01, dtype=float)
    if active_mask is None:
        active_mask = np.ones(n, dtype=bool)
    susc[~active_mask] = 0.0  # mag persiste 0 en aire pero is_active marca el activo
    df = pl.DataFrame({
        "ix": ix, "iy": iy, "iz": iz,
        "x_m": x, "y_m": y, "z_m": z,
        "susceptibility_si": susc,
        "relative_target_score": np.where(active_mask, 0.6, 0.0),
        "sensitivity_proxy": np.where(active_mask, 0.4, 0.0),
        "is_active": active_mask,
        "run_type": ["magnetic"] * n,
        "schema_version": ["v4.0"] * n,
    })
    df.write_parquet(str(path))
    return active_mask


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_build_from_gravity_only(tmp_path):
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)

    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))

    assert vol.dims == (4, 3, 5)
    assert np.allclose(vol.spacing, (10.0, 10.0, 10.0))
    assert vol.n_total == 60
    assert vol.n_active == 60  # todos activos
    assert "density" in vol.channels
    assert "posterior_std_density" in vol.channels
    assert "target_score_gravity" in vol.channels
    # density ~ 2.6 en todos los activos
    assert np.allclose(vol.channels["density"], 2.6)


def test_dense_roundtrip_fortran_order(tmp_path):
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)
    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))

    dense = vol.dense("density")
    assert dense.shape == (4, 3, 5)
    assert np.allclose(dense, 2.6)  # sin inactivos → sin NaN

    # round-trip: re-aplanar F-order debe recuperar el canal sobre active_index
    flat = dense.reshape(-1, order="F")
    assert np.allclose(flat[vol.active_index], vol.channels["density"])


def test_inactive_voxels_become_nan(tmp_path):
    p = tmp_path / "grav.parquet"
    nx, ny, nz = 4, 3, 5
    n = nx * ny * nz
    mask = np.ones(n, dtype=bool)
    mask[:10] = False  # 10 vóxeles de aire
    _write_gravity_parquet(p, nx=nx, ny=ny, nz=nz, active_mask=mask)

    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))
    assert vol.n_active == n - 10
    dense = vol.dense("density")
    assert np.isnan(dense.reshape(-1, order="F")[:10]).all()


def test_coregistration_grav_plus_mag(tmp_path):
    pg = tmp_path / "grav.parquet"
    pm = tmp_path / "mag.parquet"
    nx, ny, nz = 4, 3, 5
    n = nx * ny * nz

    # Gravedad: activa en la primera mitad; Magnético: activo en la segunda mitad.
    grav_mask = np.zeros(n, dtype=bool); grav_mask[: n // 2] = True
    mag_mask = np.zeros(n, dtype=bool); mag_mask[n // 2:] = True
    _write_gravity_parquet(pg, nx=nx, ny=ny, nz=nz, active_mask=grav_mask)
    _write_magnetic_parquet(pm, nx=nx, ny=ny, nz=nz, active_mask=mag_mask)

    vol = build_coregistered_volume_from_parquets(
        gravity_path=str(pg), magnetic_path=str(pm),
    )

    # Unión de activos = todo el dominio (las dos mitades cubren n).
    assert vol.n_active == n
    assert "density" in vol.channels
    assert "susceptibility" in vol.channels

    dense_rho = vol.dense("density").reshape(-1, order="F")
    dense_chi = vol.dense("susceptibility").reshape(-1, order="F")

    # Reconstruir el orden F-order global del lattice (igual al de _make_grid).
    # En la primera mitad: density finita, susceptibility NaN (mag no aportó).
    # En la segunda mitad: density NaN, susceptibility finita.
    finite_rho = np.isfinite(dense_rho)
    finite_chi = np.isfinite(dense_chi)
    # density y susceptibility deben ser complementarios en activación.
    assert finite_rho.sum() == n // 2
    assert finite_chi.sum() == mag_mask.sum()
    # No hay vóxel con ambos (las máscaras son disjuntas).
    assert not np.any(finite_rho & finite_chi)


def test_coregistration_rejects_mismatched_spacing(tmp_path):
    pg = tmp_path / "grav.parquet"
    pm = tmp_path / "mag.parquet"
    _write_gravity_parquet(pg, nx=4, ny=3, nz=5, bs=10.0)
    _write_magnetic_parquet(pm, nx=4, ny=3, nz=5, bs=25.0)  # spacing distinto

    with pytest.raises(ValueError, match="Co-registración"):
        build_coregistered_volume_from_parquets(
            gravity_path=str(pg), magnetic_path=str(pm),
        )


def test_npz_roundtrip(tmp_path):
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)
    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))

    npz_path = vol.to_npz(str(tmp_path / "vol.npz"))
    vol2 = CoRegisteredVolume.from_npz(npz_path)

    assert vol2.dims == vol.dims
    assert np.allclose(vol2.spacing, vol.spacing)
    assert np.allclose(vol2.world_origin, vol.world_origin)
    assert vol2.index_origin == vol.index_origin
    assert np.array_equal(vol2.active_index, vol.active_index)
    assert set(vol2.channel_names) == set(vol.channel_names)
    for name in vol.channel_names:
        a, b = vol.channels[name], vol2.channels[name]
        assert np.allclose(a, b, equal_nan=True)


def test_voxel_world_centers(tmp_path):
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)
    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))

    centers = vol.voxel_world_centers()
    assert centers.shape == (vol.n_active, 3)
    # El vóxel (0,0,0) tiene centro = world_origin = bs/2 = 5.0 en cada eje.
    first = vol.active_index == 0
    assert np.allclose(centers[first][0], [5.0, 5.0, 5.0])


def test_index_origin_offset(tmp_path):
    """Índices no arrancando en 0 → lattice normalizado, world_origin correcto."""
    p = tmp_path / "grav.parquet"
    ix, iy, iz, x, y, z = _make_grid(4, 3, 5, bs=10.0, ix0=7, iy0=2, iz0=11)
    n = len(ix)
    pl.DataFrame({
        "ix": ix, "iy": iy, "iz": iz,
        "x_m": x, "y_m": y, "z_m": z,
        "density_t_m3": np.full(n, 2.6),
        "is_active": np.ones(n, dtype=bool),
    }).write_parquet(str(p))

    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))
    assert vol.dims == (4, 3, 5)
    assert vol.index_origin == (7, 2, 11)
    # world origin = centro del índice mínimo (ix0=7 → x=7*10+5=75)
    assert np.allclose(vol.world_origin, [75.0, 25.0, 115.0])


def test_vdb_export_gate(tmp_path):
    """Sin pyopenvdb → export_volume_to_vdb retorna None sin crashear."""
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)
    vol = build_coregistered_volume_from_parquets(gravity_path=str(p))

    result = export_volume_to_vdb(vol, str(tmp_path / "vol.vdb"))
    if _HAS_PYOPENVDB:
        assert result is not None
        assert result.endswith(".vdb")
    else:
        assert result is None  # gate non-fatal


def test_export_pipeline(tmp_path):
    p = tmp_path / "grav.parquet"
    _write_gravity_parquet(p, nx=4, ny=3, nz=5, bs=10.0)

    info = export_coregistered_volume(
        output_dir=str(tmp_path), run_prefix="coreg",
        gravity_path=str(p), write_vdb=True,
    )
    assert info["npz_path"].endswith(".npz")
    assert info["dims"] == (4, 3, 5)
    assert info["n_active"] == 60
    assert "density" in info["channels"]
    # vdb_path None salvo que pyopenvdb esté instalado
    if not _HAS_PYOPENVDB:
        assert info["vdb_path"] is None
    # write_svdag default False → sin SVDAG
    assert info["svdag"] is None


def test_export_pipeline_with_svdag(tmp_path):
    """write_svdag=True → el pipeline deriva un SVDAG del mismo volumen."""
    from pathlib import Path as _P
    p = tmp_path / "grav.parquet"
    # densidad con gradiente → varias clases en el binning
    nx, ny, nz = 8, 8, 8
    ix, iy, iz, x, y, z = _make_grid(nx, ny, nz, bs=10.0)
    n = len(ix)
    density = 2.6 + (ix + iy + iz) * 0.05
    pl.DataFrame({
        "ix": ix, "iy": iy, "iz": iz, "x_m": x, "y_m": y, "z_m": z,
        "density_t_m3": density.astype(float),
        "is_active": np.ones(n, dtype=bool),
    }).write_parquet(str(p))

    info = export_coregistered_volume(
        output_dir=str(tmp_path), run_prefix="coreg",
        gravity_path=str(p), write_vdb=False,
        write_svdag=True, svdag_channel="density", svdag_n_classes=4,
    )
    sv = info["svdag"]
    assert sv is not None
    assert sv["npz_path"].endswith("_svdag.npz")
    assert _P(sv["npz_path"]).exists()
    assert sv["n_dag_nodes"] >= 1
    assert sv["dims"] == (nx, ny, nz)
    assert sv["compression_vs_voxels"] > 1.0


def test_requires_at_least_one_source():
    with pytest.raises(ValueError, match="al menos un parquet"):
        build_coregistered_volume_from_parquets()


# ─────────────────────────────────────────────────────────────────────────────
# Fase 5.2 — Integración: wiring opt-in en run_geophysics_inversion
# ─────────────────────────────────────────────────────────────────────────────

def _build_gravity_params(project_id, run_id, export_volume, export_svdag=False):
    """Construye params de una inversión gravimétrica sintética pequeña."""
    from exploration.gravimetry import GravimetryForward
    from schemas.geophysics_schema import GeophysicsInvertInput

    NX, NY, NZ, BS = 8, 6, 8, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BS + BS / 2
    y_c = gy.flatten(order="F") * BS + BS / 2
    z_c = gz.flatten(order="F") * BS + BS / 2

    r = np.sqrt((x_c - 40.0) ** 2 + (y_c - 30.0) ** 2 + (z_c - 40.0) ** 2)
    contrast = np.where(r <= 15.0, 0.6, 0.0)

    fwd = GravimetryForward(BS, BS, BS, cutoff_radius=2000.0)
    sx, sz = np.meshgrid(
        np.arange(5, NX * BS, 10, dtype=float),
        np.arange(5, NZ * BS, 10, dtype=float),
        indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast
    observations = [
        {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
        for s, g in zip(sensors, g_obs)
    ]

    return GeophysicsInvertInput(
        project_id=project_id, run_id=run_id,
        depth=int(NY * BS), nir=50, fe=50,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BS),
        cutoff_radius=int(NX * BS * 2),
        lambda_mag=1e-4, alpha_spatial=1.0,
        observations=observations,
        export_coregistered_volume=export_volume,
        export_categorical_svdag=export_svdag,
    )


def test_schema_flag_default_off():
    """El flag de export es OFF por defecto (comportamiento histórico)."""
    p = _build_gravity_params("pytest_p", "pytest_r", export_volume=False)
    assert p.export_coregistered_volume is False


@pytest.mark.benchmark
def test_wiring_export_on_produces_volume(test_project_id, test_run_id):
    """Flag ON → report trae coregistered_volume con .npz existente + canales."""
    from services.geophysics_service import run_geophysics_inversion

    params = _build_gravity_params(test_project_id, test_run_id, export_volume=True)
    result = run_geophysics_inversion(params)
    report = result.get("report", {})

    info = report.get("coregistered_volume")
    assert info is not None, "coregistered_volume ausente con el flag ON"
    assert info["npz_path"].endswith(".npz")
    from pathlib import Path as _P
    assert _P(info["npz_path"]).exists(), "el .npz co-registrado no se escribió"
    assert "density" in info["channels"]
    assert info["n_active"] > 0
    # Sin pyopenvdb instalado, vdb_path es None (gate non-fatal).
    if not _HAS_PYOPENVDB:
        assert info["vdb_path"] is None


@pytest.mark.benchmark
def test_wiring_export_off_is_none(test_project_id, test_run_id):
    """Flag OFF (default) → coregistered_volume = None (sin export)."""
    from services.geophysics_service import run_geophysics_inversion

    params = _build_gravity_params(test_project_id, test_run_id, export_volume=False)
    result = run_geophysics_inversion(params)
    report = result.get("report", {})
    assert report.get("coregistered_volume") is None


def test_schema_svdag_flag_default_off():
    """El flag de export SVDAG es OFF por defecto."""
    p = _build_gravity_params("pytest_p", "pytest_r", export_volume=False)
    assert p.export_categorical_svdag is False


@pytest.mark.benchmark
def test_wiring_svdag_flag_produces_dag(test_project_id, test_run_id):
    """Flag SVDAG ON → report.coregistered_volume.svdag con .npz existente."""
    from pathlib import Path as _P
    from services.geophysics_service import run_geophysics_inversion

    params = _build_gravity_params(
        test_project_id, test_run_id, export_volume=False, export_svdag=True,
    )
    result = run_geophysics_inversion(params)
    report = result.get("report", {})

    info = report.get("coregistered_volume")
    assert info is not None, "el volumen se construye aunque solo se pida SVDAG"
    sv = info.get("svdag")
    assert sv is not None, "svdag ausente con el flag ON"
    assert _P(sv["npz_path"]).exists()
    assert sv["n_dag_nodes"] >= 1
