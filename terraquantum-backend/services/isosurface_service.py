"""Isosurface service (Fase F4.1) — mallas suaves desde el block model.

El plan F4 pide "adiós al confeti de cubos": en vez de instanciar un cubo por
vóxel, el backend calcula ISOSUPERFICIES (marching cubes) del cuerpo anómalo a
2-3 niveles de contraste, las suaviza (Taubin, sin encoger volumen) y las entrega
al frontend como mallas indexadas.  El frontend NO calcula el nivel ni la física:
recibe posiciones/normales/índices ya en el espacio visual de Three.js.

Consistencia con el visor de vóxeles (`lib/terraQuantumGeology.ts`):
  - El campo contorneado es el CONTRASTE robusto respecto al fondo, idéntico al
    que usa el visor: `contrast = (v - background) / scale`, con
    `background = mediana`, `scale = max(P95-mediana, mediana-P5, piso)`.
  - Los niveles son fracciones del PICO de |contraste| (por defecto 50/70/90 %),
    coherentes con el "piso-relativo-al-pico" ya medido.
  - El color por vértice usa el MISMO contraste con signo → Viridis divergente
    (déficit de masa = azul/púrpura, exceso = amarillo), calculado en el frontend
    a partir de `background`/`scale` que viajan en la respuesta.

Coordenadas: se replica EXACTAMENTE el centrado + flip-Y del transporte Arrow
(`build_block_model_arrow_bytes`) para que la isosuperficie se superponga
pixel-a-pixel con los vóxeles que el visor carga desde /block-model-arrow.
"""

from __future__ import annotations

import base64
import logging
import math
from dataclasses import dataclass

import numpy as np
import polars as pl

from core.block_model_store import resolve_block_model_reference
from services.block_model_service import ensure_visual_columns

logger = logging.getLogger(__name__)

# Campos soportados y su transformación previa al cálculo de contraste.
# density: contraste lineal directo (gravedad).
# susceptibility: en escala log10 (como el visor: chiLog = log10(max(chi,0)+eps)),
#                 porque la susceptibilidad abarca órdenes de magnitud.
_SUPPORTED_FIELDS = {
    "density": {"columns": ("density", "rho", "density_t_m3"), "log": False},
    "susceptibility": {"columns": ("susceptibility_si",), "log": True},
}

# Piso de la escala robusta — idéntico al del visor (densScale mínimo 0.05 t/m³).
_SCALE_FLOOR = 0.05
# Épsilon del log de susceptibilidad — idéntico al visor.
_LOG_EPS = 1e-9
# Umbral de "anomalía débil" — idéntico al ANOMALY_WEAK_PEAK del visor: si el pico
# de |contraste| no lo supera, el cuerpo es legítimamente débil y se avisa.
_WEAK_PEAK = 0.60
# Niveles por defecto (fracciones del pico de |contraste|).
_DEFAULT_LEVELS = (0.5, 0.7, 0.9)
# Tope de celdas del volumen denso (float64). ~40M celdas ≈ 320 MB por array.
# Por encima, la grilla no es regular (coordenadas continuas) y se aborta.
_MAX_GRID_CELLS = 40_000_000
# F4.7 LOD (MEDIDO): sobre este tamaño, marching cubes usa step_size=2
# (~4-10× más rápido, pérdida visual nula — ver _lod_step).
_LOD_STEP_THRESHOLD = 2_000_000
# Iteraciones Taubin por defecto (suavizado que no encoge el volumen).
_DEFAULT_TAUBIN_ITERS = 12
# Coeficientes Taubin clásicos (λ>0, μ<0 con |μ|>λ) — pasa-banda que cancela el
# encogimiento del suavizado laplaciano puro.
_TAUBIN_LAMBDA = 0.50
_TAUBIN_MU = -0.53


@dataclass
class _FieldGrid:
    """Volumen regular listo para marching cubes."""

    magnitude: np.ndarray  # |contraste| ≥ 0, inactivos = 0
    signed: np.ndarray     # contraste con signo, inactivos = 0 (para color)
    grad: tuple[np.ndarray, np.ndarray, np.ndarray]  # ∇|contraste| por eje índice
    spacing: tuple[float, float, float]  # (dx, dy, dz) tamaño de celda por eje [m]
    origin_m: tuple[float, float, float]  # coord física del índice (0,0,0) [m]
    center_m: tuple[float, float, float]  # centro para centrar en el visor [m]
    background: float
    scale: float
    peak: float
    nx: int
    ny: int
    nz: int


# ─── Estadística robusta (idéntica al visor) ─────────────────────────────────

