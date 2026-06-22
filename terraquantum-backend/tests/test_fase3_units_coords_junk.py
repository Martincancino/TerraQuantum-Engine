"""PILAR 3 (Fase 3) — Unidades, coordenadas y filas-basura en la ingesta.

  • Canonicalización de unidades (mGal/Gal/m·s⁻²/nT + variantes ortográficas).
  • Conversión correcta a m/s² (incluida Gal = 1e-2 m/s²).
  • Filas de METADATA/IGRF embebidas (texto en coords) se omiten con aviso, sin
    romper el import (caso DO-27 magnético crudo).
  • Coordenadas LOCALES (tipo Raglan) ingieren sin crash.
  • Unidad desconocida → error CLARO (no crash).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gravity_import_service import (
    canonicalize_unit,
    convert_to_ms2,
    _is_metadata_row,
    import_gravity_csv_v1,
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 1. Canonicalización de unidades ───────────────────────────────────────────
def test_canonicalize_gravity_units():
    assert canonicalize_unit("mgal") == "mGal"
    assert canonicalize_unit("MGAL") == "mGal"
    assert canonicalize_unit(" mGal ") == "mGal"
    assert canonicalize_unit("milligal") == "mGal"
    assert canonicalize_unit("Gal") == "Gal"
    assert canonicalize_unit("uGal") == "µGal"
    assert canonicalize_unit("µGal") == "µGal"
    assert canonicalize_unit("m/s^2") == "m/s2"
    assert canonicalize_unit("m/s²") == "m/s2"


def test_canonicalize_magnetic_units():
    assert canonicalize_unit("nt", magnetic=True) == "nT"
    assert canonicalize_unit("nanoTesla", magnetic=True) == "nT"
    assert canonicalize_unit("gamma", magnetic=True) == "nT"


def test_canonicalize_unknown_passthrough():
    assert canonicalize_unit("furlongs") == "furlongs"


# ── 2. Conversión a m/s² ──────────────────────────────────────────────────────
def test_convert_to_ms2_values():
    assert math.isclose(convert_to_ms2(1.0, "mGal"), 1e-5)
    assert math.isclose(convert_to_ms2(1.0, "µGal"), 1e-8)
    assert math.isclose(convert_to_ms2(1.0, "Gal"), 1e-2)
    assert math.isclose(convert_to_ms2(3.0, "m/s2"), 3.0)
    # Variantes ortográficas convierten igual.
    assert math.isclose(convert_to_ms2(2.0, "mgal"), 2e-5)


# ── 3. Filas de metadata / IGRF ───────────────────────────────────────────────
def test_is_metadata_row():
    assert _is_metadata_row({"lat": "IGRF", "lon": "83.8"}, ["lat", "lon"]) is True
    assert _is_metadata_row({"lat": "-27.1", "lon": "-69.3"}, ["lat", "lon"]) is False
    # Coords vacías → no es metadata por este criterio (validación por fila decide).
    assert _is_metadata_row({"lat": "", "lon": ""}, ["lat", "lon"]) is False


def _mag_csv_with_junk(n=12):
    rows = ["lat,lon,elev_m,tmi_nt"]
    # Filas de metadata/IGRF embebidas (texto en columnas de coordenada).
    rows.append("IGRF_inclination_deg,83.8,,")
    rows.append("IGRF_declination_deg,25.4,,")
    for i in range(n):
        lat = -27.10 - i * 0.001
        lon = -69.30 + i * 0.001
        rows.append(f"{lat:.4f},{lon:.4f},{1200.0 + i:.1f},{51000.0 + 5.0 * (i % 4):.2f}")
    return "\n".join(rows) + "\n"


def test_import_drops_metadata_rows(tmp_path):
    path = _write(tmp_path, "do27_like.csv", _mag_csv_with_junk())
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="magnetic")
    assert res.status == "ok", res.errors
    assert len(res.observations) == 12
    assert any("metadata" in w.lower() for w in res.warnings)


# ── 4. Coordenadas locales (tipo Raglan) ──────────────────────────────────────
def _local_mag_csv(n=12):
    rows = ["x_m,z_m,magnetic_nt"]
    for i in range(n):
        rows.append(f"{i * 100.0},{(i % 4) * 120.0},{51000.0 + 6.0 * (i % 5)}")
    return "\n".join(rows) + "\n"


def test_local_coords_ingest(tmp_path):
    path = _write(tmp_path, "raglan_like.csv", _local_mag_csv())
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="magnetic")
    assert res.status == "ok", res.errors
    assert len(res.observations) == 12


# ── 5. Unidad mGal en minúscula vía columna ───────────────────────────────────
def _grav_csv_unit(unit, n=12):
    rows = ["x_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(n):
        rows.append(f"{i * 100.0},{(i % 4) * 80.0},{1.0 + 0.1 * i},{unit},bouguer_anomaly")
    return "\n".join(rows) + "\n"


def test_import_lowercase_mgal_unit(tmp_path):
    path = _write(tmp_path, "low.csv", _grav_csv_unit("mgal"))
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "ok", res.errors
    assert res.import_metadata.unit_original == "mGal"


def test_import_gal_unit_converts(tmp_path):
    # Anomalías realistas en Gal (~5 mGal = 0.005 Gal), no gravedad absoluta.
    rows = ["x_m,z_m,bouguer_anomaly,unit,gravity_type"]
    for i in range(12):
        rows.append(f"{i * 100.0},{(i % 4) * 80.0},{0.002 + 0.0005 * i},Gal,bouguer_anomaly")
    path = _write(tmp_path, "gal.csv", "\n".join(rows) + "\n")
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "ok", res.errors
    # 0.002 Gal → 0.002 * 1e-2 m/s².
    assert math.isclose(res.observations[0].g, 0.002 * 1e-2, rel_tol=1e-9)


def test_unsupported_unit_clear_error(tmp_path):
    path = _write(tmp_path, "bad.csv", _grav_csv_unit("furlongs"))
    res = import_gravity_csv_v1(path, strict=False, allow_g_raw=True, data_kind="gravity")
    assert res.status == "error"
    assert any("unsupported unit" in e.lower() for e in res.errors)
