"""Tests for core.gee_client — verifies safe initialization and graceful degradation."""

import json
import pytest


def test_init_gee_missing_file_leaves_unavailable(tmp_path, monkeypatch):
    """init_gee() with a non-existent credentials path must not raise and must leave is_available() False."""
    import core.gee_client as gee_module

    monkeypatch.setattr(gee_module, "_gee_available", False)
    monkeypatch.setenv("GEE_CREDENTIALS_PATH", str(tmp_path / "no_such_file.json"))

    gee_module.init_gee()

    assert gee_module.is_available() is False


def test_init_gee_invalid_json_leaves_unavailable(tmp_path, monkeypatch):
    """init_gee() with malformed JSON must not raise and must leave is_available() False."""
    import core.gee_client as gee_module

    bad_creds = tmp_path / "bad.json"
    bad_creds.write_text("NOT VALID JSON", encoding="utf-8")

    monkeypatch.setattr(gee_module, "_gee_available", False)
    monkeypatch.setenv("GEE_CREDENTIALS_PATH", str(bad_creds))

    gee_module.init_gee()

    assert gee_module.is_available() is False


def test_init_gee_missing_client_email_leaves_unavailable(tmp_path, monkeypatch):
    """init_gee() with JSON lacking client_email must not raise and must leave is_available() False."""
    import core.gee_client as gee_module

    no_email = tmp_path / "no_email.json"
    no_email.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")

    monkeypatch.setattr(gee_module, "_gee_available", False)
    monkeypatch.setenv("GEE_CREDENTIALS_PATH", str(no_email))

    gee_module.init_gee()

    assert gee_module.is_available() is False


def test_init_gee_invalid_credentials_rejected_by_ee(tmp_path, monkeypatch):
    """init_gee() with syntactically valid but wrong credentials must not raise."""
    import core.gee_client as gee_module

    fake_creds = tmp_path / "fake.json"
    fake_creds.write_text(
        json.dumps({"type": "service_account", "client_email": "fake@fake.iam.gserviceaccount.com"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(gee_module, "_gee_available", False)
    monkeypatch.setenv("GEE_CREDENTIALS_PATH", str(fake_creds))

    # Must not raise regardless of GEE rejection
    gee_module.init_gee()

    # Credentials are invalid so GEE will reject; result must be False
    assert gee_module.is_available() is False


def test_is_available_reflects_module_state(monkeypatch):
    """is_available() must directly reflect the _gee_available module variable."""
    import core.gee_client as gee_module

    monkeypatch.setattr(gee_module, "_gee_available", False)
    assert gee_module.is_available() is False

    monkeypatch.setattr(gee_module, "_gee_available", True)
    assert gee_module.is_available() is True
