"""BUG doble-Bouguer (corrupción silenciosa) — gravity_type como LITERAL.

Un dato ya reducido a Bouguer, sin columna de gravity_type, se re-reducía
(lat+FAC+Bouguer) → g≈−979 mGal, HTTP 200 "derived", sin aviso. La lógica de "ya
corregido" YA existía (csv_enrichment_service._FIELD_ALREADY_CORRECTED) pero
meta.gravity_type sólo se llenaba desde una COLUMNA; no había forma de declararlo
como literal sin inventar una columna.

Fix: column_map["gravity_type"] acepta un VALOR del catálogo (ej. "bouguer_anomaly")
y puebla meta.gravity_type → el enriquecimiento SALTA la re-reducción.

INVARIANTE: la ingesta entrega dato LIMPIO o un ERROR CLARO, nunca un número
silenciosamente equivocado. Sin el literal → comportamiento histórico byte-idéntico.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.csv_enrichment_service import (  # noqa: E402
    STATUS_ALREADY_PRESENT,
    STATUS_DERIVED,
    enrich_package,
)
from services.gravity_import_service import import_gravity_csv_v1  # noqa: E402


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _already_bouguer_csv(n=14):
    """CSV ya-Bouguer SIN columna gravity_type (coords legacy x_m/z_m)."""
    rows = ["station_id,x_m,z_m,g"]
    for i in range(n):
        rows.append(f"ST-{i:03d},{i*100.0},{(i % 5)*90.0},{-11.0 - 0.13 * i}")
    return "\n".join(rows) + "\n"


# ── (a) literal "bouguer_anomaly" → puebla meta.gravity_type (sin columna) ─────
def test_literal_gravity_type_populates_metadata(tmp_path):
    path = _write(tmp_path, "boug.csv", _already_bouguer_csv())
    res = import_gravity_csv_v1(
        path, strict=False, allow_g_raw=True, data_kind="gravity",
        column_map={"gravity_value": "g", "unit": "mGal",
                    "gravity_type": "bouguer_anomaly"},
    )
    assert res.status == "ok", res.errors
    assert res.import_metadata.gravity_type == "bouguer_anomaly"


# ── (b) SIN el literal → histórico (gravity_type no se fuerza) ─────────────────
def test_without_literal_is_historic(tmp_path):
    path = _write(tmp_path, "boug.csv", _already_bouguer_csv())
    res = import_gravity_csv_v1(
        path, strict=False, allow_g_raw=True, data_kind="gravity",
        column_map={"gravity_value": "g", "unit": "mGal"},
    )
    assert res.status == "ok", res.errors
    # Histórico: sin columna ni literal de tipo, no se fuerza → vacío/None.
    assert not (res.import_metadata.gravity_type or "")


# ── (c) literal inválido → ERROR claro, no basura ─────────────────────────────
def test_invalid_literal_is_clear_error(tmp_path):
    path = _write(tmp_path, "boug.csv", _already_bouguer_csv())
    res = import_gravity_csv_v1(
        path, strict=False, allow_g_raw=True, data_kind="gravity",
        column_map={"gravity_value": "g", "unit": "mGal",
                    "gravity_type": "no_es_un_tipo"},
    )
    assert res.status == "error"
    assert any("no es un tipo válido" in e for e in res.errors), res.errors


# ── (d/e) Consecuencia E2E en el enriquecimiento: literal evita doble Bouguer ──
def _primary_already_bouguer(gravity_type, n=12, g_mgal=-11.0, elev_m=2000.0):
    """Stub de import (estilo test_csv_enrichment) con lat/lon Chile + elevación."""
    obs = [
        SimpleNamespace(x_m=float(i * 100), y_m=0.0, z_m=float((i % 4) * 100),
                        g=g_mgal * 1e-5)
        for i in range(n)
    ]
    latlon = [
        {"lat_deg": -36.0 - 0.001 * i, "lon_deg": -70.5 + 0.001 * i, "elev_m": elev_m}
        for i in range(n)
    ]
    return SimpleNamespace(
        observations=obs,
        raw_latlon_elev=latlon,
        station_elevations=[elev_m] * n,
        station_uncertainties=None,
        magnetic_values=None,
        coordinate_transform=None,
        import_metadata=SimpleNamespace(gravity_type=gravity_type),
        csv_analysis=None,
        warnings=[],
    )


def _grav_step(result):
    return next(s for s in result.steps if s.key == "gravity_corrections")


def test_literal_skips_rereduction_no_double_bouguer():
    """gravity_type='bouguer_anomaly' (vía literal) → enrich NO re-reduce."""
    primary = _primary_already_bouguer("bouguer_anomaly")
    result = asyncio.run(enrich_package(
        primary, data_type="gravity", config={}, enable_dem=False,
    ))
    step = _grav_step(result)
    assert step.status == STATUS_ALREADY_PRESENT, step.detail
    assert result.g_mgal is None  # no se sobre-escribió con un re-reducido


def test_missing_type_triggers_double_bouguer_historic():
    """Sin tipo declarado → enrich re-reduce (el bug): g se desplaza ~cientos de mGal."""
    primary = _primary_already_bouguer(None)
    result = asyncio.run(enrich_package(
        primary, data_type="gravity", config={}, enable_dem=False,
    ))
    step = _grav_step(result)
    assert step.status == STATUS_DERIVED, step.detail
    mean_corr = sum(result.g_mgal) / len(result.g_mgal)
    # El dato original era ~-11 mGal; la re-reducción a 2000 m lo desplaza enormemente.
    assert abs(mean_corr - (-11.0)) > 100.0, mean_corr
