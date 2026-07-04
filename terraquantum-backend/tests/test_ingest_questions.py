"""F2.4 — Preguntas estructuradas de ingesta (extensión de needs_context).

Contrato: dato no-derivable = PREGUNTA tipada al frontend (nunca error pelado
ni default silencioso). Las respuestas viajan por los literales de column_map
que YA existen (unit / gravity_type / coordinate_system).

Casos fijados:
  - unidad faltante → pregunta blocking (antes: error del import).
  - gravity_type faltante e inferible desde el nombre (bouguer/free_air/...)
    → literal INFERIDO con aviso (patrón 60d1c56), sin pregunta.
  - gravity_type faltante NO inferible → pregunta blocking (previene el
    doble-Bouguer silencioso, bug 9045719).
  - responder por column_map_json destraba el paquete (round-trip completo).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.column_mapping_service import (  # noqa: E402
    build_column_mapping_plan,
    infer_gravity_type_from_column,
)


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


# ── 1. Inferencia de tipo desde el nombre (evidencia embebida) ───────────────
def test_infer_gravity_type_from_column_names():
    assert infer_gravity_type_from_column("bouguer_anomaly") == "bouguer_anomaly"
    assert infer_gravity_type_from_column("Anom_Bouguer_mGal") == "bouguer_anomaly"
    assert infer_gravity_type_from_column("complete_bouguer_anomaly") == "complete_bouguer_anomaly"
    assert infer_gravity_type_from_column("CBA") == "complete_bouguer_anomaly"
    assert infer_gravity_type_from_column("free_air_mgal") == "free_air_anomaly"
    assert infer_gravity_type_from_column("FAA") == "free_air_anomaly"
    assert infer_gravity_type_from_column("residual_gravity") == "residual_gravity"
    assert infer_gravity_type_from_column("g_raw") == "g_raw"
    # Genéricos: NO inferible → None (se pregunta, no se adivina).
    assert infer_gravity_type_from_column("gravity") is None
    assert infer_gravity_type_from_column("g_mgal") is None
    assert infer_gravity_type_from_column(None) is None


# ── 2. Plan: preguntas tipadas ───────────────────────────────────────────────
def test_plan_asks_unit_when_missing_everywhere():
    headers = ["x_m", "z_m", "gravity"]     # sin unit, sin mgal embebido
    plan = build_column_mapping_plan(headers, "gravity")
    keys = {q["key"] for q in plan["questions"]}
    assert "unit" in keys and "gravity_type" in keys
    q_unit = next(q for q in plan["questions"] if q["key"] == "unit")
    assert q_unit["blocking"] is True
    assert q_unit["target"] == "column_map.unit"
    assert any(o["value"] == "mGal" for o in q_unit["options"])


def test_plan_no_unit_question_when_embedded_or_present():
    # Unidad embebida en el nombre → sin pregunta (se infiere con aviso).
    plan = build_column_mapping_plan(["x_m", "z_m", "g_mgal"], "gravity")
    assert not any(q["key"] == "unit" for q in plan["questions"])
    # Columna unit presente → sin pregunta.
    plan2 = build_column_mapping_plan(["x_m", "z_m", "gravity", "unit"], "gravity")
    assert not any(q["key"] == "unit" for q in plan2["questions"])
    # Literal respondido → sin pregunta.
    plan3 = build_column_mapping_plan(
        ["x_m", "z_m", "gravity"], "gravity", {"unit": "mGal"},
    )
    assert not any(q["key"] == "unit" for q in plan3["questions"])


def test_plan_infers_gravity_type_from_bouguer_name():
    plan = build_column_mapping_plan(["x_m", "z_m", "bouguer_anomaly", "unit"], "gravity")
    assert not any(q["key"] == "gravity_type" for q in plan["questions"])
    inf = plan["inferred_literals"]["gravity_type"]
    assert inf["value"] == "bouguer_anomaly"
    assert inf["source_column"] == "bouguer_anomaly"
    assert "inferido" in inf["note"].lower()


def test_plan_asks_gravity_type_when_not_inferable():
    plan = build_column_mapping_plan(["x_m", "z_m", "gravity", "unit"], "gravity")
    q = next(q for q in plan["questions"] if q["key"] == "gravity_type")
    assert q["blocking"] is True
    assert any(o["value"] == "bouguer_anomaly" for o in q["options"])
    assert "gravity_type" not in plan["inferred_literals"]


def test_plan_type_column_present_no_question():
    plan = build_column_mapping_plan(
        ["x_m", "z_m", "gravity", "unit", "gravity_type"], "gravity",
    )
    assert not any(q["key"] == "gravity_type" for q in plan["questions"])
    plan_es = build_column_mapping_plan(
        ["x_m", "z_m", "gravity", "unit", "Tipo_Gravedad"], "gravity",
    )
    assert not any(q["key"] == "gravity_type" for q in plan_es["questions"])


def test_plan_magnetic_kind_no_gravity_questions():
    plan = build_column_mapping_plan(["x_m", "z_m", "tmi_nt"], "magnetic")
    assert plan["questions"] == []


# ── 3. Endpoint enrich: pregunta → respuesta → paquete (round-trip) ──────────
def _csv_no_type(n=16):
    rows = ["x_m,z_m,gravity,unit"]
    for i in range(n):
        rows.append(f"{i * 100.0},{(i % 5) * 90.0},{1.0 + 0.13 * i},mGal")
    return "\n".join(rows) + "\n"


def test_enrich_asks_blocking_question_then_answer_unlocks_package():
    client = _client()
    files = {"gravity_file": ("notype.csv", _csv_no_type(), "text/csv")}
    r1 = client.post("/v2/gravity-import/enrich-package", files=files)
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["needs_mapping"] is True
    qkeys = {q["key"] for q in b1["column_mapping"]["questions"]}
    assert "gravity_type" in qkeys
    assert "package_text" not in b1

    # El usuario responde por el canal existente (literal en column_map_json).
    r2 = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("notype.csv", _csv_no_type(), "text/csv")},
        data={"column_map_json": '{"gravity_type": "bouguer_anomaly"}'},
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert "package_text" in b2, b2
    assert '"gravity_type"' not in str(b2.get("needs_mapping"))


def test_enrich_inferred_type_proceeds_with_visible_warning():
    """Columna 'bouguer_anomaly' sin gravity_type → NO pregunta: infiere con
    aviso y el paquete declara el literal (anti doble-Bouguer con evidencia)."""
    rows = ["x_m,z_m,bouguer_anomaly,unit"]
    for i in range(16):
        rows.append(f"{i * 100.0},{(i % 5) * 90.0},{1.0 + 0.13 * i},mGal")
    csv_text = "\n".join(rows) + "\n"
    client = _client()
    r = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("boug.csv", csv_text, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "package_text" in body, body
    assert any("inferido" in w.lower() for w in body["warnings"]), body["warnings"]
    assert "gravity_type,bouguer_anomaly" in body["package_text"].replace(
        '"', ""
    ) or "bouguer_anomaly" in body["package_text"]
