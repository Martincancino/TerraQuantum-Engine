"""
Tests unitarios H-B3 — OpenTopography TC integration.

Sin dependencias externas (no requiere OPENTOPO_API_KEY ni red):
- _parse_aaigrid: parseo correcto del formato ASCII Grid
- compute_tc_from_dem: TC >= 0 en terreno plano; TC > 0 con terreno elevado
- _fill_nan_nearest: relleno de NaN en DEM
"""
import math
import textwrap

import numpy as np
import pytest

from services.opentopo_service import (
    _parse_aaigrid,
    _fill_nan_nearest,
    compute_tc_from_dem,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_flat_dem(
    nrows: int = 20,
    ncols: int = 20,
    lat_origin: float = -22.0,
    lon_origin: float = -68.0,
    cell_deg: float = 0.001,
    elev: float = 3000.0,
) -> tuple:
    """Returns a flat DEM with uniform elevation."""
    lat_1d = lat_origin + (nrows - 0.5 - np.arange(nrows)) * cell_deg
    lon_1d = lon_origin + (np.arange(ncols) + 0.5) * cell_deg
    elev_2d = np.full((nrows, ncols), elev, dtype=np.float64)
    return lat_1d, lon_1d, elev_2d, cell_deg


def _make_elevated_dem(
    nrows: int = 40,
    ncols: int = 40,
    lat_origin: float = -22.0,
    lon_origin: float = -68.0,
    cell_deg: float = 0.001,
    station_elev: float = 3000.0,
    hill_elev: float = 3500.0,
) -> tuple:
    """Returns a DEM with a central hill above the station elevation."""
    lat_1d = lat_origin + (nrows - 0.5 - np.arange(nrows)) * cell_deg
    lon_1d = lon_origin + (np.arange(ncols) + 0.5) * cell_deg
    elev_2d = np.full((nrows, ncols), station_elev, dtype=np.float64)
    # Raise the central quadrant
    r0, r1 = nrows // 4, 3 * nrows // 4
    c0, c1 = ncols // 4, 3 * ncols // 4
    elev_2d[r0:r1, c0:c1] = hill_elev
    return lat_1d, lon_1d, elev_2d, cell_deg


# ---------------------------------------------------------------------------
# _parse_aaigrid
# ---------------------------------------------------------------------------

class TestParseAAIGrid:
    def test_basic_parse(self):
        content = textwrap.dedent("""\
            ncols         4
            nrows         3
            xllcorner     -68.0
            yllcorner     -22.0
            cellsize      0.001
            NODATA_value  -9999
            100 110 120 130
            200 210 220 230
            300 310 320 330
        """)
        lat_1d, lon_1d, elev_2d, cell_size = _parse_aaigrid(content)

        assert elev_2d.shape == (3, 4)
        assert len(lat_1d) == 3
        assert len(lon_1d) == 4
        assert math.isclose(cell_size, 0.001, rel_tol=1e-9)

        # Row 0 = northernmost
        assert lat_1d[0] > lat_1d[-1], "lat_1d must go north-to-south"
        # Col 0 = westernmost
        assert lon_1d[0] < lon_1d[-1], "lon_1d must go west-to-east"

        # Check values (row 0 = northern row = first data row = 100 110 120 130)
        assert elev_2d[0, 0] == pytest.approx(100.0)
        assert elev_2d[0, 3] == pytest.approx(130.0)
        assert elev_2d[2, 0] == pytest.approx(300.0)

    def test_nodata_replaced_with_nan(self):
        content = textwrap.dedent("""\
            ncols 3
            nrows 2
            xllcorner 0.0
            yllcorner 0.0
            cellsize 0.001
            NODATA_value -9999
            100 -9999 200
            300 400   500
        """)
        _, _, elev_2d, _ = _parse_aaigrid(content)
        assert math.isnan(elev_2d[0, 1])
        assert not math.isnan(elev_2d[0, 0])

    def test_lat_lon_coordinates(self):
        # 2x2 DEM, cell=0.01 deg, yllcorner=-22.0, xllcorner=-68.0
        content = textwrap.dedent("""\
            ncols 2
            nrows 2
            xllcorner -68.0
            yllcorner -22.0
            cellsize 0.01
            NODATA_value -9999
            100 200
            300 400
        """)
        lat_1d, lon_1d, elev_2d, cell_size = _parse_aaigrid(content)

        # yllcorner=-22.0, nrows=2, row0_lat = -22.0 + (2-0.5)*0.01 = -22.0+0.015 = -21.985
        assert lat_1d[0] == pytest.approx(-21.985, abs=1e-9)
        # row1_lat = -22.0 + (2-1.5)*0.01 = -22.0+0.005 = -21.995
        assert lat_1d[1] == pytest.approx(-21.995, abs=1e-9)

        # xllcorner=-68.0, col0_lon = -68.0+0.5*0.01 = -67.995
        assert lon_1d[0] == pytest.approx(-67.995, abs=1e-9)
        assert lon_1d[1] == pytest.approx(-67.985, abs=1e-9)


# ---------------------------------------------------------------------------
# _fill_nan_nearest
# ---------------------------------------------------------------------------

class TestFillNanNearest:
    def test_no_nan(self):
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        orig = arr.copy()
        _fill_nan_nearest(arr)
        np.testing.assert_array_equal(arr, orig)

    def test_single_nan(self):
        arr = np.array([[1.0, np.nan], [3.0, 4.0]])
        _fill_nan_nearest(arr)
        assert not math.isnan(arr[0, 1])
        # NaN at (0,1) should be filled with nearest valid: (0,0)=1.0 or (1,1)=4.0
        assert arr[0, 1] in (1.0, 4.0)

    def test_all_nan_fills_with_zero(self):
        arr = np.full((3, 3), np.nan)
        _fill_nan_nearest(arr)
        assert not np.any(np.isnan(arr))
        np.testing.assert_array_equal(arr, np.zeros((3, 3)))


# ---------------------------------------------------------------------------
# compute_tc_from_dem
# ---------------------------------------------------------------------------

class TestComputeTCFromDem:
    def test_flat_terrain_tc_near_zero(self):
        """
        Flat terrain at same elevation as station → TC ≈ 0.
        (No topographic relief → no terrain correction needed.)
        """
        station_elev = 3000.0
        lat_1d, lon_1d, elev_2d, cell_size = _make_flat_dem(
            nrows=30, ncols=30, elev=station_elev,
        )
        center_lat = float(np.mean(lat_1d))
        center_lon = float(np.mean(lon_1d))

        tc = compute_tc_from_dem(
            stations_lat=np.array([center_lat]),
            stations_lon=np.array([center_lon]),
            stations_elev_m=np.array([station_elev]),
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_size,
            terrain_radius_m=5000.0,
        )

        assert len(tc) == 1
        # For perfectly flat terrain at the same elevation as the station,
        # dh = 0 everywhere → TC must be exactly 0.
        assert tc[0] == pytest.approx(0.0, abs=1e-12)

    def test_elevated_terrain_tc_positive(self):
        """
        Terrain with a hill above station elevation → TC > 0.
        """
        station_elev = 3000.0
        lat_1d, lon_1d, elev_2d, cell_size = _make_elevated_dem(
            nrows=40, ncols=40,
            station_elev=station_elev,
            hill_elev=3500.0,
        )
        center_lat = float(np.mean(lat_1d))
        center_lon = float(np.mean(lon_1d))

        tc = compute_tc_from_dem(
            stations_lat=np.array([center_lat]),
            stations_lon=np.array([center_lon]),
            stations_elev_m=np.array([station_elev]),
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_size,
            terrain_radius_m=10000.0,
        )

        assert len(tc) == 1
        assert tc[0] > 0.0, f"Expected TC > 0 with hill terrain, got {tc[0]}"

    def test_tc_nonnegative_always(self):
        """
        TC is a mathematical property: always >= 0 regardless of terrain.
        """
        rng = np.random.default_rng(42)
        nrows, ncols = 20, 20
        lat_1d = -22.0 + (nrows - 0.5 - np.arange(nrows)) * 0.001
        lon_1d = -68.0 + (np.arange(ncols) + 0.5) * 0.001
        # Random elevation: some below, some above the station
        elev_2d = rng.uniform(2500.0, 4000.0, size=(nrows, ncols))

        center_lat = float(np.mean(lat_1d))
        center_lon = float(np.mean(lon_1d))

        tc = compute_tc_from_dem(
            stations_lat=np.array([center_lat]),
            stations_lon=np.array([center_lon]),
            stations_elev_m=np.array([3000.0]),
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=0.001,
            terrain_radius_m=5000.0,
        )

        assert np.all(tc >= 0.0), f"TC must be >= 0 everywhere, got min={tc.min()}"

    def test_multiple_stations(self):
        """
        Multiple stations: one TC value per station.
        """
        lat_1d, lon_1d, elev_2d, cell_size = _make_elevated_dem(
            nrows=50, ncols=50, station_elev=3000.0, hill_elev=3800.0,
        )

        n_stations = 5
        center_lat = float(np.mean(lat_1d))
        center_lon = float(np.mean(lon_1d))
        lats  = np.linspace(center_lat - 0.005, center_lat + 0.005, n_stations)
        lons  = np.full(n_stations, center_lon)
        elevs = np.full(n_stations, 3000.0)

        tc = compute_tc_from_dem(
            stations_lat=lats,
            stations_lon=lons,
            stations_elev_m=elevs,
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_size,
            terrain_radius_m=10000.0,
        )

        assert len(tc) == n_stations
        assert np.all(tc >= 0.0)

    def test_radius_limits_integration(self):
        """
        With a very small radius (100 m), fewer DEM cells contribute → TC close to 0
        even with elevated terrain (the hill is far).
        """
        lat_1d, lon_1d, elev_2d, cell_size = _make_elevated_dem(
            nrows=40, ncols=40, station_elev=3000.0, hill_elev=3500.0,
        )
        center_lat = float(np.mean(lat_1d))
        center_lon = float(np.mean(lon_1d))

        tc_small_r = compute_tc_from_dem(
            stations_lat=np.array([center_lat]),
            stations_lon=np.array([center_lon]),
            stations_elev_m=np.array([3000.0]),
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_size,
            terrain_radius_m=50.0,  # very small: captures < 1 cell (0.001 deg ≈ 111 m)
        )

        tc_large_r = compute_tc_from_dem(
            stations_lat=np.array([center_lat]),
            stations_lon=np.array([center_lon]),
            stations_elev_m=np.array([3000.0]),
            dem_lat_1d=lat_1d,
            dem_lon_1d=lon_1d,
            dem_elev_2d=elev_2d,
            dem_cell_size_deg=cell_size,
            terrain_radius_m=10000.0,
        )

        assert tc_large_r[0] >= tc_small_r[0], (
            "Larger integration radius must yield equal or greater TC"
        )
