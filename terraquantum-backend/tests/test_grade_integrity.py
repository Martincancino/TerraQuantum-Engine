"""
Integridad científica (gap industrial #1) — la "ley" (grade) es un PROXY HEURÍSTICO
no físico, no derivable de gravimetría. Por defecto (expose_demo_grade=False) el payload
industrial NO debe emitir ley inventada; el contraste de densidad (física real) y el
score relativo de objetivo sí se conservan. El modo demo (expose_demo_grade=True)
reproduce el comportamiento heredado.

Tests a nivel de función (rápidos, sin inversión completa).
"""
import numpy as np

from services.geophysics_service import (
    build_full_block_model_dataframe,
    build_geophysics_report,
)


def _params(expose_demo_grade: bool):
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation

    obs = [
        GravityObservation(x_m=float(i * 10), y_m=0.0, z_m=0.0, g=float(5.0 + i))
        for i in range(10)
    ]
    return GeophysicsInvertInput(
        depth=1000, nir=80, fe=70, region="norte_chile", lat="0", lon="0",
        nx=4, ny=4, nz=4, block_size=100, cutoff_radius=800.0,
        lambda_mag=1e-3, alpha_spatial=1.0, observations=obs,
        expose_demo_grade=expose_demo_grade,
    )


def _grid_arrays(n=8):
    ix = np.arange(n) % 2
    iy = (np.arange(n) // 2) % 2
    iz = np.arange(n) // 4
    x_c = ix.astype(float) * 100.0
    y_c = iy.astype(float) * 100.0
    z_c = iz.astype(float) * 100.0
    # Mitad activos (densidad finita y anómala), mitad aire (NaN)
    est_density = np.array([3.2, 3.4, 3.0, 3.6, np.nan, np.nan, np.nan, np.nan])
    probability = np.array([0.9, 0.8, 0.7, 0.95, np.nan, np.nan, np.nan, np.nan])
    return ix, iy, iz, x_c, y_c, z_c, est_density, probability


def test_block_model_grade_gated_off_by_default():
    """Sin demo: la columna grade queda toda NaN; densidad/probabilidad intactas."""
    ix, iy, iz, x_c, y_c, z_c, est_density, probability = _grid_arrays()
    df = build_full_block_model_dataframe(
        _params(False), ix, iy, iz, x_c, y_c, z_c, est_density, probability
    )
    grade = df["grade"].to_numpy()
    assert np.all(np.isnan(grade)), "grade NO debe fabricarse en modo industrial (default)"
    # La física real se conserva:
    assert np.isfinite(df["density"].to_numpy()[:4]).all()
    assert np.isfinite(df["probability"].to_numpy()[:4]).all()


def test_block_model_grade_present_in_demo_mode():
    """Con demo explícito: la ley proxy se fabrica para las celdas activas."""
    ix, iy, iz, x_c, y_c, z_c, est_density, probability = _grid_arrays()
    df = build_full_block_model_dataframe(
        _params(True), ix, iy, iz, x_c, y_c, z_c, est_density, probability
    )
    grade_active = df["grade"].to_numpy()[:4]
    assert np.isfinite(grade_active).all() and np.any(grade_active > 0.0)


def _voxels():
    return [
        {"density": 3.4, "is_active": True, "density_proxy_index": 1.2,
         "probability": 0.9, "modeled_rock_mass_kg": 3.4e6, "anomaly_intensity": 1.2,
         "target_score": 0.9, "relative_target_score": 0.9},
        {"density": 3.1, "is_active": True, "density_proxy_index": 0.8,
         "probability": 0.7, "modeled_rock_mass_kg": 3.1e6, "anomaly_intensity": 0.8,
         "target_score": 0.7, "relative_target_score": 0.7},
    ]


def test_report_nulls_grade_by_default():
    """expose_demo_grade=False → avg_grade / avg_density_proxy_index = None."""
    rep = build_geophysics_report(
        voxels=_voxels(), total_voxels=8, cutoff_density=2.75,
        total_tonnage=1e7, parquet_path="x.parquet", expose_demo_grade=False,
    )
    assert rep["avg_grade"] is None
    assert rep["avg_density_proxy_index"] is None
    # La señal física real se conserva (densidades reales en el resumen):
    assert rep["max_density"] > 2.6
    assert rep["is_demo_grade"] is True  # provenance/etiquetas se mantienen


def test_report_emits_grade_in_demo_mode():
    """expose_demo_grade=True → avg_grade numérico (comportamiento heredado)."""
    rep = build_geophysics_report(
        voxels=_voxels(), total_voxels=8, cutoff_density=2.75,
        total_tonnage=1e7, parquet_path="x.parquet", expose_demo_grade=True,
    )
    assert isinstance(rep["avg_grade"], (int, float))
    assert rep["avg_grade"] is not None


def test_report_default_signature_is_backward_compatible():
    """Llamada sin el flag (consumidores directos) preserva el grade heredado."""
    rep = build_geophysics_report(
        voxels=_voxels(), total_voxels=8, cutoff_density=2.75,
        total_tonnage=1e7, parquet_path="x.parquet",
    )
    assert rep["avg_grade"] is not None
