import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from core import gee_client
from core.block_model_store import clean_trace_id, load_project_meta
from core.config import PROJECTS_DIR
from core.geo_utils import compute_bbox
from core.logging import get_logger
from core.utils import utc_now_iso, clean_project_id, safe_float
from schemas.spectral_schema import (
    SpectralAoi,
    SpectralImageSelection,
    SpectralIndexStats,
    SpectralIndices,
    SpectralIndicesBlock,
    SpectralIndicesResponse,
    SpectralQuality,
    SurfaceSupportScore,
)


VERSION = "spectral_v0_1"
SOURCE = "sentinel2_l2a_gee"
COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
CACHE_FILENAME = "spectral_indices.json"
DEFAULT_EXTENT_M = 3_000.0
SCALE_M = 20
MAX_PIXELS = 100_000_000
TILE_SCALE = 4
MIN_VALID_PIXEL_COUNT = 20
MIN_VALID_PIXEL_RATIO = 0.05

FORMULAS = {
    "ndvi": "(B8 - B4) / (B8 + B4)",
    "iron_oxide_proxy": "B4 / B2",
    "clay_proxy": "B11 / B12",
}

DISCLAIMER_TEXT = [
    "Los indices espectrales son proxy superficial y evidencia exploratoria.",
    "No confirman mineralizacion, cobre, oro, porfido ni recurso.",
    "No confirman deposito economico ni ley estimada desde satelite.",
]

SCL_CLASSES_KEPT = [4, 5, 7]

_log = get_logger(__name__)


def get_spectral_indices(
    project_id: str,
    force_refresh: bool = False,
) -> SpectralIndicesResponse:
    clean_project_id = clean_project_id(project_id)
    context = _build_project_context(clean_project_id)
    cache_path = get_project_spectral_cache_path(clean_project_id)

    if not force_refresh:
        cached = _read_valid_cache(cache_path, context["cache_key"])
        if cached is not None:
            return SpectralIndicesResponse(**cached)

    if not gee_client.is_available():
        response = _not_evaluated_response(
            clean_project_id,
            context,
            warning="Google Earth Engine no esta inicializado; indices no evaluados.",
        )
        return response

    try:
        response = _compute_spectral_indices_gee(clean_project_id, context)
    except Exception as exc:
        _log.warning(
            "spectral_indices_gee_failed",
            project_id=clean_project_id,
            error=str(exc)[:200],
        )
        response = _not_evaluated_response(
            clean_project_id,
            context,
            warning="Error consultando GEE; indices no evaluados.",
        )

    if _is_cacheable_response(response):
        _write_cache(cache_path, response)

    return response


def load_cached_spectral_indices(project_id: Optional[str]) -> Optional[dict]:
    if not project_id:
        return None

    try:
        clean_project_id = clean_project_id(project_id)
        cache_path = get_project_spectral_cache_path(clean_project_id)
        if not cache_path.exists():
            return None

        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def get_project_spectral_cache_path(project_id: str) -> Path:
    clean_project_id = clean_project_id(project_id)
    return PROJECTS_DIR / clean_project_id / CACHE_FILENAME


