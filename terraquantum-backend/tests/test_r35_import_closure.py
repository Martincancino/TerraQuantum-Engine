"""
R3.5-K — Import closure tests.

Covers:
  Station-id auto-generation (tests 1-8):
    1.  CSV legacy sin station_id importa OK
    2.  CSV lat/lon sin station_id importa OK
    3.  CSV UTM sin station_id importa OK
    4.  IDs autogenerados son estables (deterministas) y no vacíos
    5.  Formato ST_000001, ST_000002, ST_000003 …
    6.  Si station_id existe, se conserva comportamiento anterior
    7.  Warning "No se encontró station_id" aparece cuando columna ausente
    8.  CSV solo gravedad sin coordenadas → NO_SPATIAL_DATA, no crash

  utm_zone CSV fallback (tests 9-17):
    9.  /preview UTM con utm_zone en CSV y sin form param → spatial_readiness UTM_WITH_ZONE
    10. /preview UTM profesional con utm_zone en CSV y sin form param → PROFESSIONAL_SURVEY si 4 campos con valores reales
    11. /invert UTM con utm_zone en CSV y sin form param → georef.utm_zone = "19S"
    12. /invert UTM con utm_zone en CSV y sin form param → input_crs / epsg_code coherente
    13. Form param utm_zone tiene prioridad sobre CSV
    14. Sin utm_zone en CSV ni form param → UTM_NO_ZONE
    15. Lat/lon CSV no afectado por lógica utm_zone
    16. NOAA-like sparse (uncertainty/instrument vacíos) → GEOGRAPHIC_COORDS, no PROFESSIONAL_SURVEY
    17. NOAA-like complete con 4 campos profesionales poblados → PROFESSIONAL_SURVEY
"""
import io
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import core.block_model_store as store
from api.gravity_import_api import (
    _extract_detected_utm_zone,
    _effective_utm_zone,
    router,
)
from core.rate_limit import limiter
from services.gravity_import_service import import_gravity_csv_v1


# ---------------------------------------------------------------------------
# App / client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def reset_rate_limit():
    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass
    yield


@pytest.fixture()
def patched_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(store, "PROJECTS_DIR", projects_dir)
    return projects_dir


# ---------------------------------------------------------------------------
# Mock helpers for /invert (avoid heavy geophysics)
# ---------------------------------------------------------------------------

def _mock_inversion(*args, **kwargs):
    return {"status": "done", "blocks": [], "mock": True}


def _mock_terrain(*args, **kwargs):
    return {"status": "ok", "source": "mock"}


def _mock_enrich(*args, **kwargs):
    return {"status": "ok", "has_elevation_data": False, "warnings": []}


_INVERT_BASE_FORM = {
    "depth": "500",
    "nir": "20",
    "fe": "60",
    "region": "test_region",
    "lat": "-22.5",
    "lon": "-68.5",
    "nx": "8",
    "ny": "4",
    "nz": "8",
    "block_size": "200",
    "cutoff_radius": "600.0",
    "lambda_mag": "1.0",
    "alpha_spatial": "1.0",
    "strict": "false",
    "allow_g_raw": "false",
}


def _post_invert(client, csv_bytes: bytes, extra_form: dict | None = None, monkeypatch=None):
    if monkeypatch is not None:
        import api.gravity_import_api as api_mod
        monkeypatch.setattr(api_mod, "run_geophysics_inversion", _mock_inversion)
        monkeypatch.setattr(api_mod, "get_terrain_data", _mock_terrain)
        monkeypatch.setattr(api_mod, "enrich_block_model_with_elevation", _mock_enrich)
    form = dict(_INVERT_BASE_FORM)
    if extra_form:
        form.update(extra_form)
    return client.post(
        "/gravity-import/invert",
        data=form,
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )


def _post_preview(client, csv_bytes: bytes):
    return client.post(
        "/gravity-import/preview",
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )


# ---------------------------------------------------------------------------
# CSV builders
# ---------------------------------------------------------------------------

