"""Pipeline de ENRIQUECIMIENTO de paquetes CSV (Preparación).

A diferencia de `csv_package_service.build_package_text` (que solo FUSIONA lo que
el usuario subió en un paquete TQPKG), este servicio DERIVA con física/matemática
real todo lo que falte para que el dato quede listo para inversión:

  • Elevación faltante  → muestreo bilineal sobre un DEM (opentopo_service).
  • Gravimetría cruda   → correcciones GRS80/FAC/BC (gravity_corrections_service).
  • Coordenadas         → lat/lon ↔ UTM real (coordinate_transform_real / pyproj).
  • σ por estación      → piso del gravímetro o adaptivo (core.config).
  • Calidad             → score 0–100 ya calculado por el import (csv_analysis).
  • IGRF (magnético)    → derivado offline (armónicos esféricos IGRF-14) desde la
                          ubicación + fecha del survey (igrf_service), o lo provisto.

GUARDRAIL — NADA inventado: cada columna nueva proviene de una fórmula o de un
servicio físico existente. Lo que NO se puede derivar queda en `None` (la columna
no se agrega) y se reporta como bandera accionable en `enrichment_summary`, para
que la UI pida el contexto que falta en vez de fabricar un número.

El resultado (`EnrichmentResult`) lleva arrays-override paralelos a las estaciones
+ overrides de config (IGRF, densidad) + el `enrichment_summary` estructurado. El
endpoint los pasa a `build_package_text` para emitir el TQPKG enriquecido.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Estados de cada paso del resumen (vocabulario cerrado para la UI).
STATUS_DERIVED = "derived"            # calculado desde física/matemática
STATUS_ALREADY_PRESENT = "already_present"  # el dato ya venía en el archivo
STATUS_SKIPPED = "skipped"            # no aplica a este tipo de dato
STATUS_NEEDS_CONTEXT = "needs_context"  # derivable SI el usuario aporta un input
STATUS_NOT_DERIVABLE = "not_derivable"  # no derivable offline → null + bandera

# DemFetcher: async (south, north, west, east) -> (lat_1d, lon_1d, elev_2d, cell_deg, info)
DemFetcher = Callable[
    [float, float, float, float],
    Awaitable["tuple[np.ndarray, np.ndarray, np.ndarray, float, dict]"],
]


@dataclass
class EnrichmentStep:
    """Una entrada del resumen: qué intentó derivar el backend y con qué resultado."""

    key: str
    label: str
    status: str = STATUS_SKIPPED
    method: Optional[str] = None
    detail: str = ""
    n_stations: int = 0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "method": self.method,
            "detail": self.detail,
            "n_stations": self.n_stations,
        }


@dataclass
class EnrichmentResult:
    """Salida del pipeline: overrides paralelos a las estaciones + resumen."""

    elevations: Optional[List[float]] = None
    sigmas: Optional[List[float]] = None
    latlon: Optional[List[dict]] = None
    g_mgal: Optional[List[float]] = None         # gravedad corregida (mGal), si aplica
    gravity_type_out: Optional[str] = None       # tipo de salida tras correcciones
    config_overrides: dict = field(default_factory=dict)  # IGRF, densidad de reducción
    steps: List[EnrichmentStep] = field(default_factory=list)
    needs_context: List[str] = field(default_factory=list)
    columns_added: List[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "version": "enrichment_v1",
            "steps": [s.to_dict() for s in self.steps],
            "needs_context": list(dict.fromkeys(self.needs_context)),
            "columns_added": list(dict.fromkeys(self.columns_added)),
            "nothing_fabricated": True,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers puros (unit-testables sin red ni FastAPI)
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def valid_latlon_list(raw: Optional[list], n: int) -> Optional[List[dict]]:
    """Devuelve la lista de lat/lon si está completa y es física; si no, None.

    Exige que las N estaciones tengan lat∈[-90,90] y lon∈[-180,180] finitos. Una
    sola estación inválida invalida el conjunto (no se completa por interpolación).
    """
    if not raw or len(raw) != n:
        return None
    out: List[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            return None
        lat = _coerce_float(r.get("lat_deg"))
        lon = _coerce_float(r.get("lon_deg"))
        if lat is None or lon is None:
            return None
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return None
        out.append({"lat_deg": lat, "lon_deg": lon, "elev_m": _coerce_float(r.get("elev_m"))})
    return out


def reconstruct_latlon_from_utm(
    observations: list,
    coordinate_transform,
    *,
    utm_zone: Optional[str],
) -> Optional[List[dict]]:
    """Reconstruye lat/lon por estación desde coords UTM locales + zona UTM (pyproj).

    El import deja las observaciones en metros locales (origen = esquina SW) y guarda
    el origen absoluto en `coordinate_transform.absolute_origin = {easting, northing}`.
    UTM_estación = origen_absoluto + (x_m, z_m); luego pyproj UTM→WGS84. Requiere zona
    UTM (de `utm_zone` o, si el import la infirió, de `coordinate_transform`). Devuelve
    None si no hay origen absoluto o zona resoluble.
    """
    if coordinate_transform is None:
        return None
    origin = getattr(coordinate_transform, "absolute_origin", None)
    if not origin:
        return None
    east0 = _coerce_float(origin.get("easting"))
    north0 = _coerce_float(origin.get("northing"))
    if east0 is None or north0 is None:
        return None

    epsg = getattr(coordinate_transform, "epsg_code", None)
    zone = utm_zone or getattr(coordinate_transform, "utm_zone", None)
    if epsg is None and not zone:
        return None

    try:
        from services.coordinate_transform_real import transform_utm_to_wgs84
    except Exception:  # pragma: no cover - pyproj ausente
        return None

    out: List[dict] = []
    for o in observations:
        easting = east0 + float(o.x_m)
        northing = north0 + float(o.z_m)
        try:
            lat, lon = transform_utm_to_wgs84(
                easting, northing, utm_zone=zone, epsg_code=epsg,
            )
        except Exception:
            return None
        out.append({"lat_deg": float(lat), "lon_deg": float(lon), "elev_m": None})
    return out


def sample_dem_elevations(
    lats: np.ndarray,
    lons: np.ndarray,
    dem_lat_1d: np.ndarray,
    dem_lon_1d: np.ndarray,
    dem_elev_2d: np.ndarray,
) -> np.ndarray:
    """Muestrea la elevación del DEM en cada estación por interpolación BILINEAL.

    `dem_lat_1d` va de norte→sur (fila 0 = latitud máxima), `dem_lon_1d` de oeste→este
    (convención AAIGrid de opentopo_service). Estaciones fuera del bbox se recortan al
    borde (clamp). Devuelve un array de elevaciones [m AMSL] paralelo a las estaciones.
    """
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    lat_axis = np.asarray(dem_lat_1d, dtype=np.float64)
    lon_axis = np.asarray(dem_lon_1d, dtype=np.float64)
    elev = np.asarray(dem_elev_2d, dtype=np.float64)

    # lat va descendente → interpolamos sobre el eje invertido (ascendente) para np.interp.
    lat_asc = lat_axis[::-1]
    nrows = lat_axis.shape[0]

    out = np.empty(lats.shape[0], dtype=np.float64)
    for i in range(lats.shape[0]):
        # Índice fraccionario de columna (lon, ascendente).
        cj = np.interp(lons[i], lon_axis, np.arange(lon_axis.shape[0]))
        # Índice fraccionario de fila en eje ascendente, luego a índice real (descendente).
        ri_asc = np.interp(lats[i], lat_asc, np.arange(nrows))
        ri = (nrows - 1) - ri_asc

        r0 = int(np.clip(np.floor(ri), 0, nrows - 1))
        r1 = int(np.clip(r0 + 1, 0, nrows - 1))
        c0 = int(np.clip(np.floor(cj), 0, lon_axis.shape[0] - 1))
        c1 = int(np.clip(c0 + 1, 0, lon_axis.shape[0] - 1))
        fr = float(np.clip(ri - r0, 0.0, 1.0))
        fc = float(np.clip(cj - c0, 0.0, 1.0))

        top = elev[r0, c0] * (1 - fc) + elev[r0, c1] * fc
        bot = elev[r1, c0] * (1 - fc) + elev[r1, c1] * fc
        out[i] = top * (1 - fr) + bot * fr
    return out


def derive_sigmas_mgal(
    g_mgal: np.ndarray,
    gravimeter_type: str,
    noise_pct: float = 0.02,
) -> "tuple[List[float], str, str]":
    """σ por estación [mGal] = max(piso_instrumental, noise_pct·|g|).

    El piso viene de `GRAVIMETER_NOISE_FLOOR` (especificaciones de fábrica). Para
    gravímetro 'unknown' el piso es conservador (0.020 mGal) → comportamiento adaptivo.
    Devuelve (sigmas, method, detail).
    """
    from core.config import GRAVIMETER_NOISE_FLOOR

    gt = (gravimeter_type or "unknown").strip().lower()
    floor = float(GRAVIMETER_NOISE_FLOOR.get(gt, GRAVIMETER_NOISE_FLOOR["unknown"]))
    g = np.abs(np.asarray(g_mgal, dtype=np.float64))
    sigmas = np.maximum(floor, float(noise_pct) * g)
    known = gt in GRAVIMETER_NOISE_FLOOR and gt != "unknown"
    method = f"gravimeter_floor:{gt}" if known else "adaptive_floor"
    rango = (
        f"rango {sigmas.min():.4g}–{sigmas.max():.4g} mGal"
        if sigmas.size else "sin estaciones"
    )
    detail = f"σ = max({floor:.3g} mGal piso {gt}, {noise_pct:.0%}·|g|); {rango}"
    return [float(x) for x in sigmas], method, detail


def resolve_igrf(
    config: dict,
    lats: Optional[np.ndarray] = None,
    lons: Optional[np.ndarray] = None,
    elevations: Optional[np.ndarray] = None,
) -> "tuple[dict, EnrichmentStep, List[str]]":
    """Resuelve el IGRF (inc/dec/intensidad) para magnetometría.

    Prioridad:
      1. Si el usuario provee un IGRF válido y NO-default en el contexto → se acepta
         tal cual (already_present), no se re-computa.
      2. Si no, se DERIVA offline con física real (armónicos esféricos IGRF-14,
         `igrf_service`) desde el centroide del survey (lat/lon) + la fecha del
         survey. El IGRF varía <0.01° sobre un survey local, así que un valor en el
         centroide es físicamente correcto (igual que el triple IGRF embebido que
         usan ingest_do27/ingest_raglan para todo el survey).
      3. Si falta ubicación o fecha → needs_context (NADA fabricado).

    Devuelve (overrides, step, needs_context_keys).
    """
    inc = _coerce_float(config.get("inclination_deg"))
    dec = _coerce_float(config.get("declination_deg"))
    b0 = _coerce_float(config.get("field_intensity_nt"))

    # Defaults del schema (no son una medición real): inc=-30, dec=2, B0=23500.
    is_default = (
        inc is not None and abs(inc - (-30.0)) < 1e-9
        and dec is not None and abs(dec - 2.0) < 1e-9
        and b0 is not None and abs(b0 - 23500.0) < 1e-9
    )
    valid = (
        inc is not None and -90.0 <= inc <= 90.0
        and dec is not None and -180.0 <= dec <= 180.0
        and b0 is not None and 20000.0 <= b0 <= 70000.0
    )

    step = EnrichmentStep(
        key="igrf",
        label="Campo geomagnético IGRF (inclinación/declinación/intensidad)",
    )

    # ── 1. Provisto por el usuario (no-default) → se respeta ──────────────────
    if valid and not is_default:
        step.status = STATUS_ALREADY_PRESENT
        step.method = "contexto_usuario"
        step.detail = f"I={inc:.2f}°, D={dec:.2f}°, B0={b0:.0f} nT (provistos en el contexto)"
        return {
            "inclination_deg": inc,
            "declination_deg": dec,
            "field_intensity_nt": b0,
        }, step, []

    # ── 2/3. Derivación offline desde ubicación + fecha ───────────────────────
    needs: List[str] = []
    has_location = lats is not None and lons is not None and len(lats) > 0
    raw_date = config.get("survey_date")
    if raw_date is None or (isinstance(raw_date, str) and not raw_date.strip()):
        needs.append("survey_date")
    if not has_location:
        needs.append("utm_zone")

    if needs:
        step.status = STATUS_NEEDS_CONTEXT
        faltan = []
        if "survey_date" in needs:
            faltan.append("la fecha del survey (año o ISO, ej. 2016 o 2016-07)")
        if "utm_zone" in needs:
            faltan.append("la ubicación (lat/lon o zona UTM)")
        step.detail = (
            "IGRF derivable offline (IGRF-14), pero falta " + " y ".join(faltan) +
            ". Aporte ese contexto y se computará inclinación/declinación/intensidad."
        )
        return {}, step, needs

    from services.igrf_service import (
        igrf_field, decimal_year, METHOD_LABEL, IgrfError,
    )

    lat0 = float(np.mean(np.asarray(lats, dtype=np.float64)))
    lon0 = float(np.mean(np.asarray(lons, dtype=np.float64)))
    elev0 = (
        float(np.mean(np.asarray(elevations, dtype=np.float64)))
        if elevations is not None and len(elevations) > 0 else 0.0
    )
    try:
        yr = decimal_year(raw_date)
        field = igrf_field(lat0, lon0, elev0, yr)
    except (IgrfError, ValueError) as exc:
        step.status = STATUS_NEEDS_CONTEXT
        step.detail = (
            f"No se pudo derivar el IGRF para la fecha '{raw_date}': {exc}. "
            "Aporte una fecha dentro de 1900–2030 o el IGRF medido."
        )
        return {}, step, ["survey_date"]

    step.status = STATUS_DERIVED
    step.method = METHOD_LABEL
    step.detail = (
        f"Derivado en el centroide del survey ({lat0:.3f}°, {lon0:.3f}°, {elev0:.0f} m) "
        f"para {yr:.1f}: I={field.inclination_deg:.2f}°, D={field.declination_deg:.2f}°, "
        f"B0={field.total_intensity_nt:.0f} nT (armónicos esféricos, sin red)."
    )
    return {
        "inclination_deg": field.inclination_deg,
        "declination_deg": field.declination_deg,
        "field_intensity_nt": field.total_intensity_nt,
    }, step, []


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────────────────────────────────────────

async def enrich_package(
    primary_result,
    *,
    data_type: str,
    config: dict,
    dem_fetcher: Optional[DemFetcher] = None,
    enable_dem: bool = True,
    reduction_density_gcc: float = 2.67,
    noise_pct: float = 0.02,
) -> EnrichmentResult:
    """Ejecuta el pipeline de enriquecimiento sobre un import ya validado.

    No muta `primary_result`: devuelve overrides paralelos a las estaciones. El
    `dem_fetcher` se inyecta para testear sin red (default = opentopo_service).
    """
    is_magnetic = (data_type == "magnetic")
    obs = list(getattr(primary_result, "observations", None) or [])
    n = len(obs)
    result = EnrichmentResult()
    ctransform = getattr(primary_result, "coordinate_transform", None)

    # ── 1. Coordenadas lat/lon ────────────────────────────────────────────────
    latlon = valid_latlon_list(getattr(primary_result, "raw_latlon_elev", None), n)
    coord_step = EnrichmentStep(
        key="coordinates", label="Coordenadas geográficas (lat/lon)", n_stations=n,
    )
    if latlon is not None:
        coord_step.status = STATUS_ALREADY_PRESENT
        coord_step.method = "import_csv"
        coord_step.detail = "lat/lon presentes en el archivo cargado."
    else:
        utm_zone = config.get("utm_zone")
        latlon = reconstruct_latlon_from_utm(obs, ctransform, utm_zone=utm_zone)
        if latlon is not None:
            coord_step.status = STATUS_DERIVED
            coord_step.method = "pyproj_utm_to_wgs84"
            coord_step.detail = "lat/lon derivadas de UTM + zona vía pyproj (georef real)."
        else:
            coord_step.status = STATUS_NEEDS_CONTEXT
            coord_step.detail = (
                "Sin lat/lon ni zona UTM resoluble: indique la zona UTM (ej. '19S') "
                "para georreferenciar las estaciones."
            )
            result.needs_context.append("utm_zone")
    result.steps.append(coord_step)

    if latlon is not None:
        result.latlon = latlon

    lats = np.array([p["lat_deg"] for p in latlon]) if latlon else None
    lons = np.array([p["lon_deg"] for p in latlon]) if latlon else None

    # ── 2. Elevación (DEM) ────────────────────────────────────────────────────
    existing_elev = _existing_elevations(primary_result, latlon, n)
    elev_step = EnrichmentStep(
        key="elevation", label="Elevación del terreno (DEM)", n_stations=n,
    )
    elevations: Optional[np.ndarray] = None
    if existing_elev is not None:
        elevations = existing_elev
        elev_step.status = STATUS_ALREADY_PRESENT
        elev_step.method = "import_csv"
        elev_step.detail = (
            f"Elevación presente en el archivo (rango "
            f"{existing_elev.min():.1f}–{existing_elev.max():.1f} m)."
        )
    elif not enable_dem:
        elev_step.status = STATUS_SKIPPED
        elev_step.detail = "Muestreo de DEM desactivado para esta corrida."
    elif lats is None:
        elev_step.status = STATUS_NEEDS_CONTEXT
        elev_step.detail = "Se requiere lat/lon (ver coordenadas) para muestrear el DEM."
        result.needs_context.append("utm_zone")
    else:
        elevations, dem_detail, dem_status = await _fetch_and_sample_dem(
            lats, lons, dem_fetcher,
        )
        elev_step.status = dem_status
        elev_step.method = "opentopo_dem_bilinear" if elevations is not None else None
        elev_step.detail = dem_detail
        if dem_status == STATUS_NEEDS_CONTEXT:
            result.needs_context.append("opentopo_api_key")
    result.steps.append(elev_step)

    if elevations is not None:
        result.elevations = [float(x) for x in elevations]
        result.columns_added.append("elevation_m")
    if latlon is not None:
        result.columns_added.extend(["lat_deg", "lon_deg"])

    # ── 3. Correcciones gravimétricas (GRS80/FAC/BC) ──────────────────────────
    if not is_magnetic:
        _enrich_gravity_corrections(
            primary_result, result, lats, elevations, reduction_density_gcc, n,
        )

    # ── 4. IGRF (magnético) ───────────────────────────────────────────────────
    if is_magnetic:
        igrf_overrides, igrf_step, igrf_needs = resolve_igrf(
            config, lats, lons, elevations,
        )
        igrf_step.n_stations = n
        result.config_overrides.update(igrf_overrides)
        result.needs_context.extend(igrf_needs)
        result.steps.append(igrf_step)

    # ── 5. σ por estación ─────────────────────────────────────────────────────
    sigma_step = EnrichmentStep(
        key="sigma", label="Incertidumbre por estación (σ)", n_stations=n,
    )
    if is_magnetic:
        sigma_step.status = STATUS_SKIPPED
        sigma_step.detail = (
            "σ magnético lo deriva el motor (Std real por estación o floor=mediana); "
            "no se materializa en el paquete."
        )
    else:
        g_for_sigma = (
            np.asarray(result.g_mgal, dtype=np.float64)
            if result.g_mgal is not None
            else np.array([o.g * 1e5 for o in obs], dtype=np.float64)
        )
        sigmas, method, detail = derive_sigmas_mgal(
            g_for_sigma, str(config.get("gravimeter_type", "unknown")), noise_pct,
        )
        result.sigmas = sigmas
        result.columns_added.append("sigma_mgal")
        sigma_step.status = STATUS_DERIVED
        sigma_step.method = method
        sigma_step.detail = detail
    result.steps.append(sigma_step)

    # ── 6. Calidad (score ya calculado por el import) ─────────────────────────
    result.steps.append(_quality_step(primary_result, n))

    return result


def _existing_elevations(primary_result, latlon, n: int) -> Optional[np.ndarray]:
    """Elevaciones ya presentes (station_elevations o elev_m de lat/lon), o None."""
    se = getattr(primary_result, "station_elevations", None)
    if se is not None and len(se) == n:
        arr = np.array([_coerce_float(v) for v in se], dtype=object)
        if all(v is not None for v in arr):
            vals = np.array([float(v) for v in arr], dtype=np.float64)
            if not np.all(vals == 0.0):
                return vals
    if latlon is not None:
        elevs = [p.get("elev_m") for p in latlon]
        if all(v is not None for v in elevs):
            vals = np.array([float(v) for v in elevs], dtype=np.float64)
            if not np.all(vals == 0.0):
                return vals
    return None


async def _fetch_and_sample_dem(
    lats: np.ndarray, lons: np.ndarray, dem_fetcher: Optional[DemFetcher],
) -> "tuple[Optional[np.ndarray], str, str]":
    """Descarga el DEM del bbox y muestrea elevaciones. Falla suave (status, detail)."""
    south, north = float(np.min(lats)), float(np.max(lats))
    west, east = float(np.min(lons)), float(np.max(lons))
    # Buffer pequeño para que las estaciones del borde queden dentro del DEM.
    buf = 0.02
    fetcher = dem_fetcher or _default_dem_fetcher
    try:
        lat_1d, lon_1d, elev_2d, _cell, info = await fetcher(
            south - buf, north + buf, west - buf, east + buf,
        )
    except Exception as exc:
        from services.opentopo_service import OpenTopoKeyMissingError

        if isinstance(exc, OpenTopoKeyMissingError):
            return None, (
                "DEM no disponible: OPENTOPO_API_KEY no configurado. Configure la clave "
                "para muestrear elevación, o suba una columna de elevación."
            ), STATUS_NEEDS_CONTEXT
        return None, f"No se pudo obtener el DEM: {exc}", STATUS_NEEDS_CONTEXT

    elevs = sample_dem_elevations(lats, lons, lat_1d, lon_1d, elev_2d)
    src = info.get("source", "DEM") if isinstance(info, dict) else "DEM"
    return elevs, (
        f"Elevación muestreada del DEM ({src}) por interpolación bilineal; "
        f"rango {elevs.min():.1f}–{elevs.max():.1f} m."
    ), STATUS_DERIVED


async def _default_dem_fetcher(south, north, west, east):
    from services.opentopo_service import fetch_dem_for_survey

    return await fetch_dem_for_survey(south, north, west, east, dem_type="COP30")


def _enrich_gravity_corrections(
    primary_result,
    result: EnrichmentResult,
    lats: Optional[np.ndarray],
    elevations: Optional[np.ndarray],
    reduction_density_gcc: float,
    n: int,
) -> None:
    """Reduce gravedad cruda a anomalía de Bouguer (GRS80+FAC+BC) si hay lat+elev."""
    obs = list(getattr(primary_result, "observations", None) or [])
    meta = getattr(primary_result, "import_metadata", None)
    gravity_type_in = (getattr(meta, "gravity_type", None) or "").strip()

    from services.gravity_import_service import _FIELD_ALREADY_CORRECTED

    step = EnrichmentStep(
        key="gravity_corrections",
        label="Correcciones gravimétricas (GRS80 + Free-Air + Bouguer)",
        n_stations=n,
    )
    already = gravity_type_in in _FIELD_ALREADY_CORRECTED
    if already:
        step.status = STATUS_ALREADY_PRESENT
        step.method = "import_csv"
        step.detail = f"El dato ya es '{gravity_type_in}'; no se re-corrige."
        result.steps.append(step)
        return
    if lats is None or elevations is None:
        step.status = STATUS_NEEDS_CONTEXT
        step.detail = (
            "Gravedad cruda sin lat/elev por estación: no se aplican FAC/BC. "
            "Aporte zona UTM y elevación (o DEM) para reducir a Bouguer."
        )
        result.steps.append(step)
        return

    from services.gravity_corrections_service import apply_all_corrections

    g_in = np.array([o.g * 1e5 for o in obs], dtype=np.float64)  # m/s² → mGal
    try:
        g_corr, corr_meta = apply_all_corrections(
            lats_deg=lats,
            lons_deg=lats,  # lon no interviene en GRS80/FAC/BC (solo lat)
            elevs_m=elevations,
            g_obs_mgal=g_in,
            gravity_type_in=gravity_type_in or "g_raw",
            reduction_density_gcc=reduction_density_gcc,
            apply_lat=True, apply_fac=True, apply_bouguer=True, apply_terrain=False,
        )
    except Exception as exc:
        step.status = STATUS_NEEDS_CONTEXT
        step.detail = f"No se pudieron aplicar correcciones: {exc}"
        result.steps.append(step)
        return

    result.g_mgal = [float(x) for x in g_corr]
    result.gravity_type_out = corr_meta.get("output_gravity_type", "bouguer_anomaly")
    result.config_overrides["reduction_density_gcc"] = reduction_density_gcc
    applied = ", ".join(corr_meta.get("corrections_applied", []))
    step.status = STATUS_DERIVED
    step.method = "gravity_corrections_service"
    step.detail = (
        f"Aplicadas: {applied} → '{result.gravity_type_out}'. "
        f"g medio {corr_meta.get('g_reduced_mean_mgal', float('nan')):.4g} mGal."
    )
    result.steps.append(step)


def _quality_step(primary_result, n: int) -> EnrichmentStep:
    """Reporta el score de calidad 0–100 ya computado por el import (no recalcula)."""
    step = EnrichmentStep(key="quality", label="Calidad del dato (score 0–100)", n_stations=n)
    csv_analysis = getattr(primary_result, "csv_analysis", None)
    dq = getattr(csv_analysis, "data_quality", None) if csv_analysis else None
    if dq is None:
        step.status = STATUS_SKIPPED
        step.detail = "Score de calidad no disponible para este import."
        return step
    step.status = STATUS_DERIVED
    step.method = getattr(dq, "version", "data_quality_v0_1")
    step.detail = (
        f"Score {getattr(dq, 'score', 0.0):.0f}/100 ({getattr(dq, 'interpretation', 'POOR')}); "
        f"completitud {getattr(dq, 'completeness', 0.0):.0f}, "
        f"distribución {getattr(dq, 'spatial_distribution', 0.0):.0f}, "
        f"ruido {getattr(dq, 'noise_level', 0.0):.0f}."
    )
    return step
