"""F8 — Matriz E2E de flujos (subconjunto de cobertura, suite rápida).

Cada combo = {física} × {suciedad} × {tamaño} × {geo/Helmert} × {DEM} recorre el
flujo REAL del usuario (enrich-package → load-package síncrono) y DEBE terminar
en un modelo 3D válido O un error catalogado — jamás crash / 5xx pelado / basura
silenciosa (NaN/Inf o densidad fuera de rango en un modelo "done").

Este archivo corre el SUBCONJUNTO DE COBERTURA (cada valor de cada eje ≥1 vez,
mallas chicas). El barrido cartesiano completo (cientos de combos) vive en
`scripts/validation/f8_gate_storm.py` (el gate, bajo demanda). Marcado `slow`
porque cada combo dispara una inversión real (>10 s en conjunto).

El fixture autouse `reset_rate_limit` (conftest) da a cada test su propio
presupuesto de rate-limit, así que un combo = un test parametrizado.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.f8_storm_lib as L  # noqa: E402

pytestmark = pytest.mark.slow

_SUBSET = L.covering_subset()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _expected(combo: L.Combo) -> str:
    """Expectativa semántica determinista donde la hay; 'any' si el borde es legítimo."""
    if combo.physics == "sondajes":
        return "catalogued"          # sondajes-solo no define inversión → rechazo claro
    if combo.cleanliness in ("clean", "dirty_es"):
        return "valid"               # el camino feliz DEBE producir modelo (no solo rechazar)
    return "any"                     # dirty_encoding/preamble/mixed_units: válido o pregunta clara


@pytest.mark.parametrize("combo", _SUBSET, ids=[c.label() for c in _SUBSET])
def test_f8_e2e_combo(client, combo):
    side = L.SIZES_FAST[combo.size]
    o = L.drive_e2e(client, combo, side=side, grid=6)

    # ── Invariante duro de F8: nunca crash / 5xx pelado / basura silenciosa ──
    assert o.ok, (
        f"{combo.label()} → {o.outcome} @ {o.stage} "
        f"(http={o.http_status}, code={o.code}): {o.detail}"
    )

    # ── Expectativa semántica (que el pipeline INVIERTA en el camino feliz) ──
    exp = _expected(combo)
    if exp == "valid":
        assert o.outcome == "valid_3d_model", (
            f"{combo.label()}: se esperaba modelo 3D válido, salió "
            f"{o.outcome} (code={o.code}): {o.detail}"
        )
    elif exp == "catalogued":
        assert o.outcome == "catalogued_error", (
            f"{combo.label()}: se esperaba rechazo catalogado, salió {o.outcome}"
        )


def test_f8_subset_covers_all_axis_values():
    """Meta-test barato (no invierte): el subconjunto cubre cada valor de cada eje."""
    physics = {c.physics for c in _SUBSET}
    clean = {c.cleanliness for c in _SUBSET}
    sizes = {c.size for c in _SUBSET}
    geos = {c.geo for c in _SUBSET}
    dems = {c.dem for c in _SUBSET}
    assert physics == set(L.PHYSICS), f"faltan físicas: {set(L.PHYSICS) - physics}"
    assert clean == set(L.CLEANLINESS), f"faltan suciedades: {set(L.CLEANLINESS) - clean}"
    assert sizes == set(L.SIZES_FAST), f"faltan tamaños: {set(L.SIZES_FAST) - sizes}"
    assert geos == set(L.GEO), f"faltan geo: {set(L.GEO) - geos}"
    assert dems == set(L.DEM), f"faltan DEM: {set(L.DEM) - dems}"