def _csv_legacy_no_sid(rows: int = 12) -> bytes:
    """Legacy x_m/z_m without station_id column."""
    lines = ["x_m,z_m,unit,g_mgal,gravity_type"]
    for i in range(rows):
        lines.append(f"{i * 100},{i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly")
    return "\n".join(lines).encode()


def _csv_latlon_no_sid(rows: int = 12) -> bytes:
    """lat/lon without station_id column."""
    lines = ["lat,lon,unit,g_mgal,gravity_type"]
    for i in range(rows):
        lines.append(f"{-22.28 + i * 0.01},{-68.89 + i * 0.01},mGal,{5.0 + i * 0.1},bouguer_anomaly")
    return "\n".join(lines).encode()


def _csv_utm_no_sid(rows: int = 12, utm_zone: str | None = None) -> bytes:
    """UTM easting/northing without station_id, optionally with utm_zone column."""
    if utm_zone:
        lines = ["easting,northing,unit,g_mgal,gravity_type,utm_zone"]
        for i in range(rows):
            lines.append(
                f"{510000 + i * 100},{7535000 + i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly,{utm_zone}"
            )
    else:
        lines = ["easting,northing,unit,g_mgal,gravity_type"]
        for i in range(rows):
            lines.append(
                f"{510000 + i * 100},{7535000 + i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly"
            )
    return "\n".join(lines).encode()


def _csv_utm_with_sid(rows: int = 12, utm_zone: str | None = None) -> bytes:
    """UTM easting/northing WITH station_id, optionally with utm_zone column."""
    if utm_zone:
        lines = ["station_id,easting,northing,unit,g_mgal,gravity_type,utm_zone"]
        for i in range(rows):
            lines.append(
                f"S{i:03d},{510000 + i * 100},{7535000 + i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly,{utm_zone}"
            )
    else:
        lines = ["station_id,easting,northing,unit,g_mgal,gravity_type"]
        for i in range(rows):
            lines.append(
                f"S{i:03d},{510000 + i * 100},{7535000 + i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly"
            )
    return "\n".join(lines).encode()


def _csv_legacy_with_sid(rows: int = 12) -> bytes:
    """Legacy x_m/z_m WITH station_id column (existing behavior)."""
    lines = ["station_id,x_m,z_m,unit,g_mgal,gravity_type"]
    for i in range(rows):
        lines.append(f"st_{i},{i * 100},{i * 100},mGal,{5.0 + i * 0.1},bouguer_anomaly")
    return "\n".join(lines).encode()


def _csv_gravity_only(rows: int = 12) -> bytes:
    """Gravity column only, no spatial columns at all."""
    lines = ["unit,g_mgal,gravity_type"]
    for i in range(rows):
        lines.append(f"mGal,{5.0 + i * 0.1},bouguer_anomaly")
    return "\n".join(lines).encode()


def _csv_latlon_professional(rows: int = 12, sparse: bool = False) -> bytes:
    """lat/lon CSV with professional columns (elevation, uncertainty, instrument, correction).
    If sparse=True, leave uncertainty and instrument empty (NOAA B1 pattern).
    """
    if sparse:
        lines = [
            "station_id,lat,lon,unit,gravity_anomaly,gravity_type,"
            "elevation_m,uncertainty_mgal,instrument_id,bouguer_correction"
        ]
        for i in range(rows):
            lines.append(
                f"st_{i},{-22.28 + i * 0.01},{-68.89 + i * 0.01},"
                f"mGal,{5.0 + i * 0.1},bouguer_anomaly,"
                f"{1000 + i},,,"  # elevation present, others empty
            )
    else:
        lines = [
            "station_id,lat,lon,unit,gravity_anomaly,gravity_type,"
            "elevation_m,uncertainty_mgal,instrument_id,bouguer_correction"
        ]
        for i in range(rows):
            lines.append(
                f"st_{i},{-22.28 + i * 0.01},{-68.89 + i * 0.01},"
                f"mGal,{5.0 + i * 0.1},bouguer_anomaly,"
                f"{1000 + i},{0.02 + i * 0.001},CG-6,{0.5 + i * 0.01}"
            )
    return "\n".join(lines).encode()