def _project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _build_project_context(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        raise ValueError("Proyecto no encontrado.")

    meta = load_project_meta(project_id)
    if not meta:
        raise ValueError("Proyecto sin coordenadas geoespaciales.")

    center_lat = safe_float(meta.get("latitude"))
    center_lon = safe_float(meta.get("longitude"))
    if center_lat is None or center_lon is None:
        raise ValueError("Proyecto sin latitude/longitude.")

    extent_x_m, extent_z_m, extent_source = _derive_project_extent(project_id)
    bbox = compute_bbox(
        center_lat=center_lat,
        center_lon=center_lon,
        extent_x_m=extent_x_m,
        extent_z_m=extent_z_m,
    )
    date_start, date_end = _seasonal_date_window(center_lat)
    buffer_km = round((max(extent_x_m, extent_z_m) * 0.10) / 1000.0, 3)

    context = {
        "project_id": project_id,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "extent_x_m": float(extent_x_m),
        "extent_z_m": float(extent_z_m),
        "extent_source": extent_source,
        "buffer_km": buffer_km,
        "bbox": bbox,
        "date_start": date_start,
        "date_end": date_end,
        "version": VERSION,
        "collection": COLLECTION,
        "formulas": FORMULAS,
        "scl_classes_kept": SCL_CLASSES_KEPT,
        "scale_m": SCALE_M,
        "cloud_filter": "CLOUDY_PIXEL_PERCENTAGE < 20",
        "snow_filter": "SNOW_ICE_PERCENTAGE < 10",
    }
    context["cache_key"] = _cache_key(context)
    return context


def _latest_source_gravity_csv(project_id: str) -> Optional[Path]:
    runs_dir = _project_dir(project_id) / "runs"
    if not runs_dir.exists():
        return None

    for run_dir in sorted(
        (path for path in runs_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        csv_path = run_dir / "source_gravity.csv"
        if csv_path.exists():
            return csv_path

    return None


def _derive_project_extent(project_id: str) -> tuple[float, float, str]:
    csv_path = _latest_source_gravity_csv(project_id)
    if not csv_path:
        return DEFAULT_EXTENT_M, DEFAULT_EXTENT_M, "default_no_run"

    xs: list[float] = []
    zs: list[float] = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if not reader.fieldnames:
                raise ValueError("CSV sin headers.")
            header_map = {
                header.strip().lower(): header
                for header in reader.fieldnames
                if header is not None
            }
            x_key = header_map.get("x_m")
            z_key = header_map.get("z_m")
            if not x_key or not z_key:
                raise ValueError("CSV sin columnas x_m/z_m.")

            for row in reader:
                xs.append(float(str(row.get(x_key, "")).strip()))
                zs.append(float(str(row.get(z_key, "")).strip()))

        if not xs or not zs:
            raise ValueError("CSV sin observaciones validas.")

        extent_x_m = max(xs) - min(xs)
        extent_z_m = max(zs) - min(zs)
        if extent_x_m <= 0 or extent_z_m <= 0:
            raise ValueError("CSV con extent degenerado.")
        return float(extent_x_m), float(extent_z_m), "source_gravity_csv"
    except Exception as exc:
        _log.warning(
            "spectral_extent_fallback",
            project_id=project_id,
            csv_path=str(csv_path),
            error=str(exc),
        )
        return DEFAULT_EXTENT_M, DEFAULT_EXTENT_M, "default_extent_fallback"


def _seasonal_date_window(lat: float) -> tuple[str, str]:
    today = date.today()
    year = today.year

    if lat >= 23.5:
        return f"{year - 1}-06-01", f"{year}-09-30"
    if lat <= -23.5:
        return f"{year - 1}-12-01", f"{year}-03-31"

    start = today - timedelta(days=365)
    return start.isoformat(), today.isoformat()


def _mask_s2_scl(image):
    import ee

    scl = image.select("SCL")
    valid = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
    return image.updateMask(valid)


def _compute_spectral_indices_gee(
    project_id: str,
    context: dict,
) -> SpectralIndicesResponse:
    import ee

    bbox = context["bbox"]
    region = ee.Geometry.Rectangle(
        [bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]]
    )

    collection = (
        ee.ImageCollection(COLLECTION)
        .filterBounds(region)
        .filterDate(context["date_start"], context["date_end"])
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .filter(ee.Filter.lt("SNOW_ICE_PERCENTAGE", 10))
    )
    image_count = int(collection.size().getInfo())

    if image_count <= 0:
        return _not_evaluated_response(
            project_id,
            context,
            image_count=0,
            warning="Coleccion Sentinel-2 vacia para AOI/rango temporal.",
        )

    composite = collection.map(_mask_s2_scl).median()
    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("ndvi")
    iron_den = composite.select("B2").max(ee.Image.constant(1))
    clay_den = composite.select("B12").max(ee.Image.constant(1))
    iron = composite.select("B4").divide(iron_den).rename("iron_oxide_proxy")
    clay = composite.select("B11").divide(clay_den).rename(
        "clay_proxy"
    )
    indices = ndvi.addBands(iron).addBands(clay).toFloat()

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.percentile([90]), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    stats = indices.reduceRegion(
        reducer=reducer,
        geometry=region,
        scale=SCALE_M,
        maxPixels=MAX_PIXELS,
        bestEffort=True,
        tileScale=TILE_SCALE,
    ).getInfo()

    total_stats = (
        ee.Image.constant(1)
        .rename("total")
        .clip(region)
        .reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=region,
            scale=SCALE_M,
            maxPixels=MAX_PIXELS,
            bestEffort=True,
            tileScale=TILE_SCALE,
        )
        .getInfo()
    )

    total_pixel_count = _safe_int(total_stats.get("total"), 0)
    ndvi_count = _safe_int(stats.get("ndvi_count"), 0)
    iron_count = _safe_int(stats.get("iron_oxide_proxy_count"), 0)
    clay_count = _safe_int(stats.get("clay_proxy_count"), 0)
    valid_pixel_count = min(ndvi_count, iron_count, clay_count)
    valid_pixel_ratio = (
        valid_pixel_count / total_pixel_count if total_pixel_count > 0 else 0.0
    )

    low_valid_pixels = (
        valid_pixel_count < MIN_VALID_PIXEL_COUNT
        or valid_pixel_ratio < MIN_VALID_PIXEL_RATIO
    )
    status = "low_valid_pixels" if low_valid_pixels else "evaluated"
    warnings: list[str] = []
    if low_valid_pixels:
        warnings.append(
            "Pocos pixeles validos tras mascara SCL; no se calcula soporte superficial."
        )

    ndvi_stats = _index_stats(
        stats,
        "ndvi",
        FORMULAS["ndvi"],
        status="evaluated" if ndvi_count > 0 else "not_evaluated",
    )
    iron_stats = _index_stats(
        stats,
        "iron_oxide_proxy",
        FORMULAS["iron_oxide_proxy"],
        status=status,
        normalized_score=None
        if low_valid_pixels
        else _score_iron(safe_float(stats.get("iron_oxide_proxy_p90"))),
    )
    clay_stats = _index_stats(
        stats,
        "clay_proxy",
        FORMULAS["clay_proxy"],
        status=status,
        normalized_score=None
        if low_valid_pixels
        else _score_clay(safe_float(stats.get("clay_proxy_p90"))),
    )

    ndvi_mean = ndvi_stats.mean
    if ndvi_mean is not None and ndvi_mean >= 0.35:
        warning = (
            "NDVI alto: vegetacion puede ocultar o contaminar proxies superficiales."
        )
        iron_stats.warning = warning
        clay_stats.warning = warning
        warnings.append(warning)

    surface_support = _surface_support_score(
        iron_score=iron_stats.normalized_score,
        clay_score=clay_stats.normalized_score,
        ndvi_mean=ndvi_mean,
        valid_pixel_ratio=valid_pixel_ratio,
        low_valid_pixels=low_valid_pixels,
    )

    return SpectralIndicesResponse(
        project_id=project_id,
        spectral_indices=SpectralIndicesBlock(
            version=VERSION,
            source=SOURCE,
            status=status,
            cache_key=context["cache_key"],
            computed_at=utc_now_iso(use_z_format=True),
            aoi=_aoi(context),
            image_selection=_image_selection(context, image_count=image_count),
            quality=SpectralQuality(
                valid_pixel_count=valid_pixel_count,
                total_pixel_count=total_pixel_count,
                valid_pixel_ratio=_round_optional(valid_pixel_ratio, 4),
                cloud_mask_used=True,
                snow_mask_used=True,
                scl_mask_used=True,
                scale_m=SCALE_M,
            ),
            indices=SpectralIndices(
                ndvi=ndvi_stats,
                iron_oxide_proxy=iron_stats,
                clay_proxy=clay_stats,
            ),
            surface_support_score=surface_support,
            disclaimers=DISCLAIMER_TEXT,
            warnings=warnings,
        ),
    )


def _index_stats(
    stats: dict,
    key: str,
    formula: str,
    status: str,
    normalized_score: Optional[float] = None,
) -> SpectralIndexStats:
    return SpectralIndexStats(
        mean=_round_optional(safe_float(stats.get(f"{key}_mean")), 6),
        p90=_round_optional(safe_float(stats.get(f"{key}_p90")), 6),
        std_dev=_round_optional(safe_float(stats.get(f"{key}_stdDev")), 6),
        valid_pixel_count=_safe_int(stats.get(f"{key}_count"), None),
        normalized_score=_round_optional(normalized_score, 4),
        status=status,
        formula=formula,
        warning=None,
    )


def _surface_support_score(
    iron_score: Optional[float],
    clay_score: Optional[float],
    ndvi_mean: Optional[float],
    valid_pixel_ratio: float,
    low_valid_pixels: bool,
) -> SurfaceSupportScore:
    if low_valid_pixels or iron_score is None or clay_score is None:
        return SurfaceSupportScore(
            value=None,
            status="not_evaluated",
            explanation=(
                "Soporte superficial no evaluado por baja calidad de pixeles o "
                "proxies incompletos. No confirma mineralizacion."
            ),
        )

    ndvi_factor = 1.0
    if ndvi_mean is not None and ndvi_mean >= 0.45:
        ndvi_factor = 0.40
    elif ndvi_mean is not None and ndvi_mean >= 0.35:
        ndvi_factor = 0.70

    quality_factor = float(np.clip(valid_pixel_ratio / 0.75, 0.0, 1.0))
    raw_score = (float(iron_score) * 0.50) + (float(clay_score) * 0.50)
    value = float(np.clip(raw_score * ndvi_factor * quality_factor, 0.0, 1.0))

    return SurfaceSupportScore(
        value=round(value, 4),
        status="evaluated",
        explanation=(
            "Combinacion normalizada de proxies superficiales de oxidos de hierro "
            "y arcillas/OH, penalizada por NDVI alto y calidad de pixeles. "
            "No confirma mineralizacion ni deposito economico."
        ),
    )


def _not_evaluated_response(
    project_id: str,
    context: dict,
    warning: str,
    image_count: Optional[int] = None,
) -> SpectralIndicesResponse:
    return SpectralIndicesResponse(
        project_id=project_id,
        spectral_indices=SpectralIndicesBlock(
            version=VERSION,
            source=SOURCE,
            status="not_evaluated",
            cache_key=context["cache_key"],
            computed_at=utc_now_iso(use_z_format=True),
            aoi=_aoi(context),
            image_selection=_image_selection(context, image_count=image_count),
            quality=SpectralQuality(
                valid_pixel_count=None,
                total_pixel_count=None,
                valid_pixel_ratio=None,
                cloud_mask_used=True,
                snow_mask_used=True,
                scl_mask_used=True,
                scale_m=SCALE_M,
            ),
            indices=SpectralIndices(
                ndvi=SpectralIndexStats(
                    status="not_evaluated",
                    formula=FORMULAS["ndvi"],
                ),
                iron_oxide_proxy=SpectralIndexStats(
                    status="not_evaluated",
                    formula=FORMULAS["iron_oxide_proxy"],
                ),
                clay_proxy=SpectralIndexStats(
                    status="not_evaluated",
                    formula=FORMULAS["clay_proxy"],
                ),
            ),
            surface_support_score=SurfaceSupportScore(
                value=None,
                status="not_evaluated",
                explanation="No evaluado; no confirma mineralizacion.",
            ),
            disclaimers=DISCLAIMER_TEXT,
            warnings=[warning],
        ),
    )


def _aoi(context: dict) -> SpectralAoi:
    return SpectralAoi(
        center_lat=context["center_lat"],
        center_lon=context["center_lon"],
        buffer_km=context["buffer_km"],
        extent_x_m=context["extent_x_m"],
        extent_z_m=context["extent_z_m"],
        bbox=context["bbox"],
    )


def _image_selection(context: dict, image_count: Optional[int]) -> SpectralImageSelection:
    return SpectralImageSelection(
        collection=COLLECTION,
        date_start=context["date_start"],
        date_end=context["date_end"],
        image_count=image_count,
        cloud_filter=context["cloud_filter"],
        snow_filter=context["snow_filter"],
        scl_classes_kept=list(SCL_CLASSES_KEPT),
    )


def _read_valid_cache(cache_path: Path, cache_key: str) -> Optional[dict]:
    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        spectral = data.get("spectral_indices") if isinstance(data, dict) else None
        if not isinstance(spectral, dict):
            return None
        if spectral.get("cache_key") != cache_key:
            return None
        if spectral.get("version") != VERSION:
            return None
        return data
    except Exception as exc:
        _log.warning("spectral_cache_read_failed", path=str(cache_path), error=str(exc))
        return None


def _write_cache(cache_path: Path, response: SpectralIndicesResponse) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = response.model_dump() if hasattr(response, "model_dump") else response.dict()
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(cache_path)
    except Exception as exc:
        _log.warning("spectral_cache_write_failed", path=str(cache_path), error=str(exc))


def _is_cacheable_response(response: SpectralIndicesResponse) -> bool:
    spectral = response.spectral_indices
    if spectral.status in {"evaluated", "low_valid_pixels"}:
        return True
    return spectral.image_selection.image_count is not None


def _cache_key(context: dict) -> str:
    key_payload = {
        "version": context["version"],
        "collection": context["collection"],
        "formulas": context["formulas"],
        "scl_classes_kept": context["scl_classes_kept"],
        "center_lat": round(float(context["center_lat"]), 8),
        "center_lon": round(float(context["center_lon"]), 8),
        "extent_x_m": round(float(context["extent_x_m"]), 3),
        "extent_z_m": round(float(context["extent_z_m"]), 3),
        "bbox": {
            key: round(float(value), 8)
            for key, value in sorted(context["bbox"].items())
        },
        "date_start": context["date_start"],
        "date_end": context["date_end"],
        "scale_m": context["scale_m"],
        "cloud_filter": context["cloud_filter"],
        "snow_filter": context["snow_filter"],
    }
    raw = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _score_iron(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(np.clip((float(value) - 1.2) / 1.0, 0.0, 1.0))


def _score_clay(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(np.clip((float(value) - 1.0) / 0.8, 0.0, 1.0))


def _safe_int(value: Any, fallback: Optional[int]) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _round_optional(value: Optional[float], digits: int) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)