"""
Router FastAPI — Correcciones de Gravedad (Fase 1 / H-B3 Plan Industrial Tier 1).

Endpoints:
    POST /gravity-corrections/apply
        Aplica GRS80 / FAC / Bouguer / TC a una lista de estaciones.
        Cuando apply_terrain=True, descarga automáticamente el DEM desde
        OpenTopography y calcula la corrección de terreno por estación.

    POST /gravity-corrections/terrain-dem
        Standalone: dada una lista de estaciones, descarga DEM y retorna
        los valores de TC por estación (sin aplicar el resto de correcciones).

    POST /gravity-corrections/nettleton
        Análisis de Nettleton para encontrar la densidad de reducción óptima.
"""
from __future__ import annotations

import math
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.gravity_corrections_schema import (
    ApplyCorrectionsRequest,
    ApplyCorrectionsResponse,
    CorrectedStation,
    CorrectionReport,
    RegionalResidualRequest,
)
from services.gravity_corrections_service import apply_all_corrections, nettleton_analysis

router = APIRouter(prefix="/gravity-corrections", tags=["Gravity Corrections"])
_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: extract lat/lon/elev/g arrays from stations list
# ---------------------------------------------------------------------------

def _extract_arrays(
    stations: List[dict],
    g_col: str,
) -> tuple:
    """
    Extracts lats, lons, elevs, g_obs from the stations dicts.
    Returns (lats, lons, elevs, g_obs) as float64 arrays.
    Raises HTTPException 422 on missing/invalid columns.
    """
    try:
        lats  = np.array([float(s["lat_deg"])                       for s in stations])
        lons  = np.array([float(s["lon_deg"])                       for s in stations])
        elevs = np.array([float(s.get("elev_m", float("nan")))      for s in stations])
        g_obs = np.array([float(s[g_col])                           for s in stations])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Error al extraer columnas de las estaciones: {exc}. "
                f"Verifique que lat_deg, lon_deg, elev_m y '{g_col}' estén presentes."
            ),
        ) from exc
    return lats, lons, elevs, g_obs


# ---------------------------------------------------------------------------
# Helper: auto-compute TC via OpenTopography
# ---------------------------------------------------------------------------

async def _compute_tc_opentopo(
    lats: np.ndarray,
    lons: np.ndarray,
    elevs: np.ndarray,
    dem_type: str,
    terrain_radius_m: float,
    reduction_density_gcc: float,
) -> tuple:
    """
    Fetches DEM from OpenTopography and computes TC per station.

    Returns:
        tc_mgal: np.ndarray, shape (n,), always >= 0
        source_info: dict with DEM metadata
    """
    from services.opentopo_service import (
        fetch_dem_for_survey,
        compute_tc_from_dem,
        OpenTopoKeyMissingError,
        OpenTopoError,
    )

    south = float(lats.min())
    north = float(lats.max())
    west  = float(lons.min())
    east  = float(lons.max())

    # Buffer = terrain_radius + 20% margin, converted to degrees
    buffer_deg = (terrain_radius_m * 1.2) / 111320.0

    try:
        dem_lat, dem_lon, dem_elev, cell_size, source_info = await fetch_dem_for_survey(
            south=south,
            north=north,
            west=west,
            east=east,
            dem_type=dem_type,
            buffer_deg=buffer_deg,
        )
    except OpenTopoKeyMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OpenTopoError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error al descargar DEM de OpenTopography: {exc}",
        ) from exc

    tc_mgal = compute_tc_from_dem(
        stations_lat=lats,
        stations_lon=lons,
        stations_elev_m=elevs,
        dem_lat_1d=dem_lat,
        dem_lon_1d=dem_lon,
        dem_elev_2d=dem_elev,
        dem_cell_size_deg=cell_size,
        terrain_radius_m=terrain_radius_m,
        reduction_density_gcc=reduction_density_gcc,
    )

    _log.info(
        "[CORRECTIONS-API] TC OpenTopo: min=%.4f max=%.4f mGal (fuente=%s)",
        float(tc_mgal.min()),
        float(tc_mgal.max()),
        source_info.get("source", "?"),
    )

    return tc_mgal, source_info