def _csv_utm_professional_with_zone(rows: int = 12) -> bytes:
    """UTM with utm_zone column + all 4 professional fields populated."""
    lines = [
        "station_id,easting,northing,unit,gravity_anomaly,gravity_type,"
        "utm_zone,elevation_m,uncertainty_mgal,instrument_id,bouguer_correction"
    ]
    for i in range(rows):
        lines.append(
            f"st_{i},{510000 + i * 100},{7535000 + i * 100},"
            f"mGal,{5.0 + i * 0.1},bouguer_anomaly,"
            f"19S,{1000 + i},{0.02 + i * 0.001},CG-6,{0.5 + i * 0.01}"
        )
    return "\n".join(lines).encode()


# ---------------------------------------------------------------------------
# Helper: write CSV to temp file
# ---------------------------------------------------------------------------

def _write_temp(tmp_path: Path, content: bytes, name: str = "test.csv") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ===========================================================================
# PART 1 — station_id auto-generation
# ===========================================================================

class TestStationIdAutoGeneration:

    # 1. CSV legacy sin station_id importa OK
    def test_legacy_no_sid_imports_ok(self, tmp_path):
        p = _write_temp(tmp_path, _csv_legacy_no_sid())
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok", result.errors

    # 2. CSV lat/lon sin station_id importa OK
    def test_latlon_no_sid_imports_ok(self, tmp_path):
        p = _write_temp(tmp_path, _csv_latlon_no_sid())
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok", result.errors

    # 3. CSV UTM sin station_id importa OK
    def test_utm_no_sid_imports_ok(self, tmp_path):
        p = _write_temp(tmp_path, _csv_utm_no_sid())
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok", result.errors

    # 4. IDs autogenerados son estables y no vacíos (>=10 rows para superar mínimo)
    def test_autogenerated_ids_are_stable(self, tmp_path):
        content = _csv_legacy_no_sid(rows=12)
        p = _write_temp(tmp_path, content, "a.csv")
        q = _write_temp(tmp_path, content, "b.csv")
        r1 = import_gravity_csv_v1(p, strict=False)
        r2 = import_gravity_csv_v1(q, strict=False)
        assert r1.status == "ok", r1.errors
        assert r2.status == "ok", r2.errors
        # Same row count = same observations (station_id not stored in GravityObservation,
        # but both runs should produce equivalent results and same warning)
        w1 = [w for w in r1.warnings if "station_id" in w.lower() or "autom" in w.lower()]
        w2 = [w for w in r2.warnings if "station_id" in w.lower() or "autom" in w.lower()]
        assert len(w1) == len(w2) == 1

    # 5. Formato ST_000001, ST_000002, ST_000003 generado internamente
    # (GravityObservation no almacena station_id; verificamos via warning y no-error)
    def test_autogenerated_id_format_warning_present(self, tmp_path):
        p = _write_temp(tmp_path, _csv_legacy_no_sid(rows=12))
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok", result.errors
        # Warning debe mencionar station_id y IDs automáticos
        matching = [
            w for w in result.warnings
            if "station_id" in w.lower() and ("autom" in w.lower() or "id" in w.lower())
        ]
        assert matching, f"Expected auto-id warning, got: {result.warnings}"

    # 6. Si station_id existe, se conserva comportamiento anterior (OK, sin warning)
    def test_existing_sid_column_preserved(self, tmp_path):
        p = _write_temp(tmp_path, _csv_legacy_with_sid())
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok", result.errors
        # No auto-id warning when column is present
        auto_id_warnings = [
            w for w in result.warnings
            if "autom" in w.lower() and "station_id" in w.lower()
        ]
        assert not auto_id_warnings, f"Should not warn about auto-ids: {result.warnings}"

    # 7. Warning aparece cuando columna ausente
    def test_warning_emitted_when_sid_column_missing(self, tmp_path):
        p = _write_temp(tmp_path, _csv_latlon_no_sid())
        result = import_gravity_csv_v1(p, strict=False)
        assert result.status == "ok"
        sid_warnings = [
            w for w in result.warnings
            if "station_id" in w.lower()
        ]
        assert sid_warnings, f"Expected station_id warning, got: {result.warnings}"
        assert "autom" in sid_warnings[0].lower() or "orden" in sid_warnings[0].lower()

    # 8. CSV solo gravedad sin coordenadas → NO_SPATIAL_DATA o error controlado, no crash
    def test_gravity_only_no_spatial_no_crash(self, tmp_path):
        p = _write_temp(tmp_path, _csv_gravity_only())
        # Must not raise; import may fail but gracefully
        try:
            result = import_gravity_csv_v1(p, strict=False)
            # If it returns a result, it should be "error" (no spatial columns)
            assert result.status in ("ok", "error")
        except Exception as exc:
            pytest.fail(f"import_gravity_csv_v1 should not raise, got: {exc}")