def _robust_background_scale(values: np.ndarray) -> tuple[float, float]:
    """(background, scale) robustos = mediana y mayor desviación P5/P95.

    Réplica exacta de la lógica de `updateInstancedBuffers`:
        background = P50
        scale = max(P95 - background, background - P5, 0.05)
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    if finite.size == 1:
        return float(finite[0]), 1.0
    bg = float(np.quantile(finite, 0.5))
    p95 = float(np.quantile(finite, 0.95))
    p5 = float(np.quantile(finite, 0.05))
    scale = max(p95 - bg, bg - p5, _SCALE_FLOOR)
    return bg, scale


def _extract_field_values(df: pl.DataFrame, field: str) -> np.ndarray:
    """Serie numérica del campo pedido, con log10 si corresponde. NaN donde falta."""
    spec = _SUPPORTED_FIELDS[field]
    col = next((c for c in spec["columns"] if c in df.columns), None)
    if col is None:
        return np.full(len(df), np.nan, dtype=np.float64)
    vals = df[col].to_numpy().astype(np.float64)
    if spec["log"]:
        # chiLog = log10(max(chi, 0) + eps) — idéntico al visor.
        vals = np.log10(np.clip(vals, 0.0, None) + _LOG_EPS)
    return vals


# ─── Construcción del volumen ────────────────────────────────────────────────

def _axis_coords(df: pl.DataFrame, names: tuple[str, ...]) -> np.ndarray | None:
    """Coordenadas por celda desde la 1ª columna presente (x_m→x→ix)."""
    for name in names:
        if name in df.columns:
            arr = df[name].to_numpy().astype(np.float64)
            if np.isfinite(arr).any():
                return arr
    return None


def _axis_grid(coord: np.ndarray) -> tuple[np.ndarray, int, float, float, float] | None:
    """(idx compacto, n, spacing, origin, center) de una grilla regular en un eje.

    CLAVE: se rank/step-encodea por COORDENADA, no por el índice crudo. El índice
    de cada celda es round((coord − origin)/paso), con paso = mínima diferencia
    entre coordenadas únicas. Así una grilla en metros (x = 24..1992, paso 48) da
    n=42 en vez de 1993 — jamás se intenta reservar un volumen gigante a partir de
    coordenadas tomadas como índices (el bug que cazó el dato real: 29 GiB).

    Devuelve None si el eje es degenerado (<2 planos).
    """
    r = np.round(coord.astype(np.float64), 3)
    finite = r[np.isfinite(r)]
    if finite.size == 0:
        return None
    uniq = np.unique(finite)
    if uniq.size < 2:  # marching cubes necesita ≥2 planos
        return None
    diffs = np.diff(uniq)
    pos = diffs[diffs > 0]
    spacing = float(pos.min()) if pos.size else 1.0
    origin = float(uniq[0])
    last = float(uniq[-1])
    idx = np.clip(np.rint((r - origin) / spacing), 0, None).astype(np.int64)
    n = int(idx.max()) + 1
    center = (origin + last) / 2.0
    return idx, n, spacing, origin, center


def _build_field_grid(df: pl.DataFrame, field: str) -> _FieldGrid | None:
    """Arma el volumen regular nx×ny×nz de |contraste| y contraste con signo.

    Devuelve None si el modelo no tiene grilla utilizable (columnas de coordenadas
    ausentes, grilla degenerada <2 celdas en algún eje, sin celdas activas, o una
    grilla no-regular tan grande que el volumen denso sería inviable).
    """
    # Prioridad de coordenadas: x_m/y_m/z_m (v4.0) → x/y/z (v3.0) → ix/iy/iz (índice).
    xm = _axis_coords(df, ("x_m", "x", "ix"))
    ym = _axis_coords(df, ("y_m", "y", "iy"))
    zm = _axis_coords(df, ("z_m", "z", "iz"))
    if xm is None or ym is None or zm is None or len(xm) == 0:
        return None

    gx = _axis_grid(xm)
    gy = _axis_grid(ym)
    gz = _axis_grid(zm)
    if gx is None or gy is None or gz is None:
        return None
    ix, nx, dx, x0, xc = gx
    iy, ny, dy, y0, yc = gy
    iz, nz, dz, z0, zc = gz

    # Tope anti-OOM: un volumen denso por encima de esto es inviable (coordenadas
    # continuas / grilla no regular). Se aborta con gracia en vez de reventar la RAM.
    if nx * ny * nz > _MAX_GRID_CELLS:
        return None

    # Máscara de actividad: is_active True (o ausente) y densidad no-null.
    active = np.ones(len(df), dtype=bool)
    if "is_active" in df.columns:
        active &= df["is_active"].fill_null(True).to_numpy().astype(bool)
    if "density" in df.columns:
        active &= df["density"].is_not_null().to_numpy()

    raw = _extract_field_values(df, field)
    active &= np.isfinite(raw)
    if not active.any():
        return None

    bg, scale = _robust_background_scale(raw[active])
    signed = (raw - bg) / scale  # contraste con signo por celda

    signed_vol = np.zeros((nx, ny, nz), dtype=np.float64)
    signed_vol[ix[active], iy[active], iz[active]] = signed[active]
    magnitude_vol = np.abs(signed_vol)

    peak = float(magnitude_vol.max())
    if not math.isfinite(peak) or peak <= 0.0:
        return None

    # Gradiente del campo (espacio índice): -∇ apunta hacia afuera del cuerpo
    # (campo decreciente). Orienta las normales de forma robusta incluso en mallas
    # ABIERTAS (cuerpo pegado al borde del dominio), donde el signo del volumen
    # firmado no es fiable.
    grad = np.gradient(magnitude_vol)

    return _FieldGrid(
        magnitude=magnitude_vol,
        signed=signed_vol,
        grad=(grad[0], grad[1], grad[2]),
        spacing=(dx, dy, dz),
        origin_m=(x0, y0, z0),
        center_m=(xc, yc, zc),
        background=bg,
        scale=scale,
        peak=peak,
        nx=nx,
        ny=ny,
        nz=nz,
    )


# ─── Marching cubes + transformación al espacio visual ───────────────────────

def _swap_winding(faces: np.ndarray) -> np.ndarray:
    """Invierte la orientación de cada triángulo (intercambia dos índices)."""
    swapped = faces.copy()
    swapped[:, [1, 2]] = faces[:, [2, 1]]
    return swapped


def _signed_volume_raw(verts: np.ndarray, faces: np.ndarray) -> float:
    """Volumen firmado (teorema de la divergencia) — el SIGNO indica la orientación."""
    v0 = verts[faces[:, 0]].astype(np.float64)
    v1 = verts[faces[:, 1]].astype(np.float64)
    v2 = verts[faces[:, 2]].astype(np.float64)
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)


def _recompute_vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Normales por vértice = suma ponderada por área de las normales de cara."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    # cross sin normalizar → magnitud ∝ 2·área (ponderación por área natural).
    face_n = np.cross(v1 - v0, v2 - v0)
    vnormals = np.zeros_like(verts)
    for k in range(3):
        np.add.at(vnormals, faces[:, k], face_n)
    lengths = np.linalg.norm(vnormals, axis=1, keepdims=True)
    lengths = np.where(lengths > 1e-12, lengths, 1.0)
    return (vnormals / lengths).astype(np.float32)


def _taubin_smooth(verts: np.ndarray, faces: np.ndarray, iterations: int) -> np.ndarray:
    """Suavizado Taubin λ|μ — pasa-banda que NO encoge el volumen.

    Usa la matriz de adyacencia normalizada por filas (umbrella laplaciano).
    """
    if iterations <= 0 or len(verts) == 0:
        return verts
    from scipy.sparse import coo_matrix

    n = len(verts)
    # Aristas no dirigidas desde las caras.
    e = np.vstack([
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]],
    ])
    e = np.vstack([e, e[:, ::-1]])  # simetrizar
    rows = e[:, 0]
    cols = e[:, 1]
    data = np.ones(len(rows), dtype=np.float64)
    adj = coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
    adj.data[:] = 1.0  # sin duplicados de peso
    deg = np.asarray(adj.sum(axis=1)).ravel()
    deg = np.where(deg > 0, deg, 1.0)
    inv_deg = (1.0 / deg)

    p = verts.astype(np.float64).copy()

    def _laplacian(pts: np.ndarray) -> np.ndarray:
        # L(p) = mean(vecinos) - p
        return adj.dot(pts) * inv_deg[:, None] - pts

    for _ in range(iterations):
        p = p + _TAUBIN_LAMBDA * _laplacian(p)
        p = p + _TAUBIN_MU * _laplacian(p)
    return p.astype(np.float32)




def _b64_f32(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<f4").tobytes()).decode("ascii")


def _b64_u32(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<u4").tobytes()).decode("ascii")


def _lod_step(n_cells: int) -> int:
    """LOD medido (F4.7): step de marching cubes según tamaño del volumen.

    MEDIDO 2026-07-09: los vértices son pocos incluso a 8M celdas (~29k) — el
    render nunca es el cuello; el costo es la EXTRACCIÓN CPU (~650 ms/nivel a 8M,
    ~125 ms a 1.7M) + gradientes float64. step=2 divide el costo ~4-10× con
    pérdida visual nula a esas resoluciones (la malla sigue más fina que el dato).
    El octree (decimación GPU) NO se justifica: quedó congelado con esta medición.
    """
    return 1 if n_cells <= _LOD_STEP_THRESHOLD else 2


def _build_one_level(
    grid: _FieldGrid,
    fraction: float,
    taubin_iters: int,
) -> dict | None:
    """Extrae, transforma, suaviza y codifica la isosuperficie de un nivel.

    Devuelve None si el nivel no produce superficie (fuera del rango del volumen).
    """
    from skimage.measure import marching_cubes

    level = fraction * grid.peak
    vmin = float(grid.magnitude.min())
    vmax = float(grid.magnitude.max())
    # marching_cubes exige vmin < level < vmax; si no, no hay superficie.
    if not (vmin < level < vmax):
        return None

    step = _lod_step(grid.nx * grid.ny * grid.nz)
    try:
        verts_phys, faces, _normals, _values = marching_cubes(
            grid.magnitude,
            level=level,
            spacing=grid.spacing,
            allow_degenerate=False,
            step_size=step,
        )
    except (ValueError, RuntimeError):
        return None

    if len(verts_phys) == 0 or len(faces) == 0:
        return None

    dx, dy, dz = grid.spacing
    from scipy.ndimage import map_coordinates
    # Índices continuos en el volumen (para muestrear campos escalares/gradiente).
    idx_coords = np.vstack([
        verts_phys[:, 0] / dx,
        verts_phys[:, 1] / dy,
        verts_phys[:, 2] / dz,
    ])
    signed_at_vert = map_coordinates(
        grid.signed, idx_coords, order=1, mode="nearest"
    ).astype(np.float32)

    # Dirección "hacia afuera" por vértice = −∇|contraste| (campo decreciente),
    # muestreado y llevado al espacio visual (el flip-Y niega la componente Y).
    gi = map_coordinates(grid.grad[0], idx_coords, order=1, mode="nearest")
    gj = map_coordinates(grid.grad[1], idx_coords, order=1, mode="nearest")
    gk = map_coordinates(grid.grad[2], idx_coords, order=1, mode="nearest")
    outward = np.column_stack([-gi, gj, -gk])  # x:−g, y:+g (flip), z:−g

    # Físico → visual: coord física = origin + verts_phys; luego centrar + flip-Y.
    ox, oy, oz = grid.origin_m
    cx0, cy0, cz0 = grid.center_m
    x_m = ox + verts_phys[:, 0]
    y_m = oy + verts_phys[:, 1]
    z_m = oz + verts_phys[:, 2]
    visual = np.empty_like(verts_phys, dtype=np.float64)
    visual[:, 0] = x_m - cx0
    visual[:, 1] = cy0 - y_m   # flip-Y: idéntico al visor (cy = y_center - y_m)
    visual[:, 2] = z_m - cz0

    faces = faces.astype(np.int64)

    # Suavizado Taubin (no encoge volumen). No cambia la topología.
    visual = _taubin_smooth(visual, faces, taubin_iters)

    normals = _recompute_vertex_normals(visual, faces)

    # Orientar hacia afuera por VOTO MAYORITARIO contra −∇|contraste|. Robusto en
    # mallas ABIERTAS (cuerpo pegado al borde del dominio), donde el signo del
    # volumen firmado no es fiable. Si la mayoría de las normales apunta hacia
    # adentro, se invierte el winding y se recomputan.
    vote = float(np.einsum("ij,ij->i", normals.astype(np.float64), outward).sum())
    if vote < 0:
        faces = _swap_winding(faces)
        normals = _recompute_vertex_normals(visual, faces)

    volume_m3 = abs(_signed_volume_raw(visual, faces))

    return {
        "fraction": round(fraction, 4),
        "level_value": round(level, 6),
        "n_vertices": int(len(visual)),
        "n_faces": int(len(faces)),
        "enclosed_volume_m3": round(volume_m3, 3),
        "signed_contrast_range": [
            round(float(signed_at_vert.min()), 4),
            round(float(signed_at_vert.max()), 4),
        ],
        "positions_b64": _b64_f32(visual.reshape(-1)),
        "normals_b64": _b64_f32(normals.reshape(-1)),
        "signed_contrast_b64": _b64_f32(signed_at_vert),
        "indices_b64": _b64_u32(faces.reshape(-1)),
    }


# ─── API pública ─────────────────────────────────────────────────────────────

def build_isosurface_response(
    project_id: str | None,
    run_id: str | None,
    field: str = "density",
    levels: tuple[float, ...] | None = None,
    taubin_iterations: int = _DEFAULT_TAUBIN_ITERS,
) -> dict:
    """Calcula las isosuperficies del block model.

    Args:
        project_id, run_id: identifican la corrida (mismo contrato que /block-model).
        field: "density" (gravedad, default) o "susceptibility" (magnético).
        levels: fracciones del pico de |contraste| a contornear (default 0.5/0.7/0.9).
        taubin_iterations: pasadas de suavizado Taubin.

    Returns:
        dict serializable a JSON:
            field, colormap, background, scale, peak_contrast, weak_anomaly,
            cell_size {x,y,z}, center_m {x,y,z}, levels[...]  (cada nivel con
            arrays base64 en el espacio visual de Three.js), warnings[], error?.
        Las mallas ya vienen centradas + flip-Y para superponerse a los vóxeles
        del endpoint /block-model-arrow.  El frontend NO calcula física.
    """
    field_clean = str(field or "density").lower().strip()
    warnings: list[str] = []
    if field_clean not in _SUPPORTED_FIELDS:
        warnings.append(
            f"campo '{field_clean}' no soportado; usando 'density'."
        )
        field_clean = "density"

    lvls = tuple(sorted({float(x) for x in (levels or _DEFAULT_LEVELS) if 0.0 < float(x) < 1.0}))
    if not lvls:
        lvls = _DEFAULT_LEVELS

    try:
        ref = resolve_block_model_reference(project_id=project_id, run_id=run_id)
    except ValueError as exc:
        return _empty_response(field_clean, str(exc), warnings)

    parquet_path = ref.path
    if not parquet_path.exists():
        return _empty_response(
            field_clean, f"Archivo {parquet_path} no encontrado.", warnings
        )

    df = pl.read_parquet(str(parquet_path))
    if len(df) == 0:
        return _empty_response(field_clean, "Block model vacío.", warnings)

    df = ensure_visual_columns(df)

    grid = _build_field_grid(df, field_clean)
    if grid is None:
        return _empty_response(
            field_clean,
            "El block model no tiene una grilla regular utilizable o carece de "
            "celdas activas con el campo pedido.",
            warnings,
        )

    weak = grid.peak < _WEAK_PEAK
    if weak:
        warnings.append(
            "anomalía débil: el pico de contraste es bajo; la isosuperficie puede "
            "ser pequeña o ruidosa (weak_anomaly)."
        )

    level_meshes: list[dict] = []
    skipped: list[float] = []
    for frac in lvls:
        mesh = _build_one_level(grid, frac, taubin_iterations)
        if mesh is None:
            skipped.append(frac)
        else:
            level_meshes.append(mesh)

    if skipped:
        warnings.append(
            "niveles sin superficie (fuera del rango del volumen): "
            + ", ".join(f"{s:.2f}" for s in skipped)
        )

    error = None
    if not level_meshes:
        error = (
            "Ningún nivel produjo superficie: el campo de contraste es demasiado "
            "plano para contornear (modelo homogéneo o degenerado)."
        )

    dx, dy, dz = grid.spacing
    return {
        "field": field_clean,
        "colormap": "viridis_divergent",
        "background": round(grid.background, 6),
        "scale": round(grid.scale, 6),
        "peak_contrast": round(grid.peak, 6),
        "weak_anomaly": bool(weak),
        "cell_size": {"x": round(dx, 4), "y": round(dy, 4), "z": round(dz, 4)},
        "center_m": {
            "x": round(grid.center_m[0], 4),
            "y": round(grid.center_m[1], 4),
            "z": round(grid.center_m[2], 4),
        },
        "grid_dims": {"nx": grid.nx, "ny": grid.ny, "nz": grid.nz},
        "lod_step": _lod_step(grid.nx * grid.ny * grid.nz),
        "levels": level_meshes,
        "n_levels": len(level_meshes),
        "warnings": warnings,
        "error": error,
        "source_path": str(parquet_path),
    }


def _empty_response(field: str, error: str, warnings: list[str]) -> dict:
    return {
        "field": field,
        "colormap": "viridis_divergent",
        "background": None,
        "scale": None,
        "peak_contrast": None,
        "weak_anomaly": False,
        "cell_size": None,
        "center_m": None,
        "grid_dims": None,
        "levels": [],
        "n_levels": 0,
        "warnings": warnings,
        "error": error,
        "source_path": None,
    }