# ---------------------------------------------------------------------------
# POST /gravity-corrections/apply
# ---------------------------------------------------------------------------

@router.post("/apply", response_model=ApplyCorrectionsResponse)
async def apply_gravity_corrections(
    req: ApplyCorrectionsRequest,
) -> ApplyCorrectionsResponse:
    """
    Aplica correcciones de gravedad (GRS80 / FAC / BC / TC) a una lista de estaciones.

    Cuando ``apply_terrain=True`` el endpoint descarga automáticamente el DEM
    del tipo indicado en ``dem_type`` desde OpenTopography (requiere
    ``OPENTOPO_API_KEY`` configurado) y calcula la corrección de terreno
    por el método de prismas para cada estación.

    Para datos ``g_raw`` sin elevaciones con FAC/BC/TC activado retorna HTTP 422.
    """
    stations = req.stations
    params   = req.params
    gtype_in = req.gravity_type_in
    g_col    = req.gravity_column

    if not stations:
        raise HTTPException(status_code=422, detail="Se requiere al menos 1 estación.")

    lats, lons, elevs, g_obs = _extract_arrays(stations, g_col)
    # F2B: g_obs puede pre-reducirse (marea/deriva) antes de la cadena; el
    # reporte por estación muestra SIEMPRE la lectura original.
    g_obs_original = g_obs.copy()

    # Validate elevations if needed
    needs_elev = (
        (params.apply_fac or params.apply_bouguer or params.apply_terrain)
        and gtype_in == "g_raw"
    )
    if needs_elev and np.any(np.isnan(elevs)):
        missing = int(np.sum(np.isnan(elevs)))
        raise HTTPException(
            status_code=422,
            detail=(
                f"{missing} estaciones no tienen elevación (elev_m). "
                "Se requiere elevación para calcular FAC, BC y TC. "
                "Proporcione la columna 'elev_m' en cada estación, o "
                "deshabilite apply_fac, apply_bouguer y apply_terrain."
            ),
        )

    # --- F2B: pre-reducciones de CAMPO (marea Longman + deriva por cierres) ---
    prereduction_meta: dict = {}
    if params.apply_tide or params.apply_drift:
        if gtype_in != "g_raw":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Las correcciones de marea y deriva solo aplican a lecturas "
                    f"CRUDAS de campo (g_raw); el dato declarado es '{gtype_in}' "
                    "(ya reducido: la marea/deriva ya fueron removidas o no son "
                    "recuperables). Desactive apply_tide/apply_drift."
                ),
            )
        from services.gravity_corrections_service import apply_field_prereductions

        station_ids = [str(s.get("station_id", f"ST_{i:06d}")) for i, s in enumerate(stations)]
        time_strings = [str(s.get("time_utc") or s.get("timestamp") or "") for s in stations]
        try:
            g_obs, prereduction_meta = apply_field_prereductions(
                lats_deg=lats, lons_deg=lons, elevs_m=elevs, g_obs_mgal=g_obs,
                station_ids=station_ids, time_strings=time_strings,
                apply_tide=params.apply_tide, apply_drift=params.apply_drift,
                drift_method=params.drift_method,
                base_station_id=params.base_station_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- Terrain correction via OpenTopography ---
    tc_per_station: Optional[np.ndarray] = None
    dem_source: Optional[str] = None

    already_tc = gtype_in == "complete_bouguer_anomaly"
    if params.apply_terrain and not already_tc:
        tc_per_station, source_info = await _compute_tc_opentopo(
            lats=lats,
            lons=lons,
            elevs=elevs,
            dem_type=params.dem_type,
            terrain_radius_m=params.terrain_radius_m,
            reduction_density_gcc=params.reduction_density_gcc,
        )
        dem_source = source_info.get("source")

    # --- Apply all corrections ---
    try:
        g_reduced, meta = apply_all_corrections(
            lats_deg=lats,
            lons_deg=lons,
            elevs_m=elevs,
            g_obs_mgal=g_obs,
            gravity_type_in=gtype_in,
            reduction_density_gcc=params.reduction_density_gcc,
            apply_lat=params.apply_lat_correction,
            apply_fac=params.apply_fac,
            apply_bouguer=params.apply_bouguer,
            apply_terrain=params.apply_terrain,
            tc_values_mgal=tc_per_station,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- Build per-station corrections for the response ---
    # Recompute individual components to fill per-station fields accurately
    from services.gravity_corrections_service import (
        compute_normal_gravity_mgal,
        compute_free_air_correction,
        compute_bouguer_correction,
    )

    gamma_arr = compute_normal_gravity_mgal(lats) if meta.get("gamma_min_mgal") is not None else None
    fac_arr   = compute_free_air_correction(elevs, lats) if meta.get("fac_min_mgal") is not None else None
    bc_arr    = compute_bouguer_correction(elevs, params.reduction_density_gcc) if meta.get("bc_min_mgal") is not None else None

    corrected: List[CorrectedStation] = []
    for i, s in enumerate(stations):
        corrected.append(
            CorrectedStation(
                station_id=str(s.get("station_id", f"ST_{i:06d}")),
                lat_deg=float(lats[i]),
                lon_deg=float(lons[i]),
                elev_m=float(elevs[i]) if not math.isnan(float(elevs[i])) else 0.0,
                g_obs_mgal=float(g_obs_original[i]),
                gamma_mgal=float(gamma_arr[i]) if gamma_arr is not None else None,
                fac_mgal=float(fac_arr[i])   if fac_arr   is not None else None,
                bc_mgal=float(bc_arr[i])     if bc_arr    is not None else None,
                tc_mgal=float(tc_per_station[i]) if tc_per_station is not None else None,
                g_bouguer_mgal=float(g_reduced[i]),
                uncertainty_mgal=float(s.get("uncertainty_mgal", 0.02)),
                gravity_type=meta["output_gravity_type"],
            )
        )

    # F2B — las pre-reducciones de campo van PRIMERO en la lista (orden real).
    _all_corrections = (
        list(prereduction_meta.get("corrections_applied", []))
        + list(meta["corrections_applied"])
    )
    report = CorrectionReport(
        n_stations=len(stations),
        corrections_applied=_all_corrections,
        reduction_density_gcc=params.reduction_density_gcc,
        dem_source=dem_source,
        terrain_radius_m=params.terrain_radius_m if params.apply_terrain else None,
        fac_min_mgal=meta.get("fac_min_mgal"),
        fac_max_mgal=meta.get("fac_max_mgal"),
        bc_min_mgal=meta.get("bc_min_mgal"),
        bc_max_mgal=meta.get("bc_max_mgal"),
        tc_min_mgal=float(tc_per_station.min()) if tc_per_station is not None else None,
        tc_max_mgal=float(tc_per_station.max()) if tc_per_station is not None else None,
        g_bouguer_min_mgal=meta.get("g_reduced_min_mgal"),
        g_bouguer_max_mgal=meta.get("g_reduced_max_mgal"),
        tide_min_mgal=prereduction_meta.get("tide_min_mgal"),
        tide_max_mgal=prereduction_meta.get("tide_max_mgal"),
        drift_rate_mgal_per_day=prereduction_meta.get("drift_rate_mgal_per_day"),
        drift_closure_mgal=prereduction_meta.get("drift_closure_mgal"),
        drift_n_base=prereduction_meta.get("drift_n_base"),
        warnings=list(prereduction_meta.get("warnings", [])),
    )

    _log.info(
        "[CORRECTIONS-API] %d estaciones — tipo_salida=%s correcciones=%s",
        len(stations),
        meta["output_gravity_type"],
        meta["corrections_applied"],
    )

    return ApplyCorrectionsResponse(
        corrected=corrected,
        report=report,
        output_gravity_type=meta["output_gravity_type"],
    )


# ---------------------------------------------------------------------------
# F2B — POST /gravity-corrections/regional-residual (producto de usuario)
# ---------------------------------------------------------------------------

@router.post("/regional-residual")
def regional_residual_endpoint(req: "RegionalResidualRequest"):
    """Separa regional/residual (tendencia polinomial u continuación ascendente).

    Producto de MAPA y decisión del usuario — cada respuesta lleva la
    advertencia medida: NO se aplica automático antes de invertir. Acepta
    x_m/y_m (metros locales del import) o lat_deg/lon_deg (se proyecta
    equirectangular local SOLO para la separación, no georreferencia).
    `output_format=csv` devuelve el CSV descargable por estación.
    """
    from fastapi.responses import PlainTextResponse

    from services.regional_residual_service import (
        result_to_csv,
        separate_regional_residual,
    )

    stations = req.stations
    if len(stations) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"Se necesitan ≥8 estaciones (hay {len(stations)}).",
        )
    ids = [str(s.get("station_id", f"ST_{i:06d}")) for i, s in enumerate(stations)]
    try:
        vals = np.array([float(s[req.value_column]) for s in stations])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Columna de valor '{req.value_column}' ausente o no numérica en "
                f"alguna estación: {exc}"
            ),
        ) from exc

    if all(("x_m" in s and "y_m" in s) for s in stations):
        xs = np.array([float(s["x_m"]) for s in stations])
        ys = np.array([float(s["y_m"]) for s in stations])
    elif all(("lat_deg" in s and "lon_deg" in s) for s in stations):
        lats = np.array([float(s["lat_deg"]) for s in stations])
        lons = np.array([float(s["lon_deg"]) for s in stations])
        lat0 = float(np.mean(lats))
        xs = (lons - float(np.mean(lons))) * 111_320.0 * math.cos(math.radians(lat0))
        ys = (lats - lat0) * 110_540.0
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                "Cada estación debe traer x_m/y_m (metros locales) o "
                "lat_deg/lon_deg para la separación regional-residual."
            ),
        )

    try:
        res = separate_regional_residual(
            xs, ys, vals,
            method=req.method, order=req.order, height_m=req.height_m,
            with_grids=req.include_grids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.output_format == "csv":
        csv_text = result_to_csv(ids, xs, ys, vals, res, value_name=req.value_column)
        return PlainTextResponse(
            csv_text, media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                    f'attachment; filename="regional_residual_{req.method}.csv"'
            },
        )

    from core.utils import sanitize_nan

    payload = {
        "method": res.method,
        "report": res.report,
        "stations": [
            {
                "station_id": ids[i],
                "x_m": float(xs[i]),
                "y_m": float(ys[i]),
                req.value_column: float(vals[i]),
                "regional": float(res.regional[i]),
                "residual": float(res.residual[i]),
            }
            for i in range(len(vals))
        ],
    }
    if req.include_grids and res.grid is not None:
        payload["grids"] = {
            **res.grid.meta(),
            "observed": res.grid.values.tolist(),
            "regional": res.regional_grid.tolist(),
            "residual": res.residual_grid.tolist(),
        }
    return sanitize_nan(payload)


# ---------------------------------------------------------------------------
# POST /gravity-corrections/nettleton
# ---------------------------------------------------------------------------

@router.post("/nettleton")
def run_nettleton_analysis(
    stations: List[dict],
    density_min: float = 1.8,
    density_max: float = 3.5,
    density_step: float = 0.05,
) -> dict:
    """
    Análisis de Nettleton: densidad de reducción óptima que minimiza
    la correlación entre la anomalía de Bouguer y la topografía.
    """
    if not stations:
        raise HTTPException(status_code=422, detail="Se requiere al menos 1 estación.")

    try:
        lats  = np.array([float(s["lat_deg"])    for s in stations])
        elevs = np.array([float(s["elev_m"])     for s in stations])
        g_obs = np.array([float(s["g_obs_mgal"]) for s in stations])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Error al extraer columnas: {exc}") from exc

    densities = np.arange(density_min, density_max + density_step / 2, density_step)
    result = nettleton_analysis(g_obs, elevs, lats, densities)
    return result
