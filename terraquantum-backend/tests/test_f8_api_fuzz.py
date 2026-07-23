"""F8 — Fuzzing de la API (dep-free, sin schemathesis).

El plan nombra schemathesis; la regla del repo prohíbe deps nuevas sin permiso,
así que este es un fuzzer PROPIO, determinista, del mismo contrato: golpear la
superficie de ENTRADA de datos con payloads malformados/adversariales y verificar
el invariante de F2 ("nunca un 500 pelado"):

    toda respuesta ∈ {<500}  O  {5xx CON envoltura catalogada ES}
    y el cliente NUNCA lanza una excepción.

Un 5xx sin `detail.code` + `detail.user_message` (o un crash del handler) = BUG.
No dispara inversiones: los inputs basura se rechazan en parseo/validación → 4xx.
"""
import json
import os
import sys
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _assert_never_bare_5xx(resp, ctx: str):
    """El contrato transversal: ni 500 pelado ni crash. 5xx SOLO con envoltura ES."""
    if resp.status_code < 500:
        return  # 2xx / 4xx catalogado → OK
    # 5xx permitido únicamente si trae la envoltura catalogada (code + user_message).
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"[{ctx}] 5xx con cuerpo no-JSON: {resp.status_code} {resp.text[:200]} ({exc})")
    detail = body.get("detail", body) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        pytest.fail(f"[{ctx}] 5xx sin envoltura (detail no es dict): {resp.text[:200]}")
    code = detail.get("code") or detail.get("error")
    msg = detail.get("user_message") or detail.get("message")
    assert code, f"[{ctx}] 5xx sin código de catálogo: {resp.text[:200]}"
    assert msg, f"[{ctx}] 5xx sin user_message en español: {resp.text[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# Corpus de payloads malformados (determinista)
# ─────────────────────────────────────────────────────────────────────────────
_BAD_BYTES = {
    "empty": b"",
    "non_utf8": b"\xff\xfe\x00\x01\x80\x81 garbage \xc0\xc1",
    "null_bytes": b"lat,lon,g\x00\x00\n1,2,3\x00\n",
    "binary_png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(60)),
    "html": b"<!doctype html><html><body>no soy csv</body></html>",
    "json_as_csv": b'{"lat": 1, "lon": 2, "g": 3}',
    "one_giant_field": b"col\n" + (b"9" * 200_000) + b"\n",
    "only_header": b"lat,lon,elev_m,bouguer_anomaly,unit,gravity_type\n",
    "ragged": b"a,b,c\n1,2\n3,4,5,6,7,8\n,,\nx,y,z\n",
    "inf_nan_text": b"x_m,z_m,bouguer_anomaly,unit\n0,0,inf,mGal\n1,1,-nan,mGal\n2,2,1e400,mGal\n",
    "wrong_delim_mix": b"x_m;z_m,bouguer_anomaly|unit\n0;0,1|mGal\n",
    "unicode_soup": "x_m,z_m,g\n0,0,½\n1,1,‮​\nΩ,≈,∞\n".encode("utf-8"),
}

_BAD_FORMS = {
    "config_not_json": {"config_json": "{not json"},
    "config_is_array": {"config_json": "[1,2,3]"},
    "config_nested_bomb": {"config_json": json.dumps({"a": {"b": {"c": [1] * 1000}}})},
    "config_huge_grid": {"config_json": json.dumps({"nx": 10**9, "ny": 10**9, "nz": 10**9})},
    "config_negative_grid": {"config_json": json.dumps({"nx": -5, "ny": 0, "nz": -1})},
    "boreholes_not_json": {"boreholes_json": "<xml/>"},
    "boreholes_wrong_shape": {"boreholes_json": json.dumps([{"nope": 1}, "string", 42])},
    "helmert_garbage": {"helmert_control_points_json": json.dumps({"points": "no-list"})},
    "helmert_one_point": {"helmert_control_points_json": json.dumps(
        {"points": [{"local_x": 0, "local_z": 0, "real_e": 1, "real_n": 1}]})},
}

# IDs adversariales para endpoints con path param (traversal / inyección).
_BAD_IDS = [
    "../../etc/passwd", "..\\..\\windows\\system32", "%2e%2e%2f%2e%2e%2f",
    "'; DROP TABLE runs;--", "\x00null", "a" * 500, "..", ".", " ", "run/../..",
    "<script>", "${jndi:ldap://x}", "con", "nul",
]
_BAD_ID_LABELS = [f"id{i}" for i in range(len(_BAD_IDS))]


