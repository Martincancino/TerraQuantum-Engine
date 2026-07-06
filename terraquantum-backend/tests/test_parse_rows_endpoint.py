"""F2 cierre de deuda — POST /v2/gravity-import/parse-rows.

El wizard de correcciones parseaba CSV en TypeScript (split+parseFloat):
con decimal-coma, parseFloat("362472,4")=362472 EN SILENCIO — la misma clase
de corrupción del bug e7d2858 pero en el cliente. Este endpoint entrega las
filas COMPLETAS ya parseadas por el pipeline oficial (sniffer incluido) con
valores canónicos (punto decimal), y el frontend deja de parsear.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "csv_reales"
)


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _post(client, name, payload, max_rows=None):
    params = {"max_rows": max_rows} if max_rows else {}
    return client.post(
        "/v2/gravity-import/parse-rows",
        files={"file": (name, payload, "text/csv")},
        params=params,
    )


def test_excel_es_semicolon_comma_decimal_rows_come_back_canonical():
    """El caso del bug: ';' + coma decimal → valores canónicos con PUNTO."""
    with open(os.path.join(CORPUS, "LdM_gravimetria_CRUDO_usuario.csv"), "rb") as fh:
        payload = fh.read()
    r = _post(_client(), "ldm_crudo.csv", payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["headers"][:3] == ["Estacion", "Este_UTM", "Norte_UTM"]
    assert body["n_rows"] >= 100 and body["truncated"] is False
    row0 = body["rows"][0]
    # 362472,4 del archivo → "362472.4" canónico (el cliente puede parseFloat).
    assert abs(float(row0["Este_UTM"]) - 362472.4) < 1e-3, row0
    assert abs(float(row0["Anom_Bouguer_mGal"]) - (-11.5534)) < 1e-3, row0
    assert body["sniff_report"]["separator"]["value"] == ";"
    assert body["sniff_report"]["decimal"]["value"] == ","


def test_clean_csv_all_rows():
    rows = ["lat,lon,elev_m,g_obs_mgal"]
    for i in range(25):
        rows.append(f"{-27.1 - i * 0.001:.4f},{-69.3:.4f},{1500 + i},{978000.0 + i * 0.5:.3f}")
    r = _post(_client(), "clean.csv", "\n".join(rows) + "\n")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_rows"] == 25
    assert abs(float(body["rows"][3]["g_obs_mgal"]) - 978001.5) < 1e-6


def test_max_rows_truncates_with_flag():
    rows = ["a,b"] + [f"{i},{i * 2.5}" for i in range(40)]
    r = _post(_client(), "big.csv", "\n".join(rows) + "\n", max_rows=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_rows"] == 10 and body["truncated"] is True


def test_garbage_is_422_catalogued_never_500():
    r = _post(_client(), "junk.csv", b"\x00\x01\x02" * 50)
    assert r.status_code in (200, 422), r.text
    if r.status_code == 422:
        assert r.json()["detail"]["error"] == "CSV_NO_HEADERS"
