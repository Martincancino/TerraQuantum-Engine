"""F2.6(a) — Corpus REAL paramétrico: los 18 fixtures de csv_reales/.

GATE F2: el 100% del corpus llega a TQPKG válido o a PREGUNTA clara — nunca
crash, nunca 500 pelado, nunca corrupción silenciosa. El corpus son los
archivos REALES que motivaron F2 (LdM crudos Excel-ES con preámbulo y coma
decimal, DO-27, multi-física, TQPKG), movidos a fixtures en F1 ("son ORO").

Ruta por tipo:
  - gravimetría / joint → POST /v2/gravity-import/enrich-package (el camino
    dorado de preparación) → package_text.
  - magnetometría → ídem con data_type=magnetic.
  - sondajes → POST /borehole/parse-csv → intervalos válidos.
  - .tqpkg → parse_package_text + re-import del cuerpo (round-trip del paquete).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "csv_reales"
)


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def _post_enrich(client, filename, data_type="gravity"):
    with open(os.path.join(CORPUS, filename), "rb") as fh:
        content = fh.read()
    field = "magnetic_file" if data_type == "magnetic" else "gravity_file"
    return client.post(
        "/v2/gravity-import/enrich-package",
        files={field: (filename, content, "text/csv")},
        data={"data_type": data_type} if data_type == "magnetic" else {},
    )


# Todos los CSV gravimétricos/joint del corpus DEBEN llegar a paquete completo
# (tras F2.1-F2.4: sniffer + auto-mapeo ES + inferencia de tipo con aviso).
_GRAVITY_FILES = [
    "LdM_gravimetria_CRUDO_usuario.csv",       # preámbulo + ';' + coma decimal + ES
    "LdM_gravimetria_CRUDO_v2_sinpreambulo.csv",
    "LdM_dot_noType.csv",                      # ';' + punto decimal, sin tipo
    "LdM_dot_withType.csv",                    # ';' + Tipo_Gravedad (ES)
    "LdM_ENRICHED_GOOD.csv",                   # TQPKG re-subido como CSV
    "do27_gravity_LISTO.csv",
    "do27_gravity_LISTO_coarse.csv",
    "do27_gravity_LISTO_mini.csv",
    "laguna_del_maule_gravimetria.csv",
    "laguna_del_maule_joint_demo.csv",         # grav + mag co-localizado
    "multi_gravimetria.csv",
    "prueba_gravimetria_LISTO.csv",
]

_MAGNETIC_FILES = [
    "multi_magnetometria.csv",
    "laguna_del_maule_magnetometria_demo.csv",
]

_TQPKG_FILES = [
    "prueba_gravimetria.tqpkg",
    "prueba_gravimetria_v2.tqpkg",
    "prueba_gravimetria_v3.tqpkg",
]

_BOREHOLE_FILES = ["multi_sondajes.csv"]


def test_corpus_is_fully_covered():
    """Ningún archivo del corpus queda fuera de este test paramétrico."""
    listed = set(_GRAVITY_FILES + _MAGNETIC_FILES + _TQPKG_FILES + _BOREHOLE_FILES)
    actual = {f for f in os.listdir(CORPUS) if not f.startswith(".")}
    assert actual == listed, (
        f"Corpus desincronizado. Faltan en el test: {actual - listed}; "
        f"sobran en el test: {listed - actual}"
    )


@pytest.mark.parametrize("filename", _GRAVITY_FILES)
def test_corpus_gravity_reaches_package(filename):
    r = _post_enrich(_client(), filename)
    assert r.status_code == 200, f"{filename} → HTTP {r.status_code}: {r.text[:400]}"
    body = r.json()
    if "package_text" not in body:
        # Única alternativa aceptable: PREGUNTA clara (nunca error mudo).
        assert body.get("needs_mapping") or body.get("needs_confirmation"), body
        plan = body.get("column_mapping") or {}
        assert plan.get("questions") or plan.get("missing_required") or plan.get(
            "suspicions"
        ), f"{filename}: sin paquete y sin pregunta clara: {body}"
        pytest.fail(
            f"{filename} pidió mapeo en vez de llegar a paquete: "
            f"missing={plan.get('missing_required')} questions="
            f"{[q['key'] for q in plan.get('questions', [])]}"
        )
    # Paquete válido: round-trips por el parser oficial.
    from services.csv_package_service import parse_package_text

    parsed = parse_package_text(body["package_text"])
    assert parsed.plan.get("route"), f"{filename}: paquete sin ruta"
    assert body["n_stations"] >= 10
    assert body.get("sniff_report") is not None


@pytest.mark.parametrize("filename", _MAGNETIC_FILES)
def test_corpus_magnetic_reaches_package(filename):
    r = _post_enrich(_client(), filename, data_type="magnetic")
    assert r.status_code == 200, f"{filename} → HTTP {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert "package_text" in body, f"{filename}: {body}"
    assert body["n_stations"] >= 10


@pytest.mark.parametrize("filename", _TQPKG_FILES)
def test_corpus_tqpkg_roundtrip(filename):
    """Los .tqpkg del corpus parsean y su cuerpo re-importa limpio."""
    from services.csv_package_service import parse_package_text
    from services.gravity_import_service import import_gravity_csv_v1

    with open(os.path.join(CORPUS, filename), "rb") as fh:
        text = fh.read().decode("utf-8", errors="replace")
    parsed = parse_package_text(text)
    assert parsed.plan.get("route")
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(parsed.body_csv)
        tmp_path = tmp.name
    try:
        res = import_gravity_csv_v1(
            tmp_path, strict=False, allow_g_raw=True, data_kind="gravity",
        )
        assert res.status == "ok", f"{filename}: {res.errors}"
        assert len(res.observations) >= 10
    finally:
        os.unlink(tmp_path)


@pytest.mark.parametrize("filename", _BOREHOLE_FILES)
def test_corpus_boreholes_parse(filename):
    client = _client()
    with open(os.path.join(CORPUS, filename), encoding="utf-8") as fh:
        csv_text = fh.read()
    r = client.post("/borehole/parse-csv", json={"csv_text": csv_text})
    assert r.status_code == 200, f"{filename} → HTTP {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert body["n_holes"] >= 1, body
    assert body["n_samples"] >= 1, body
