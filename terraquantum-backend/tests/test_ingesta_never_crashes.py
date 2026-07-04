"""F2.3 — Contrato "nunca crashea": PROHIBIDO el 500 pelado en ingesta.

Dos capas verificadas:
  1. Handlers globales (main._register_never_crash_handlers): cualquier
     TerraquantumError sin capturar → 422/500 con el payload COMPLETO del
     catálogo ES; cualquier Exception sin capturar → 500 catalogado TQ_INTERNAL
     (mensaje + acción sugerida en español). Jamás {"detail": "Internal
     Server Error"}.
  2. Fuzz básico sobre los endpoints de ingesta: payloads malformados
     (binarios, truncados, NUL, decimales mezclados, preámbulos basura,
     millones de columnas...) → SIEMPRE respuesta estructurada ∈
     {200, 4xx, 500-catalogado}.
"""
import io
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client(raise_exc=False):
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app, raise_server_exceptions=raise_exc)


def _reset_rate_limit():
    from core.rate_limit import limiter
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass


# ── 1. Handlers globales (red transversal) ───────────────────────────────────
def test_global_handler_converts_tq_error_to_catalog_payload():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.errors import CsvValidationError
    from main import _register_never_crash_handlers

    mini = FastAPI()
    _register_never_crash_handlers(mini)

    @mini.get("/boom-catalogado")
    def _boom_cat():
        raise CsvValidationError("CSV_EMPTY")

    r = TestClient(mini, raise_server_exceptions=False).get("/boom-catalogado")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["error"] == "CSV_EMPTY" and d["code"] == "CSV_EMPTY"
    assert len(d["user_message"]) > 100          # contrato F23: ES accionable
    assert len(d["suggested_action"]) >= 40


def test_global_handler_converts_unhandled_exception_to_tq_internal():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from main import _register_never_crash_handlers

    mini = FastAPI()
    _register_never_crash_handlers(mini)

    @mini.get("/boom-pelado")
    def _boom():
        raise RuntimeError("kaboom interno")

    r = TestClient(mini, raise_server_exceptions=False).get("/boom-pelado")
    assert r.status_code == 500
    d = r.json()["detail"]
    assert d["error"] == "TQ_INTERNAL"
    assert "suggested_action" in d and len(d["suggested_action"]) >= 40
    assert d["type"] == "RuntimeError"
    # El texto para el usuario está en español y NO es el 500 pelado.
    assert d["message"] != "Internal Server Error"


# ── 2. Fuzz básico de endpoints de ingesta ───────────────────────────────────
def _fuzz_payloads():
    """Payloads malformados deterministas (seed fija → reproducible)."""
    rng = random.Random(20260703)
    base = "x_m,z_m,bouguer_anomaly,unit,gravity_type\n" + "\n".join(
        f"{i * 100.0},{(i % 5) * 90.0},{1.0 + 0.13 * i},mGal,bouguer_anomaly"
        for i in range(14)
    )
    payloads = [
        b"",                                        # vacío
        b"\x00\x01\x02\xff\xfe" * 200,              # binario puro
        bytes(rng.getrandbits(8) for _ in range(4096)),  # ruido aleatorio
        "solo_una_columna\n1\n2\n3\n".encode(),
        ((",," * 500 + "\n") * 20).encode(),        # comas sin datos
        base.encode()[: len(base) // 2],            # truncado a mitad de fila
        ("col" + ",col" * 9999 + "\n1" + ",1" * 9999).encode(),  # 10k columnas
        ("Proyecto: %$#@!;;;;\n" * 12 + base.replace(",", ";")).encode(),
        base.replace(".", ",").encode(),            # decimales mezclados c/ sep ','
        ("x_m;z_m;g\n1,5;2,5;1,234,567\n" * 14).encode(),  # miles ambiguos
        base.encode("utf-16"),                      # UTF-16 sin avisar
        ("﻿" + base).encode("utf-8"),          # BOM
        (base + "\n😀🌋⛏️,‏עברית‏,1e309,NaN,inf").encode(),  # emoji/RTL/overflow
        ("x_m,z_m,bouguer_anomaly,unit,gravity_type\n" + "\n".join(
            f"{i},{i},{'9' * 400},mGal,bouguer_anomaly" for i in range(14)
        )).encode(),                                # números de 400 dígitos
        b"#TQPKG/1\n#CONFIG {rota sin json\ngarbage,mas,garbage\n1,2,3",
    ]
    return payloads


_INGESTA_ENDPOINTS = [
    ("/gravity-import/preview", "file"),
    ("/v2/gravity-import/analyze-columns", "file"),
    ("/v2/gravity-import/enrich-package", "gravity_file"),
    ("/v2/gravity-import/build-package", "gravity_file"),
]


@pytest.mark.parametrize("endpoint,field", _INGESTA_ENDPOINTS)
def test_fuzz_ingesta_endpoint_never_bare_500(endpoint, field):
    client = _client(raise_exc=False)
    for i, payload in enumerate(_fuzz_payloads()):
        _reset_rate_limit()   # el fuzz no debe medirse contra el rate-limit
        r = client.post(
            endpoint,
            files={field: (f"fuzz_{i}.csv", io.BytesIO(payload), "text/csv")},
        )
        assert r.status_code in (200, 400, 413, 422, 500), (
            f"{endpoint} payload#{i} → HTTP {r.status_code}: {r.text[:300]}"
        )
        body = r.json()
        if r.status_code == 500:
            # 500 permitido SOLO catalogado (nunca el 500 pelado de Starlette).
            detail = body.get("detail")
            assert isinstance(detail, dict) and detail.get("error"), (
                f"{endpoint} payload#{i} → 500 PELADO: {r.text[:300]}"
            )
        else:
            assert body is not None
        # El 500 pelado exacto de Starlette está prohibido SIEMPRE.
        assert body.get("detail") != "Internal Server Error", (
            f"{endpoint} payload#{i} → 500 pelado"
        )
