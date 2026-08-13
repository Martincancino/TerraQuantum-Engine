"""
R3-INTEGRATION — Tests para _run_r3_post_inversion_enrichment en gravity_import_api.

Verifica que después de una inversión exitosa se ejecute automáticamente:
  1. get_terrain_data(project_id)
  2. enrich_block_model_with_elevation(project_id, run_id)

Con guardrails por nivel de georef_confidence:
  HIGH/MEDIUM → ambas funciones llamadas
  LOW         → ambas llamadas + warning conservador sobre lat/lon
  MISSING     → ninguna llamada, attempted=False

Todos los tests usan monkeypatch; no ejecutan inversión pesada ni tocan data real.
"""
import json
from pathlib import Path

import pytest

from services import block_model_store as store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    """Redirige PROJECTS_DIR a tmp_path para aislamiento total."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def _create_terrain_files(projects_dir: Path, project_id: str) -> None:
    """Crea terrain_metadata.json y terrain_dem_matrix.json de prueba."""
    proj_dir = projects_dir / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "terrain_metadata.json").write_text(
        json.dumps({"georef_confidence": "HIGH", "source": "mock_v1",
                    "extent_x_m": 1000.0, "extent_z_m": 1000.0}),
        encoding="utf-8",
    )
    (proj_dir / "terrain_dem_matrix.json").write_text(
        json.dumps([[3000.0] * 4] * 4), encoding="utf-8"
    )


def _enrich_ok(*args, **kwargs) -> dict:
    return {"status": "ok", "has_elevation_data": True, "warnings": []}


def _enrich_raise(*args, **kwargs):
    raise RuntimeError("enrichment simulado falla")


# ── 1. MISSING → no calls, attempted=False ────────────────────────────────────

def test_missing_georef_skips_all(patched_projects_dir, monkeypatch):
    """MISSING → attempted=False, get_terrain_data y enrich NO se llaman."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    terrain_calls: list = []
    enrich_calls: list = []
    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: terrain_calls.append(1))
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", lambda *a, **kw: enrich_calls.append(1))

    result = _run_r3_post_inversion_enrichment("proj_miss", "run_miss", "MISSING")

    assert result["attempted"] is False
    assert result["terrain_persisted"] is False
    assert result["enrichment_attempted"] is False
    assert result["enrichment_status"] is None
    assert result["has_elevation_data"] is False
    assert len(terrain_calls) == 0
    assert len(enrich_calls) == 0
    assert any("ausente" in w.lower() for w in result["warnings"]), (
        f"Se esperaba warning de georef ausente; got: {result['warnings']}"
    )


def test_none_georef_treated_as_missing(patched_projects_dir, monkeypatch):
    """georef_confidence=None debe comportarse igual que MISSING."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    terrain_calls: list = []
    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: terrain_calls.append(1))
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", lambda *a, **kw: None)

    result = _run_r3_post_inversion_enrichment("proj_none", "run_none", None)

    assert result["attempted"] is False
    assert len(terrain_calls) == 0


# ── 2. HIGH → ambas funciones llamadas, enrichment_status ok ─────────────────

def test_high_georef_calls_terrain_and_enrich(patched_projects_dir, monkeypatch):
    """HIGH → get_terrain_data y enrich llamados; terrain_persisted=True, status ok."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_high")

    terrain_calls: list = []
    enrich_calls: list = []

    def mock_terrain(project_id, **kwargs):
        terrain_calls.append(project_id)

    def mock_enrich(project_id, run_id, **kwargs):
        enrich_calls.append((project_id, run_id))
        return {"status": "ok", "has_elevation_data": True, "warnings": []}

    monkeypatch.setattr(api_mod, "get_terrain_data", mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", mock_enrich)

    result = _run_r3_post_inversion_enrichment("proj_high", "run_high", "HIGH")

    assert result["attempted"] is True
    assert result["terrain_persisted"] is True
    assert result["enrichment_attempted"] is True
    assert result["enrichment_status"] == "ok"
    assert result["has_elevation_data"] is True
    assert len(terrain_calls) == 1
    assert len(enrich_calls) == 1
    assert terrain_calls[0] == "proj_high"
    assert enrich_calls[0] == ("proj_high", "run_high")


# ── 3. MEDIUM → igual que HIGH ───────────────────────────────────────────────

def test_medium_georef_calls_both_services(patched_projects_dir, monkeypatch):
    """MEDIUM → igual comportamiento que HIGH."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_med")

    terrain_calls: list = []
    enrich_calls: list = []

    def mock_terrain(project_id, **kwargs):
        terrain_calls.append(project_id)

    def mock_enrich(project_id, run_id, **kwargs):
        enrich_calls.append(1)
        return {"status": "ok", "has_elevation_data": True, "warnings": []}

    monkeypatch.setattr(api_mod, "get_terrain_data", mock_terrain)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", mock_enrich)

    result = _run_r3_post_inversion_enrichment("proj_med", "run_med", "MEDIUM")

    assert result["attempted"] is True
    assert result["terrain_persisted"] is True
    assert result["enrichment_attempted"] is True
    assert result["enrichment_status"] == "ok"
    assert len(terrain_calls) == 1
    assert len(enrich_calls) == 1


# ── 4. LOW → ambas llamadas + warning conservador ────────────────────────────

def test_low_georef_calls_both_with_conservative_warning(patched_projects_dir, monkeypatch):
    """LOW → ambas funciones llamadas + warning conservador sobre lat/lon."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_low")

    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: None)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _enrich_ok)

    result = _run_r3_post_inversion_enrichment("proj_low", "run_low", "LOW")

    assert result["attempted"] is True
    assert result["enrichment_attempted"] is True
    lat_lon_warning = any("lat/lon" in w.lower() for w in result["warnings"])
    assert lat_lon_warning, (
        f"Se esperaba warning conservador sobre lat/lon para LOW; got: {result['warnings']}"
    )


