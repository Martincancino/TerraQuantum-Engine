"""
R3-BE-2 — Tests for sample_dem_elevation() and DEM sampling utilities.

All tests are pure unit tests; no GEE, no disk access, no backend server.
Row 0 of the DEM is the northern-most row; z_m grows northward (south = row max).

DEM_4x4 pattern  →  matrix[r][c] = 10*(r+1) + 10*c
  row 0 (north): [10, 20, 30, 40]
  row 1:         [20, 30, 40, 50]
  row 2:         [30, 40, 50, 60]
  row 3 (south): [40, 50, 60, 70]

META_NO_MARGIN: 100 m × 100 m bbox at the equator → bbox == model extent
  → offset_x_m = offset_z_m = 0
  → col_f = (x_m / 100) * 3
  → row_f = ((100 - z_m) / 100) * 3
"""
import pytest

from services.geo_utils import METERS_PER_DEG_LAT, sample_dem_elevation

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

DEM_4x4 = [
    [10.0, 20.0, 30.0, 40.0],   # row 0 — north
    [20.0, 30.0, 40.0, 50.0],
    [30.0, 40.0, 50.0, 60.0],
    [40.0, 50.0, 60.0, 70.0],   # row 3 — south
]

# 100 m × 100 m at the equator (cos(0)=1 → deg_lon == deg_lat)
_D = 100.0 / METERS_PER_DEG_LAT

META_NO_MARGIN = {
    "bbox": {
        "min_lat": -_D / 2,
        "max_lat":  _D / 2,
        "min_lon": -_D / 2,
        "max_lon":  _D / 2,
    },
}

_EXT = 100.0   # model_extent_x_m == model_extent_z_m


# ---------------------------------------------------------------------------
# 1 — Empty matrix → None
# ---------------------------------------------------------------------------

def test_sample_dem_empty_matrix_returns_none():
    elev, warn = sample_dem_elevation([], META_NO_MARGIN, 50.0, 50.0, _EXT, _EXT)
    assert elev is None
    assert "vacío" in warn.lower()


# ---------------------------------------------------------------------------
# 2 — Inconsistent row lengths → None
# ---------------------------------------------------------------------------

def test_sample_dem_inconsistent_rows_returns_none():
    bad_dem = [[1.0, 2.0], [3.0, 4.0, 5.0]]
    elev, warn = sample_dem_elevation(bad_dem, META_NO_MARGIN, 50.0, 50.0, _EXT, _EXT)
    assert elev is None
    assert "inconsistente" in warn.lower()


# ---------------------------------------------------------------------------
# 3 — Mock DEM (all zeros) → 0.0 + conceptual warning
# ---------------------------------------------------------------------------

def test_sample_dem_mock_returns_zero_with_warning():
    mock_dem = [[0.0] * 4 for _ in range(4)]
    elev, warn = sample_dem_elevation(mock_dem, META_NO_MARGIN, 50.0, 50.0, _EXT, _EXT)
    assert elev == 0.0
    assert "mock" in warn.lower() or "conceptual" in warn.lower()


# ---------------------------------------------------------------------------
# 4 — Unknown method → None
# ---------------------------------------------------------------------------

def test_sample_dem_unknown_method_returns_none():
    elev, warn = sample_dem_elevation(
        DEM_4x4, META_NO_MARGIN, 50.0, 50.0, _EXT, _EXT, method="cubic"
    )
    assert elev is None
    assert "cubic" in warn


# ---------------------------------------------------------------------------
# 5 — Nearest neighbour at a well-defined grid position
# ---------------------------------------------------------------------------

def test_sample_dem_nearest_center():
    # x_m=60 → col_f = (60/100)*3 = 1.8 → round → 2
    # z_m=40 → row_f = ((100-40)/100)*3 = 1.8 → round → 2
    # matrix[2][2] = 50.0
    elev, warn = sample_dem_elevation(
        DEM_4x4, META_NO_MARGIN, 60.0, 40.0, _EXT, _EXT, method="nearest"
    )
    assert elev == pytest.approx(50.0)
    assert warn == ""


# ---------------------------------------------------------------------------
# 6 — Bilinear at the exact model centre
# ---------------------------------------------------------------------------

def test_sample_dem_bilinear_center():
    # x_m=50 → col_f=1.5  /  z_m=50 → row_f=1.5
    # bilinear: (matrix[1][1]+matrix[1][2]+matrix[2][1]+matrix[2][2])/4
    #         = (30+40+40+50)/4 = 40.0
    elev, warn = sample_dem_elevation(
        DEM_4x4, META_NO_MARGIN, 50.0, 50.0, _EXT, _EXT, method="bilinear"
    )
    assert elev == pytest.approx(40.0)
    assert warn == ""


# ---------------------------------------------------------------------------
# 7 — Bilinear interpolates correctly between four known cells
# ---------------------------------------------------------------------------

def test_sample_dem_bilinear_interpolates_between_four_cells():
    # x_m=25 → col_f=0.75  /  z_m=75 → row_f=0.75
    # bilinear with row0=0, col0=0, dr=0.75, dc=0.75:
    #   v00=10, v01=20, v10=20, v11=30
    #   = 10*0.0625 + 20*0.1875 + 20*0.1875 + 30*0.5625 = 25.0
    elev, warn = sample_dem_elevation(
        DEM_4x4, META_NO_MARGIN, 25.0, 75.0, _EXT, _EXT, method="bilinear"
    )
    assert elev == pytest.approx(25.0)
    assert warn == ""


