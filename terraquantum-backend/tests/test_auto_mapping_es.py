"""F2.2 — Auto-mapeo de columnas ES/EN + heurística por RANGO físico.

Cierra la deuda histórica del plan (auto-mapeo de nombres en español) y fija el
GOTCHA MEDIDO (2026-07-03): la convención interna es x=este, z=norte,
y=PROFUNDIDAD — un northing en la columna 'y' corrompía la geometría EN
SILENCIO. Ahora: (a) el plan de mapeo lo marca como sospecha y PREGUNTA
(confianza media jamás auto-aplica); (b) el import lo bloquea con error claro.

E2E de producto: los CSVs crudos reales del corpus (LdM Excel-ES con preámbulo,
';', coma decimal y headers en español) importan SIN column_map manual.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.column_mapping_service import build_column_mapping_plan  # noqa: E402
from services.gravity_import_service import import_gravity_csv_v1  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CORPUS = os.path.join(FIXTURES, "csv_reales")
LDM_CRUDO = os.path.join(CORPUS, "LdM_gravimetria_CRUDO_usuario.csv")
LDM_DOT_TYPE = os.path.join(CORPUS, "LdM_dot_withType.csv")


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 1. El CSV crudo REAL de LdM importa SIN mapeo manual (la tesis de F2) ────
def test_ldm_crudo_full_auto_import():
    """Preámbulo + ';' + coma decimal + headers ES → import automático completo.

    Antes de F2.2 esto requería column_map manual con los 7 roles; ahora los
    sinónimos ES (Este_UTM/Norte_UTM/Cota_msnm/Estacion) + la unidad embebida
    en 'Anom_Bouguer_mGal' (patrón 60d1c56) resuelven todo con evidencia.
    """
    res = import_gravity_csv_v1(LDM_CRUDO, strict=False, allow_g_raw=True)
    assert res.status == "ok", res.errors
    assert len(res.observations) >= 100
    meta = res.import_metadata
    assert meta.gravity_column_used == "Anom_Bouguer_mGal"
    assert meta.unit_original == "mGal"
    assert any("inferida mGal" in w for w in res.warnings), res.warnings
    # Coordenadas UTM por sinónimos ES → transformadas a metros locales.
    assert res.coordinate_transform.input_coordinate_system == "utm"
    # Elevación (Cota_msnm) y sigma (Error_mGal) capturadas por estación.
    assert res.station_elevations is not None
    assert 1500 < res.station_elevations[0] < 3500
    assert res.station_uncertainties is not None
    # station_id desde 'Estacion' (sin warning de IDs autogenerados).
    assert not any("station_id" in w for w in res.warnings), res.warnings


def test_ldm_dot_with_type_full_auto_import():
    """';' + punto decimal + Tipo_Gravedad (sinónimo ES de gravity_type)."""
    res = import_gravity_csv_v1(LDM_DOT_TYPE, strict=False, allow_g_raw=True)
    assert res.status == "ok", res.errors
    assert res.import_metadata.gravity_type == "bouguer_anomaly"
    assert any("Tipo_Gravedad" in w for w in res.warnings), res.warnings


# ── 2. GOTCHA MEDIDO: northing en el slot de profundidad ─────────────────────
def test_import_blocks_northing_in_depth_slot(tmp_path):
    """y_m con valores ~6e6 (northing UTM) → error CLARO, jamás geometría corrupta."""
    rows = ["x_m,y_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(14):
        rows.append(
            f"{362000 + i * 100.0},{6008000 + i * 50.0},{i * 90.0},"
            f"{-11.0 + 0.1 * i},mGal,bouguer_anomaly"
        )
    res = import_gravity_csv_v1(
        _write(tmp_path, "northing_y.csv", "\n".join(rows) + "\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "error"
    assert any("northing" in e.lower() or "norte" in e.lower() for e in res.errors), res.errors
    assert any("PROFUNDIDAD" in e for e in res.errors)


def test_import_small_depths_unaffected(tmp_path):
    """Profundidades reales (0-400 m) NO disparan la guardia (byte-idéntico)."""
    rows = ["x_m,y_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(14):
        rows.append(f"{i * 100.0},{i * 25.0},{(i % 5) * 90.0},{1.0 + 0.1 * i},mGal,bouguer_anomaly")
    res = import_gravity_csv_v1(
        _write(tmp_path, "depth_ok.csv", "\n".join(rows) + "\n"),
        strict=False, allow_g_raw=True, data_kind="gravity",
    )
    assert res.status == "ok", res.errors


# ── 3. Plan de mapeo: sospechas por rango (media confianza → PREGUNTA) ───────
def _samples_northing_in_y():
    headers = ["x_m", "y_m", "z_m", "bouguer_anomaly", "unit", "gravity_type"]
    samples = {
        "x_m": [str(362000 + i * 100.0) for i in range(20)],
        "y_m": [str(6008000 + i * 50.0) for i in range(20)],
        "z_m": [str(i * 90.0) for i in range(20)],
        "bouguer_anomaly": [str(-11.0 + 0.1 * i) for i in range(20)],
        "unit": ["mGal"] * 20,
        "gravity_type": ["bouguer_anomaly"] * 20,
    }
    return headers, samples


def test_plan_flags_northing_in_depth_slot():
    headers, samples = _samples_northing_in_y()
    plan = build_column_mapping_plan(headers, "gravity", None, sample_values=samples)
    assert plan["needs_mapping"] is False
    assert plan["needs_confirmation"] is True
    assert plan["confidence"] == "medium"
    kinds = {s["kind"] for s in plan["suspicions"]}
    assert "northing_in_depth_slot" in kinds
    susp = next(s for s in plan["suspicions"] if s["kind"] == "northing_in_depth_slot")
    assert susp["column"] == "y_m" and susp["suggested_role"] == "y"
    assert plan["role_confidence"]["depth"] == "medium"


def test_plan_user_override_silences_confirmation():
    """El usuario ya decidió (override explícito) → se reporta pero no re-pregunta."""
    headers, samples = _samples_northing_in_y()
    plan = build_column_mapping_plan(
        headers, "gravity", {"y": "y_m"}, sample_values=samples,
    )
    # y_m pasa al rol norte (z slot); depth queda sin columna → sin sospecha.
    assert plan["needs_confirmation"] is False
    assert plan["roles"]["y"] == "y_m"


def test_plan_without_samples_is_backward_identical():
    headers, _ = _samples_northing_in_y()
    plan = build_column_mapping_plan(headers, "gravity", None)
    assert plan["needs_confirmation"] is False
    assert plan["confidence"] == "high"
    assert plan["suspicions"] == [] and plan["suggestions"] == {}


# ── 4. Sugerencias por rango para headers crípticos (candidato ÚNICO) ────────
def test_plan_suggests_unique_range_candidates():
    headers = ["c1", "c2", "c3"]
    samples = {
        "c1": [str(362000 + i * 100.0) for i in range(20)],   # easting único
        "c2": [str(6008000 + i * 50.0) for i in range(20)],   # northing único
        "c3": [str(-300.0 + i * 0.5) for i in range(20)],     # mGal (fuera de ±180 → no lon)
    }
    plan = build_column_mapping_plan(headers, "gravity", None, sample_values=samples)
    assert plan["needs_mapping"] is True          # nombres no resuelven nada
    sug = plan["suggestions"]
    assert sug["x"]["column"] == "c1"
    assert sug["y"]["column"] == "c2"
    assert sug["gravity_value"]["column"] == "c3"
    assert all(v["confidence"] == "medium" for v in sug.values())


def test_plan_ambiguous_ranges_suggest_nothing():
    """Dos columnas calzan el mismo rol → NO se sugiere (no adivinar)."""
    headers = ["c1", "c2", "c3"]
    samples = {
        "c1": [str(362000 + i * 100.0) for i in range(20)],
        "c2": [str(363000 + i * 100.0) for i in range(20)],   # segundo easting
        "c3": [str(-300.0 + i * 0.5) for i in range(20)],
    }
    plan = build_column_mapping_plan(headers, "gravity", None, sample_values=samples)
    assert "x" not in plan["suggestions"]


# ── 5. Endpoints: la heurística viaja al frontend ────────────────────────────
def _csv_text_northing_in_y():
    rows = ["x_m,y_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(20):
        rows.append(
            f"{362000 + i * 100.0},{6008000 + i * 50.0},{i * 90.0},"
            f"{-11.0 + 0.1 * i},mGal,bouguer_anomaly"
        )
    return "\n".join(rows) + "\n"


def test_analyze_columns_returns_suspicions_and_sniff():
    client = _client()
    r = client.post(
        "/v2/gravity-import/analyze-columns",
        files={"file": ("northing_y.csv", _csv_text_northing_in_y(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    plan = body["column_mapping"]
    assert plan["needs_confirmation"] is True
    assert any(s["kind"] == "northing_in_depth_slot" for s in plan["suspicions"])
    assert body["sniff_report"]["separator"]["value"] == ","


def test_enrich_package_asks_confirmation_then_proceeds_with_override():
    client = _client()
    files = {"gravity_file": ("northing_y.csv", _csv_text_northing_in_y(), "text/csv")}
    # 1) Sin mapeo → el endpoint PREGUNTA (needs_confirmation, sin paquete).
    r1 = client.post("/v2/gravity-import/enrich-package", files=files)
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["needs_mapping"] is True and b1.get("needs_confirmation") is True
    assert "package_text" not in b1
    # 2) El usuario corrige (y_m → rol norte) → el paquete se genera.
    r2 = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("northing_y.csv", _csv_text_northing_in_y(), "text/csv")},
        data={"column_map_json": '{"x": "x_m", "y": "y_m", "gravity_type": "bouguer_anomaly"}'},
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert "package_text" in b2, b2
    assert b2["sniff_report"] is not None
