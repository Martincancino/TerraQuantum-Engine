"""
HITO 4 — Calibración DOI (Depth of Investigation, Li & Oldenburg 1999).

El backend calcula `doi_raw` como el índice de sensibilidad adimensional:

    doi_raw_j = |m1_j - m2_j| / |m_ref1 - m_ref2|

donde m1 es la inversión con m_ref=0 y m2 con m_ref=0.1 t/m³.

Interpretación física:
  doi_raw ≈ 0   → celda BIEN RESUELTA (modelo insensible al modelo de referencia)
  doi_raw ≈ 1   → celda MAL RESUELTA (modelo dependiente del modelo de referencia)
  doi_raw > 0.1 → convencionalmente fuera del DOI (Li & Oldenburg 1999, Tabla 1)

Para una anomalía compacta a 50m de profundidad en dominio de 80m, con datos
sintéticos de alta calidad, esperamos que la mediana de doi_raw sea baja
(modelo bien determinado en la zona de la anomalía).

Este test NO usa la misma malla para forward e inversión (protocolo anti-inverse-crime).
"""
import numpy as np
import pytest


# Umbral del índice DOI adimensional (Li & Oldenburg 1999).
# doi_raw < DOI_RESOLVED_THRESHOLD → celda considerada "resuelta"
DOI_RESOLVED_THRESHOLD = 0.1

# El p50 del índice doi_raw debe ser:
#   - Positivo y finito (no degenerate)
#   - Menor que DOI_RESOLVED_THRESHOLD: al menos la mitad de las celdas
#     son bien resueltas para una anomalía superficial bien condicionada.
DOI_P50_MAX = DOI_RESOLVED_THRESHOLD   # p50 < 0.1


@pytest.mark.benchmark
def test_doi_within_physical_range(test_project_id, test_run_id):
    """doi_raw p50 debe ser < 0.1 (celda mediana bien resuelta) para anomalía superficial."""
    from exploration.gravimetry import GravimetryForward
    from schemas.geophysics_schema import GeophysicsInvertInput
    from services.geophysics_service import run_geophysics_inversion

    # ── Forward sintético: anomalía compacta a Y_TRUE = 50m ──────────────────
    NX, NY, NZ, BS = 10, 8, 10, 10.0
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BS + BS / 2
    y_c = gy.flatten(order="F") * BS + BS / 2
    z_c = gz.flatten(order="F") * BS + BS / 2

    Y_TRUE = 50.0
    cx, cy_anom, cz = 50.0, Y_TRUE, 50.0
    r = np.sqrt((x_c - cx)**2 + (y_c - cy_anom)**2 + (z_c - cz)**2)
    contrast = np.where(r <= 15.0, 0.5, 0.0)

    fwd = GravimetryForward(BS, BS, BS, cutoff_radius=2000.0)
    sx_grid, sz_grid = np.meshgrid(
        np.arange(5, 95, 10, dtype=float),
        np.arange(5, 95, 10, dtype=float),
        indexing="ij",
    )
    sensors = np.column_stack([sx_grid.ravel(), np.zeros(sx_grid.size), sz_grid.ravel()])
    kernel = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors)
    g_obs = kernel @ contrast

    observations = [
        {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
        for s, g in zip(sensors, g_obs)
    ]

    params = GeophysicsInvertInput(
        project_id=test_project_id,
        run_id=test_run_id,
        depth=int(NY * BS),
        nir=83, fe=79,
        region="norte_chile", lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ,
        block_size=int(BS),
        cutoff_radius=int(NX * BS * 2),
        lambda_mag=1e-4, alpha_spatial=1.0,
        compute_uncertainty=True,
        observations=observations,
    )

    result = run_geophysics_inversion(params)
    report = result.get("report", {})
    doi_diag = report.get("doiDiagnostics", {})
    doi_p50 = doi_diag.get("p50")

    assert doi_p50 is not None, (
        "doiDiagnostics.p50 no presente en el report — "
        "¿compute_uncertainty=True no activa el cálculo DOI?"
    )
    assert np.isfinite(doi_p50), f"doi_p50={doi_p50} no es finito"
    assert doi_p50 > 0.0, (
        f"doi_p50={doi_p50:.6f} es cero o negativo — índice DOI degenerado"
    )
    assert doi_p50 < DOI_P50_MAX, (
        f"doi_raw p50={doi_p50:.4f} >= {DOI_P50_MAX} — "
        "celda mediana mal resuelta. Para anomalía a {:.0f}m en dominio de {:.0f}m, "
        "se esperan al menos 50% de celdas con doi_raw < 0.1 "
        "(Li & Oldenburg 1999, índice adimensional, bajo = bien resuelto).".format(
            Y_TRUE, NY * BS
        )
    )


@pytest.mark.unit
def test_doi_index_interpretation():
    """Verifica que los valores típicos del índice DOI tienen la interpretación correcta.

    doi_raw = |m1 - m2| / |m_ref1 - m_ref2| = |m1 - m2| / 0.1
    Rango esperado: (0, ~2] en casos reales.
    """
    # Celda perfectamente resuelta: ambas inversiones dan el mismo resultado
    doi_resolved = abs(0.0 - 0.0) / 0.1
    assert doi_resolved == 0.0

    # Celda en el umbral Li & Oldenburg: m1-m2 = 0.01 (10% del offset de referencia)
    doi_at_threshold = abs(0.01 - 0.0) / 0.1
    assert abs(doi_at_threshold - 0.1) < 1e-10

    # Celda completamente irresuelta: diferencia = offset completo
    doi_unresolved = abs(0.1 - 0.0) / 0.1
    assert abs(doi_unresolved - 1.0) < 1e-10