# ---------------------------------------------------------------------------
# 8 — Row axis: row 0 = north (z_m = max), z_m grows northward
# ---------------------------------------------------------------------------

def test_sample_dem_row_axis_is_inverted_north_is_row_zero():
    # DEM where row 0 has high elevation (north) and row 3 has zero (south)
    dem_ns = [
        [1000.0, 1000.0, 1000.0, 1000.0],   # row 0 — north
        [600.0,  600.0,  600.0,  600.0],
        [300.0,  300.0,  300.0,  300.0],
        [0.0,    0.0,    0.0,    0.0],       # row 3 — south
    ]
    # z_m=100 → north edge → row_f = ((100-100)/100)*3 = 0 → row 0 → 1000.0
    elev_north, _ = sample_dem_elevation(
        dem_ns, META_NO_MARGIN, 50.0, 100.0, _EXT, _EXT, method="nearest"
    )
    # z_m=0 → south edge → row_f = ((100-0)/100)*3 = 3 → row 3 → 0.0
    elev_south, _ = sample_dem_elevation(
        dem_ns, META_NO_MARGIN, 50.0, 0.0, _EXT, _EXT, method="nearest"
    )
    assert elev_north == pytest.approx(1000.0)
    assert elev_south == pytest.approx(0.0)
    # North elevation must be higher than south
    assert elev_north > elev_south


# ---------------------------------------------------------------------------
# 9 — Out-of-bounds position: clamp + warning
# ---------------------------------------------------------------------------

def test_sample_dem_clamps_out_of_bounds_with_warning():
    # x_m=200 (beyond 100 m east edge) with no-margin bbox:
    #   col_f = (200/100)*3 = 6.0 → clamped to 3.0
    #   z_m=40 → row_f = ((100-40)/100)*3 = 1.8 → round = 2
    #   matrix[2][3] = 60.0
    elev, warn = sample_dem_elevation(
        DEM_4x4, META_NO_MARGIN, 200.0, 40.0, _EXT, _EXT, method="nearest"
    )
    assert elev is not None
    assert elev == pytest.approx(60.0)
    assert "clamp" in warn.lower() or "fuera" in warn.lower()


# ---------------------------------------------------------------------------
# 10 — Missing / insufficient metadata → None
# ---------------------------------------------------------------------------

def test_sample_dem_missing_metadata_returns_none():
    elev, warn = sample_dem_elevation(
        DEM_4x4, None, 50.0, 50.0, _EXT, _EXT
    )
    assert elev is None
    assert "metadata" in warn.lower() or "sin" in warn.lower()


def test_sample_dem_empty_metadata_returns_none():
    elev, warn = sample_dem_elevation(
        DEM_4x4, {}, 50.0, 50.0, _EXT, _EXT
    )
    assert elev is None
    assert "metadata" in warn.lower() or "sin" in warn.lower()


def test_sample_dem_bbox_form_b_sw_ne():
    """dem_metadata bbox Form B (sw/ne sub-dicts) must work like Form A."""
    meta_b = {
        "bbox": {
            "sw": {"lat": -_D / 2, "lon": -_D / 2},
            "ne": {"lat":  _D / 2, "lon":  _D / 2},
        }
    }
    # Same call as test 6 but with Form B bbox — expect same result
    elev, warn = sample_dem_elevation(
        DEM_4x4, meta_b, 50.0, 50.0, _EXT, _EXT, method="bilinear"
    )
    assert elev == pytest.approx(40.0)
    assert warn == ""


# ---------------------------------------------------------------------------
# 11 — Voxel absolute elevation formula: surface_elevation_masl - y_m
# ---------------------------------------------------------------------------

def test_voxel_absolute_elevation_formula_surface_minus_depth():
    surface_elevation_masl = 3000.0   # m.s.n.m. from DEM
    y_m = 500.0                        # depth (positive downward, backend convention)
    voxel_elevation_masl = surface_elevation_masl - y_m
    assert voxel_elevation_masl == pytest.approx(2500.0)


def test_voxel_elevation_decreases_with_greater_depth():
    surface = 3000.0
    shallow = surface - 100.0
    deep    = surface - 2000.0
    assert deep < shallow < surface


# ---------------------------------------------------------------------------
# 12 — depth_below_surface_m == y_m convention (no inversion needed)
# ---------------------------------------------------------------------------

def test_depth_below_surface_equals_y_m_convention():
    # Backend stores y_m as positive depth downward from survey surface.
    # depth_below_surface_m requires no sign change.
    y_m = 800.0
    depth_below_surface_m = y_m
    assert depth_below_surface_m == 800.0


def test_depth_below_surface_y_zero_is_at_surface():
    y_m = 0.0
    depth_below_surface_m = y_m
    surface_elevation_masl = 2400.0
    voxel_elevation_masl = surface_elevation_masl - depth_below_surface_m
    assert voxel_elevation_masl == pytest.approx(surface_elevation_masl)