# ===========================================================================
# PART 2 — utm_zone CSV fallback
# ===========================================================================

class TestUtmZoneCsvFallback:

    # 9. /preview UTM con utm_zone en CSV y sin form param → spatial_readiness UTM_WITH_ZONE
    def test_preview_utm_csv_zone_gives_utm_with_zone(self, client):
        csv_bytes = _csv_utm_no_sid(utm_zone="19S")
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "UTM_WITH_ZONE", (
            f"Expected UTM_WITH_ZONE, got {sr['level']}"
        )

    # 10. /preview UTM profesional con utm_zone en CSV y sin form param → PROFESSIONAL_SURVEY
    def test_preview_utm_professional_csv_zone_gives_professional_survey(self, client):
        csv_bytes = _csv_utm_professional_with_zone()
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "PROFESSIONAL_SURVEY", (
            f"Expected PROFESSIONAL_SURVEY, got {sr['level']}. "
            f"Warnings: {body.get('warnings', [])}"
        )

    # 11. /invert UTM con utm_zone en CSV y sin form param → georef.utm_zone = "19S"
    def test_invert_utm_csv_zone_populates_georef_utm_zone(self, client, monkeypatch):
        csv_bytes = _csv_utm_with_sid(utm_zone="19S")
        resp = _post_invert(client, csv_bytes, monkeypatch=monkeypatch)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        georef = body["georef"]
        assert georef["utm_zone"] == "19S", (
            f"Expected georef.utm_zone='19S', got {georef['utm_zone']!r}"
        )

    # 12. /invert UTM con utm_zone en CSV y sin form param → input_crs / epsg_code coherente
    def test_invert_utm_csv_zone_epsg_coherent(self, client, monkeypatch):
        csv_bytes = _csv_utm_with_sid(utm_zone="19S")
        resp = _post_invert(client, csv_bytes, monkeypatch=monkeypatch)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        georef = body["georef"]
        assert georef.get("epsg_code") is not None, "epsg_code should not be None"
        assert georef.get("input_crs") not in (None, "unknown"), (
            f"input_crs should be set, got {georef.get('input_crs')!r}"
        )
        # EPSG:32719 for UTM zone 19S
        assert georef["epsg_code"] == 32719, (
            f"Expected EPSG 32719 for 19S, got {georef['epsg_code']}"
        )

    # 13. Form param utm_zone tiene prioridad sobre CSV
    def test_form_param_utm_zone_takes_priority_over_csv(self, client, monkeypatch):
        csv_bytes = _csv_utm_with_sid(utm_zone="19S")
        resp = _post_invert(
            client, csv_bytes,
            extra_form={"utm_zone": "20S"},
            monkeypatch=monkeypatch,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        georef = body["georef"]
        # Form param "20S" wins over CSV "19S"
        assert georef["utm_zone"] == "20S", (
            f"Expected form param zone '20S', got {georef['utm_zone']!r}"
        )
        # Mismatch warning should be present
        all_warnings = body.get("warnings", [])
        mismatch_warnings = [w for w in all_warnings if "difiere" in w.lower() or "mismatch" in w.lower()]
        assert mismatch_warnings, (
            f"Expected mismatch warning when form != csv zone. Warnings: {all_warnings}"
        )

    # 14. Sin utm_zone en CSV ni form param → UTM_NO_ZONE
    def test_no_csv_zone_no_form_zone_gives_utm_no_zone(self, client):
        csv_bytes = _csv_utm_no_sid(utm_zone=None)
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "UTM_NO_ZONE", (
            f"Expected UTM_NO_ZONE without any zone, got {sr['level']}"
        )

    # 15. Lat/lon CSV no afectado por lógica utm_zone
    def test_latlon_csv_unaffected_by_utm_zone_logic(self, client):
        csv_bytes = _csv_latlon_no_sid()
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "GEOGRAPHIC_COORDS", (
            f"Expected GEOGRAPHIC_COORDS for lat/lon CSV, got {sr['level']}"
        )

    # 16. NOAA-like sparse (uncertainty/instrument vacíos) → GEOGRAPHIC_COORDS, no PROFESSIONAL_SURVEY
    def test_noaa_sparse_stays_geographic_coords(self, client):
        csv_bytes = _csv_latlon_professional(sparse=True)
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "GEOGRAPHIC_COORDS", (
            f"Sparse professional CSV should be GEOGRAPHIC_COORDS, got {sr['level']}. "
            f"Warnings: {body.get('warnings', [])}"
        )

    # 17. NOAA-like complete con 4 campos profesionales poblados → PROFESSIONAL_SURVEY
    def test_noaa_complete_gives_professional_survey(self, client):
        csv_bytes = _csv_latlon_professional(sparse=False)
        resp = _post_preview(client, csv_bytes)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sr = body["spatial_readiness"]
        assert sr["level"] == "PROFESSIONAL_SURVEY", (
            f"Complete professional CSV should be PROFESSIONAL_SURVEY, got {sr['level']}. "
            f"Warnings: {body.get('warnings', [])}"
        )


# ===========================================================================
# Unit tests: helper functions
# ===========================================================================

class TestHelpers:

    def test_extract_utm_zone_from_coordinate_transform(self, tmp_path):
        """_extract_detected_utm_zone reads coordinate_transform.utm_zone."""
        p = _write_temp(tmp_path, _csv_utm_no_sid(utm_zone="19S"))
        result = import_gravity_csv_v1(p, strict=False)
        z = _extract_detected_utm_zone(result)
        assert z == "19S"

    def test_extract_utm_zone_derived_for_latlon(self, tmp_path):
        """lat/lon CSV is reprojected to UTM, so it now carries the DERIVED zone.

        El fixture está en Atacama (~lon -68.84, lat -22.2) → zona UTM 19S.
        La reproyección pyproj registra utm_zone="19S" como procedencia CRS real
        (antes, con equirectangular, no había zona y el resultado era None).
        """
        p = _write_temp(tmp_path, _csv_latlon_no_sid())
        result = import_gravity_csv_v1(p, strict=False)
        z = _extract_detected_utm_zone(result)
        assert z == "19S"

    def test_effective_utm_zone_form_priority(self, tmp_path):
        """Form param wins when both form and CSV have a zone."""
        p = _write_temp(tmp_path, _csv_utm_no_sid(utm_zone="19S"))
        result = import_gravity_csv_v1(p, strict=False)
        z = _effective_utm_zone("20S", result)
        assert z == "20S"

    def test_effective_utm_zone_csv_fallback(self, tmp_path):
        """CSV zone is used when form param is empty."""
        p = _write_temp(tmp_path, _csv_utm_no_sid(utm_zone="19S"))
        result = import_gravity_csv_v1(p, strict=False)
        z = _effective_utm_zone(None, result)
        assert z == "19S"

    def test_effective_utm_zone_none_when_absent(self, tmp_path):
        """Returns None when neither form nor CSV has a zone."""
        p = _write_temp(tmp_path, _csv_utm_no_sid(utm_zone=None))
        result = import_gravity_csv_v1(p, strict=False)
        z = _effective_utm_zone(None, result)
        assert z is None