# ─────────────────────────────────────────────────────────────────────────────
# Fuzz: enrich-package (la puerta de entrada de datos)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,payload", list(_BAD_BYTES.items()), ids=list(_BAD_BYTES))
def test_fuzz_enrich_bad_file_bytes(client, name, payload):
    r = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("fuzz.csv", payload, "text/csv")},
    )
    _assert_never_bare_5xx(r, f"enrich/bytes/{name}")


@pytest.mark.parametrize("name,data", list(_BAD_FORMS.items()), ids=list(_BAD_FORMS))
def test_fuzz_enrich_bad_form(client, name, data):
    # CSV mínimo válido + form malformado → el error debe ser claro, no un crash.
    good = b"x_m,z_m,bouguer_anomaly,unit,gravity_type\n0,0,1,mGal,bouguer_anomaly\n1,1,2,mGal,bouguer_anomaly\n"
    r = client.post(
        "/v2/gravity-import/enrich-package",
        files={"gravity_file": ("ok.csv", good, "text/csv")},
        data=data,
    )
    _assert_never_bare_5xx(r, f"enrich/form/{name}")


def test_fuzz_enrich_no_file_at_all(client):
    r = client.post("/v2/gravity-import/enrich-package")
    _assert_never_bare_5xx(r, "enrich/nofile")


@pytest.mark.parametrize("dt", ["", "GRAVITY", "sismica", "1", "null", "../x"])
def test_fuzz_enrich_bad_data_type(client, dt):
    good = b"x_m,z_m,bouguer_anomaly,unit\n0,0,1,mGal\n1,1,2,mGal\n"
    r = client.post(
        "/v2/gravity-import/enrich-package",
        params={"data_type": dt},
        files={"file": ("ok.csv", good, "text/csv")},
    )
    _assert_never_bare_5xx(r, f"enrich/dtype/{dt!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Fuzz: load-package
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,payload", list(_BAD_BYTES.items()), ids=list(_BAD_BYTES))
def test_fuzz_load_package_bad_bytes(client, name, payload):
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("fuzz.csv", payload, "text/csv")},
        data={"sync": "true"},
    )
    _assert_never_bare_5xx(r, f"load/bytes/{name}")


@pytest.mark.parametrize("bad_id", _BAD_IDS, ids=_BAD_ID_LABELS)
def test_fuzz_load_package_bad_ids(client, bad_id):
    good = b"x_m,z_m,bouguer_anomaly,unit,gravity_type\n0,0,1,mGal,bouguer_anomaly\n1,1,2,mGal,bouguer_anomaly\n"
    r = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("ok.csv", good, "text/csv")},
        data={"project_id": bad_id, "run_id": bad_id, "sync": "false"},
    )
    _assert_never_bare_5xx(r, f"load/id/{bad_id!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Fuzz: endpoints GET con path param (traversal / IDs basura)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad_id", _BAD_IDS, ids=_BAD_ID_LABELS)
def test_fuzz_block_model_csv_bad_ids(client, bad_id):
    # URL-encode: un cliente real codifica el segmento (los chars de control como
    # \x00 ni siquiera forman URL sin codificar) → el SERVIDOR recibe y sanea.
    seg = urllib.parse.quote(bad_id, safe="")
    r = client.get(f"/export/block-model-csv/{seg}/{seg}")
    _assert_never_bare_5xx(r, f"block-model/{bad_id!r}")
    # Nunca debe filtrar un archivo del sistema: si responde 200, es CSV del modelo.
    if r.status_code == 200:
        ct = r.headers.get("content-type", "")
        assert "csv" in ct, f"200 no-CSV en block-model con id {bad_id!r}: {ct}"


@pytest.mark.parametrize("bad_id", _BAD_IDS, ids=_BAD_ID_LABELS)
def test_fuzz_geophysics_status_bad_ids(client, bad_id):
    seg = urllib.parse.quote(bad_id, safe="")
    r = client.get(f"/geophysics-status/{seg}/{seg}")
    _assert_never_bare_5xx(r, f"status/{bad_id!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Fuzz: parse-rows / analyze-columns (parsers directos)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,payload", list(_BAD_BYTES.items()), ids=list(_BAD_BYTES))
def test_fuzz_parse_rows(client, name, payload):
    r = client.post(
        "/v2/gravity-import/parse-rows",
        files={"file": ("fuzz.csv", payload, "text/csv")},
    )
    _assert_never_bare_5xx(r, f"parse-rows/{name}")


@pytest.mark.parametrize("name,payload", list(_BAD_BYTES.items()), ids=list(_BAD_BYTES))
def test_fuzz_analyze_columns(client, name, payload):
    r = client.post(
        "/v2/gravity-import/analyze-columns",
        files={"file": ("fuzz.csv", payload, "text/csv")},
    )
    _assert_never_bare_5xx(r, f"analyze-columns/{name}")