# ── 5. get_terrain_data falla → no crash, terrain_persisted=False ────────────

def test_terrain_failure_no_crash_warning_added(patched_projects_dir, monkeypatch):
    """Si get_terrain_data lanza excepción → no crash, terrain_persisted=False, warning."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    def terrain_fail(*a, **kw):
        raise ConnectionError("GEE no disponible")

    monkeypatch.setattr(api_mod, "get_terrain_data", terrain_fail)
    # Sin terrain files → enrichment skipped
    # (patched_projects_dir no tiene terrain files para proj_tf)

    result = _run_r3_post_inversion_enrichment("proj_tf", "run_tf", "HIGH")

    assert result["attempted"] is True
    assert result["terrain_persisted"] is False
    assert any(
        "terrain" in w.lower() or "falló" in w.lower() for w in result["warnings"]
    ), f"Se esperaba warning de terrain fallo; got: {result['warnings']}"


def test_terrain_failure_but_existing_files_still_enriches(patched_projects_dir, monkeypatch):
    """Si terrain falla pero DEM files ya existen → enrichment igual se ejecuta."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_tef")

    def terrain_fail(*a, **kw):
        raise RuntimeError("GEE falla simulada")

    enrich_calls: list = []

    def mock_enrich(*a, **kw):
        enrich_calls.append(1)
        return {"status": "ok", "has_elevation_data": True, "warnings": []}

    monkeypatch.setattr(api_mod, "get_terrain_data", terrain_fail)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", mock_enrich)

    result = _run_r3_post_inversion_enrichment("proj_tef", "run_tef", "HIGH")

    assert result["terrain_persisted"] is False
    assert result["enrichment_attempted"] is True
    assert len(enrich_calls) == 1, "Enrichment debe ejecutarse si DEM files existen aunque terrain falle"


# ── 6. enrich falla → no crash, status error ─────────────────────────────────

def test_enrich_failure_no_crash_status_error(patched_projects_dir, monkeypatch):
    """Si enrich_block_model_with_elevation lanza excepción → no crash, status error."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_ef")

    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: None)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _enrich_raise)

    result = _run_r3_post_inversion_enrichment("proj_ef", "run_ef", "HIGH")

    assert result["attempted"] is True
    assert result["enrichment_attempted"] is True
    assert result["enrichment_status"] == "error"
    assert result["has_elevation_data"] is False
    assert any(
        "falló" in w.lower() or "enrich" in w.lower() for w in result["warnings"]
    ), f"Se esperaba warning de enrich fallo; got: {result['warnings']}"


# ── 7. Statuses propagados correctamente ─────────────────────────────────────

def test_enrich_skipped_status_propagated(patched_projects_dir, monkeypatch):
    """Si enrich devuelve status 'skipped' → se propaga correctamente."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    _create_terrain_files(patched_projects_dir, "proj_sk")

    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: None)
    monkeypatch.setattr(
        api_mod, "enrich_block_model_with_elevation",
        lambda *a, **kw: {"status": "skipped", "has_elevation_data": False,
                          "warnings": ["DEM no disponible"]},
    )

    result = _run_r3_post_inversion_enrichment("proj_sk", "run_sk", "MEDIUM")

    assert result["enrichment_status"] == "skipped"
    assert result["has_elevation_data"] is False
    assert any("DEM" in w for w in result["warnings"])


def test_r3_result_structure_complete(patched_projects_dir, monkeypatch):
    """El resultado siempre tiene las 6 claves esperadas."""
    import api.gravity_import_api as api_mod
    from api.gravity_import_api import _run_r3_post_inversion_enrichment

    monkeypatch.setattr(api_mod, "get_terrain_data", lambda *a, **kw: None)
    monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", lambda *a, **kw: None)

    for conf in ("HIGH", "MEDIUM", "LOW", "MISSING", None):
        result = _run_r3_post_inversion_enrichment("proj_struct", "run_struct", conf)
        for key in ("attempted", "terrain_persisted", "enrichment_attempted",
                    "enrichment_status", "has_elevation_data", "warnings"):
            assert key in result, f"Clave '{key}' ausente en resultado para conf={conf}"
        assert isinstance(result["warnings"], list)


# ── 8. Nota: QA manual del endpoint /invert ──────────────────────────────────
# El endpoint /invert llama _run_r3_post_inversion_enrichment solo si project_id
# y run_id están presentes. El test de integración completo requiere:
#   - Backend corriendo
#   - CSV real
#   - GEE o mock DEM
# Ver sección "QA manual deseado" del spec R3-INTEGRATION.
