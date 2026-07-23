"""F7 — Licenciamiento offline Ed25519.

Verifica el round-trip firma/verificación y todos los rechazos (firma alterada,
vencida, otro producto), y que SIN licencia o SIN emisor el modo es local libre
(nunca bloquea). Genera pares de claves efímeros: no depende de la clave real
del emisor.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import license_service as ls

PRODUCT = "terraquantum"


def _payload(tier="pro", expires_delta_days=30, product=PRODUCT):
    now = datetime.now(timezone.utc)
    exp = None if expires_delta_days is None else (now + timedelta(days=expires_delta_days)).isoformat()
    return {
        "product": product,
        "licensee": "Consultora Geofísica SpA",
        "tier": tier,
        "issued_at": now.isoformat(),
        "expires_at": exp,
    }


@pytest.fixture
def keypair():
    return ls.generate_keypair()  # (priv_hex, pub_hex)


def test_valid_license_verifies(keypair):
    priv, pub = keypair
    tok = ls.sign_license(_payload(tier="pro"), priv)
    st = ls.verify_license(tok, pub, product=PRODUCT)
    assert st.valid and st.tier == "pro" and not st.expired
    assert st.licensee == "Consultora Geofísica SpA"


def test_perpetual_license_never_expires(keypair):
    priv, pub = keypair
    tok = ls.sign_license(_payload(tier="pro", expires_delta_days=None), priv)
    st = ls.verify_license(tok, pub, product=PRODUCT)
    assert st.valid and not st.expired


def test_expired_license_rejected(keypair):
    priv, pub = keypair
    tok = ls.sign_license(_payload(expires_delta_days=-1), priv)
    st = ls.verify_license(tok, pub, product=PRODUCT)
    assert not st.valid and st.expired and st.tier == ls.LOCAL_TIER


def test_tampered_signature_rejected(keypair):
    priv, pub = keypair
    tok = ls.sign_license(_payload(), priv)
    tampered = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
    st = ls.verify_license(tampered, pub, product=PRODUCT)
    assert not st.valid


def test_tampered_payload_rejected(keypair):
    """Cambiar el tier en el payload sin re-firmar debe invalidar la firma."""
    priv, pub = keypair
    tok = ls.sign_license(_payload(tier="free"), priv)
    prefix, payload_seg, sig = tok.split(".")
    # Corromper 1 char del payload rompe la firma sobre ese segmento.
    bad_payload = payload_seg[:-2] + ("zz" if not payload_seg.endswith("zz") else "yy")
    st = ls.verify_license(f"{prefix}.{bad_payload}.{sig}", pub, product=PRODUCT)
    assert not st.valid


def test_wrong_product_rejected(keypair):
    priv, pub = keypair
    tok = ls.sign_license(_payload(product="otro-software"), priv)
    st = ls.verify_license(tok, pub, product=PRODUCT)
    assert not st.valid and st.tier == ls.LOCAL_TIER


def test_wrong_public_key_rejected():
    priv_a, _ = ls.generate_keypair()
    _, pub_b = ls.generate_keypair()  # emisor distinto
    tok = ls.sign_license(_payload(), priv_a)
    st = ls.verify_license(tok, pub_b, product=PRODUCT)
    assert not st.valid


def test_no_token_is_local_free(keypair):
    _, pub = keypair
    st = ls.verify_license("", pub, product=PRODUCT)
    assert not st.valid and st.tier == ls.LOCAL_TIER


def test_no_issuer_is_local_free(keypair):
    priv, _ = keypair
    tok = ls.sign_license(_payload(), priv)
    st = ls.verify_license(tok, "", product=PRODUCT)
    assert not st.valid and st.tier == ls.LOCAL_TIER


def test_garbage_token_never_raises(keypair):
    _, pub = keypair
    for junk in ["hola", "a.b", "tqlic1.@@@.###", "tqlic1..", "x" * 500]:
        st = ls.verify_license(junk, pub, product=PRODUCT)
        assert not st.valid  # y no lanzó


def test_public_key_derivation(keypair):
    priv, pub = keypair
    assert ls.public_key_for(priv) == pub


def test_voxel_budget_local_unlimited(monkeypatch):
    """Modo local (sin licencia) no limita vóxeles."""
    monkeypatch.setattr("core.config.TQ_LICENSE_TOKEN", "", raising=False)
    monkeypatch.setattr("core.config.TQ_LICENSE_PUBLIC_KEY_HEX", "", raising=False)
    res = ls.check_voxel_budget(500_000)
    assert res["allowed"] and res["tier"] == ls.LOCAL_TIER


def test_voxel_budget_free_tier_limited(monkeypatch):
    """Con una licencia free activa (por env), el tope de vóxeles aplica."""
    priv, pub = ls.generate_keypair()
    tok = ls.sign_license(_payload(tier="free"), priv)
    monkeypatch.setattr("core.config.TQ_LICENSE_TOKEN", tok, raising=False)
    monkeypatch.setattr("core.config.TQ_LICENSE_PUBLIC_KEY_HEX", pub, raising=False)
    limit = __import__("core.config", fromlist=["TQ_TIER_LIMITS"]).TQ_TIER_LIMITS["free"]["max_voxels"]
    ok = ls.check_voxel_budget(limit)
    over = ls.check_voxel_budget(limit + 1)
    assert ok["allowed"] is True
    assert over["allowed"] is False and str(limit) in over["reason"].replace(",", "")


def test_status_and_activate_endpoints(monkeypatch, tmp_path):
    """GET /license/status y POST /license/activate con una licencia real."""
    from api import license_api

    priv, pub = ls.generate_keypair()
    tok = ls.sign_license(_payload(tier="pro"), priv)
    lic_file = tmp_path / "license.key"
    monkeypatch.setattr("core.config.TQ_LICENSE_TOKEN", "", raising=False)
    monkeypatch.setattr("core.config.TQ_LICENSE_PUBLIC_KEY_HEX", pub, raising=False)
    monkeypatch.setattr("core.config.TQ_LICENSE_FILE", lic_file, raising=False)

    app = FastAPI()
    app.include_router(license_api.router)
    client = TestClient(app)

    # Sin archivo → local libre.
    st = client.get("/license/status").json()
    assert st["mode"] == "local_free" and st["effective_tier"] == ls.LOCAL_TIER

    # Activar una licencia válida → se guarda y el estado pasa a pro.
    act = client.post("/license/activate", json={"token": tok}).json()
    assert act["activated"] is True and act["valid"] is True and act["tier"] == "pro"
    assert lic_file.exists()

    st2 = client.get("/license/status").json()
    assert st2["valid"] is True and st2["effective_tier"] == "pro" and st2["mode"] == "licensed"

    # Activar basura → no activa, no lanza.
    bad = client.post("/license/activate", json={"token": "no-es-licencia"}).json()
    assert bad["activated"] is False and bad["valid"] is False
