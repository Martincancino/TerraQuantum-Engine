import time

from schemas.geophysics_schema import GravityObservation
from services.csv_analysis_service import analyze_csv_observations
from services.gravity_import_service import import_gravity_csv_v1


def _observations(count, x0=1000.0, z0=2000.0, step=25.0):
    return [
        GravityObservation(
            x_m=x0 + i * step,
            y_m=0.0,
            z_m=z0 + i * step,
            g=(i + 1) * 1e-5,
        )
        for i in range(count)
    ]


def _write_gravity_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("station_id,x_m,y_m,z_m,unit,g,gravity_type\n")
        for row in rows:
            f.write(",".join(str(value) for value in row) + "\n")


def test_csv_analysis_has_all_required_sections():
    observations = _observations(10)
    raw_values = [float(i + 1) for i in range(10)]

    analysis = analyze_csv_observations(
        observations=observations,
        declared_unit="mGal",
        raw_gravity_values=raw_values,
    )

    assert analysis.version == "csv_analysis_v0_1"
    assert analysis.observation_count == 10
    assert analysis.spatial_extent.x_min is not None
    assert analysis.sampling.area_km2 >= 0
    assert analysis.sampling.mean_spacing_m is not None
    assert analysis.gravity_stats.p5 is not None
    assert analysis.duplicates.exact_count == 0
    assert analysis.outliers.method == "zscore_3sigma"
    assert analysis.units.declared == "mGal"
    assert analysis.coordinate_system.detected in {"latlon", "utm", "local_meters", "unknown"}
    assert analysis.quality_label in {"ALTA", "MEDIA", "BAJA", "INSUFICIENTE"}
    assert analysis.quality_label != "OK"


def test_csv_analysis_handles_10000_observations_quickly():
    observations = [
        GravityObservation(
            x_m=float((i % 100) * 20),
            y_m=0.0,
            z_m=float((i // 100) * 20),
            g=float(i) * 1e-6,
        )
        for i in range(10_000)
    ]
    raw_values = [float(i) for i in range(10_000)]

    start = time.perf_counter()
    analysis = analyze_csv_observations(
        observations=observations,
        declared_unit="mGal",
        raw_gravity_values=raw_values,
    )
    elapsed = time.perf_counter() - start

    assert analysis.observation_count == 10_000
    assert analysis.duplicates.near_count == 0
    assert elapsed < 5.0


def test_exact_duplicate_rows_are_rejected_with_warning(tmp_path):
    rows = [
        (f"st_{i}", 1000 + i * 10, 0, 2000 + i * 10, "mGal", i + 1, "bouguer_anomaly")
        for i in range(10)
    ]
    rows.append(("st_dup", 1000, 0, 2000, "mGal", 99, "bouguer_anomaly"))
    csv_path = tmp_path / "gravity.csv"
    _write_gravity_csv(csv_path, rows)

    result = import_gravity_csv_v1(csv_path, strict=True)

    assert result.status == "ok"
    assert result.import_metadata.valid_rows == 10
    assert result.import_metadata.rejected_rows == 1
    assert result.csv_analysis is not None
    assert result.csv_analysis.duplicates.exact_count == 1
    assert result.csv_analysis.duplicates.examples
    assert any("duplicadas" in warning for warning in result.import_metadata.warnings)


def test_outlier_detection_reports_examples():
    observations = _observations(31)
    raw_values = [10.0] * 30 + [100.0]

    analysis = analyze_csv_observations(
        observations=observations,
        declared_unit="mGal",
        raw_gravity_values=raw_values,
    )

    assert analysis.outliers.count > 0
    assert analysis.outliers.examples
    assert all("g_value" in example for example in analysis.outliers.examples)


def test_coordinate_system_detects_latlon():
    observations = [
        GravityObservation(x_m=-70.0 + i * 0.01, y_m=0.0, z_m=-30.0 + i * 0.01, g=1e-5)
        for i in range(10)
    ]

    analysis = analyze_csv_observations(observations, "mGal", [1.0] * 10)

    assert analysis.coordinate_system.detected == "latlon"


def test_coordinate_system_detects_utm():
    observations = [
        GravityObservation(x_m=350_000.0 + i * 50, y_m=0.0, z_m=6_200_000.0 + i * 50, g=1e-5)
        for i in range(10)
    ]

    analysis = analyze_csv_observations(observations, "mGal", [1.0] * 10)

    assert analysis.coordinate_system.detected == "utm"


def test_coordinate_system_detects_local_meters():
    observations = [
        GravityObservation(x_m=float(i * 5000), y_m=0.0, z_m=float(i * 5000), g=1e-5)
        for i in range(10)
    ]

    analysis = analyze_csv_observations(observations, "mGal", [1.0] * 10)

    assert analysis.coordinate_system.detected == "local_meters"


def test_mgal_unit_range_consistent():
    analysis = analyze_csv_observations(_observations(10), "mGal", [10.0] * 10)

    assert analysis.units.value_range_consistent is True
    assert analysis.units.warning is None


def test_absurd_mgal_unit_range_warns():
    analysis = analyze_csv_observations(_observations(10), "mGal", [100_001.0] * 10)

    assert analysis.units.value_range_consistent is False
    assert analysis.units.warning


def test_less_than_10_observations_is_insufficient():
    analysis = analyze_csv_observations(_observations(8), "mGal", [1.0] * 8)

    assert analysis.quality_label == "INSUFICIENTE"


def test_parser_accepts_utf8_bom_header(tmp_path):
    rows = [
        (f"bom_{i}", 1000 + i * 10, 0, 2000 + i * 10, "mGal", i + 1, "bouguer_anomaly")
        for i in range(10)
    ]
    csv_path = tmp_path / "gravity_bom.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        f.write("\ufeffstation_id,x_m,y_m,z_m,unit,g,gravity_type\n")
        for row in rows:
            f.write(",".join(str(value) for value in row) + "\n")

    result = import_gravity_csv_v1(csv_path, strict=True)

    assert result.status == "ok"
    assert result.import_metadata.valid_rows == 10
    assert result.csv_analysis is not None
    assert result.csv_analysis.version == "csv_analysis_v0_1"
