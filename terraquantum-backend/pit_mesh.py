from typing import Optional, List, Tuple
import numpy as np
import trimesh
import math
from shapely.geometry import box, Polygon, MultiPolygon, JOIN_STYLE
from shapely.ops import unary_union
from trimesh.visual.material import PBRMaterial


# ---------------------------------------------------------------------------
# Utilidades de polígonos
# ---------------------------------------------------------------------------

def clean_poly(poly, min_area: float):
    if poly is None or poly.is_empty:
        return None
    if isinstance(poly, MultiPolygon) or poly.geom_type == 'GeometryCollection':
        parts = [p for p in poly.geoms if isinstance(p, Polygon) and p.area > min_area]
        return MultiPolygon(parts) if parts else None
    elif isinstance(poly, Polygon) and poly.area > min_area:
        return poly
    return None


# ---------------------------------------------------------------------------
# Construcción de superficies
# ---------------------------------------------------------------------------

def build_column_topography(rock_mask: np.ndarray) -> np.ndarray:
    nx, ny, nz = rock_mask.shape
    has_rock = rock_mask.any(axis=1)
    col_indices = np.argmax(rock_mask, axis=1)
    return np.where(has_rock, col_indices, 0).astype(np.int32)


def build_world_topography(topography: np.ndarray, block_size: float) -> np.ndarray:
    return -(topography.astype(np.float64) - topography.min()) * block_size


def build_excavation_surface(mined_mask: np.ndarray, topography: Optional[np.ndarray] = None) -> np.ndarray:
    nx, ny, nz = mined_mask.shape
    has_mined = mined_mask.any(axis=1)
    flipped = np.flip(mined_mask, axis=1)
    last_idx = np.argmax(flipped, axis=1)
    deepest = ny - 1 - last_idx
    deepest = np.where(has_mined, deepest + 1, 0)
    if topography is not None:
        deepest = np.where(has_mined, np.maximum(0, deepest - topography), 0)
    return deepest.astype(np.int32)


def clean_surface(surface: np.ndarray) -> np.ndarray:
    from scipy.ndimage import median_filter
    return median_filter(surface, size=3).astype(np.int32)


def quantize_surface_to_benches(surface: np.ndarray, block_size: float, bench_height: float) -> np.ndarray:
    if bench_height <= 0:
        return surface.copy()
    bench_blocks = max(2, int(np.ceil(bench_height / block_size)))
    quantized = np.zeros_like(surface)
    excavated = surface > 0
    quantized[excavated] = (
        np.ceil(surface[excavated] / bench_blocks).astype(np.int32) * bench_blocks
    )
    return quantized


# ---------------------------------------------------------------------------
# Color LiDAR por profundidad (gradiente azul→cian→verde→amarillo→rojo→blanco)
# ---------------------------------------------------------------------------

def _depth_to_lidar_color(y: float, y_min: float, y_max: float) -> Tuple[int, int, int, int]:
    """
    Convierte una coordenada Y (negativa = profundo) a color estilo LiDAR.
    y_min = más profundo (valor más negativo), y_max = superficie (0)
    """
    if y_max == y_min:
        return (0, 128, 255, 255)

    # t=0 → superficie (blanco/rojo), t=1 → fondo (azul)
    t = np.clip((y_max - y) / (y_max - y_min), 0.0, 1.0)

    # Gradiente de 5 colores: blanco → rojo → amarillo → verde → cian → azul
    colors = [
        (255, 255, 255),  # 0.0 superficie
        (255,  60,  60),  # 0.2 rojo
        (255, 200,   0),  # 0.4 amarillo
        ( 60, 220,  60),  # 0.6 verde
        (  0, 200, 220),  # 0.8 cian
        (  0,  40, 255),  # 1.0 fondo
    ]
    n = len(colors) - 1
    idx = t * n
    lo = int(idx)
    hi = min(lo + 1, n)
    alpha = idx - lo

    r = int(colors[lo][0] * (1 - alpha) + colors[hi][0] * alpha)
    g = int(colors[lo][1] * (1 - alpha) + colors[hi][1] * alpha)
    b = int(colors[lo][2] * (1 - alpha) + colors[hi][2] * alpha)
    return (r, g, b, 255)


# ---------------------------------------------------------------------------
# Geometría interna
# ---------------------------------------------------------------------------

def _get_polys_at_level(surface: np.ndarray, depth: int, block_size: float,
                         x_off: float, z_off: float) -> List[Polygon]:
    cells = []
    x_indices, z_indices = np.where(surface >= depth)
    for x, z in zip(x_indices, z_indices):
        x0 = x * block_size - x_off
        z0 = z * block_size - z_off
        cells.append(box(x0, z0, x0 + block_size, z0 + block_size))
    if not cells:
        return []
    merged = unary_union(cells).buffer(0)
    if not merged.is_valid:
        return []
    return [merged] if isinstance(merged, Polygon) else list(merged.geoms)


def _triangulate_polygon(poly: Polygon, y: float, vertices: list, faces: list,
                          y_min: float = 0.0, y_max: float = 0.0,
                          use_lidar_color: bool = False, vertex_colors: list = None):
    try:
        v, f = trimesh.creation.triangulate_polygon(poly, engine='earcut')
        start = len(vertices)
        v3 = np.column_stack((v[:, 0], np.full(len(v), y), v[:, 1]))
        vertices.extend(v3.tolist())
        faces.extend((f + start).tolist())
        if use_lidar_color and vertex_colors is not None:
            color = _depth_to_lidar_color(y, y_min, y_max)
            vertex_colors.extend([color] * len(v3))
    except Exception:
        pass


def _resample_ring(coords: np.ndarray, n: int) -> np.ndarray:
    coords = np.array(coords)
    diffs = coords[1:] - coords[:-1]
    dists = np.sqrt((diffs ** 2).sum(axis=1))
    cum = np.insert(np.cumsum(dists), 0, 0.0)
    total = cum[-1]
    if total == 0:
        return coords
    targets = np.linspace(0, total, n)
    resampled = []
    for t in targets:
        idx = int(np.clip(np.searchsorted(cum, t) - 1, 0, len(coords) - 2))
        t0, t1 = cum[idx], cum[idx + 1]
        alpha = (t - t0) / (t1 - t0) if (t1 - t0) > 0 else 0.0
        resampled.append(coords[idx] + alpha * (coords[idx + 1] - coords[idx]))
    return np.array(resampled)


def _stitch_wall(ring_top: np.ndarray, ring_bot: np.ndarray,
                 y_top: float, y_bot: float,
                 vertices: list, faces: list,
                 y_min: float = 0.0, y_max: float = 0.0,
                 use_lidar_color: bool = False, vertex_colors: list = None):
    n = max(len(ring_top), len(ring_bot), 24)
    rt = _resample_ring(np.array(ring_top), n)
    rb = _resample_ring(np.array(ring_bot), n)
    rt = np.vstack([rt, rt[0]])
    rb = np.vstack([rb, rb[0]])
    n += 1

    start = len(vertices)
    for p in rt:
        vertices.append((float(p[0]), y_top, float(p[1])))
    for p in rb:
        vertices.append((float(p[0]), y_bot, float(p[1])))

    if use_lidar_color and vertex_colors is not None:
        color_top = _depth_to_lidar_color(y_top, y_min, y_max)
        color_bot = _depth_to_lidar_color(y_bot, y_min, y_max)
        vertex_colors.extend([color_top] * n)
        vertex_colors.extend([color_bot] * n)

    for i in range(n - 1):
        v0, v1 = start + i, start + i + 1
        v2, v3 = start + n + i + 1, start + n + i
        faces.append([v0, v3, v1])
        faces.append([v1, v3, v2])


# ---------------------------------------------------------------------------
# Generador de UVs triplanares (para textura de roca sin depender de UE5)
# ---------------------------------------------------------------------------

def _compute_triplanar_uvs(vertices: np.ndarray, uv_scale: float = 0.01) -> np.ndarray:
    """
    Proyección triplanar: cada vértice toma UV según la cara dominante (X, Y o Z).
    uv_scale controla el tiling (más pequeño = más repeticiones).
    """
    v = vertices
    bounds_range = v.max(axis=0) - v.min(axis=0)
    bounds_range = np.where(bounds_range == 0, 1.0, bounds_range)

    # Normales por vértice aproximadas via posición
    v_norm = (v - v.min(axis=0)) / bounds_range

    # Para mallas de rajo, la mayoría de caras son horizontales o verticales
    # Usamos proyección XZ para caras horizontales (bermas) y XY/ZY para taludes
    uvs = np.column_stack([v[:, 0] * uv_scale, v[:, 2] * uv_scale])
    return uvs.astype(np.float32)


def _safe_cleanup_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    cleanup_methods = (
        "remove_degenerate_faces",
        "remove_duplicate_faces",
        "remove_unreferenced_vertices",
    )

    for method_name in cleanup_methods:
        method = getattr(mesh, method_name, None)
        if callable(method):
            method()

    return mesh


# ---------------------------------------------------------------------------
# Constructor principal de la malla
# ---------------------------------------------------------------------------

def build_benched_mesh(
    surface: np.ndarray,
    block_size: float,
    bench_height: float,
    pit_angle: float,
    berm_width: float,
    color: list = [200, 200, 200, 255],
    use_lidar_colors: bool = True,   # 🔥 Gradiente LiDAR activado por defecto
    uv_scale: float = 0.005,         # 🔥 Tiling de textura (ajustable)
) -> trimesh.Trimesh:

    nx, nz = surface.shape
    vertices: list = []
    faces: list = []
    vertex_colors: list = []

    angle_rad = math.radians(max(1.0, min(89.0, pit_angle)))
    slope_run = bench_height / math.tan(angle_rad)
    min_area_tol = block_size ** 2

    x_off = (nx * block_size) / 2.0
    z_off = (nz * block_size) / 2.0

    bench_blocks = max(2, int(np.ceil(bench_height / block_size)))
    max_depth = int(surface.max())
    levels = np.arange(bench_blocks, max_depth + bench_blocks, bench_blocks, dtype=np.int32)

    if len(levels) == 0:
        return trimesh.Trimesh()

    # Rango de profundidad para el gradiente LiDAR
    y_max = 0.0
    y_min = -float(max_depth * block_size)

    prev_toe_polys: Optional[List[Polygon]] = None
    prev_y = 0.0

    for depth in levels:
        y_top = prev_y
        y_bot = -float(depth * block_size)

        excavated_polys = _get_polys_at_level(surface, depth, block_size, x_off, z_off)
        if not excavated_polys:
            continue
        excavated_union = unary_union(excavated_polys)

        if prev_toe_polys is None:
            current_toe_polys = excavated_polys
            # Primera berma (superficie) — NO añadimos tapa superior exterior
            # para que el hoyo sea visible desde arriba
        else:
            current_toe_polys = []
            current_crests_for_berm = []

            for prev_toe in prev_toe_polys:
                crest_candidate = prev_toe.buffer(-berm_width, join_style=JOIN_STYLE.mitre)
                crest_candidate = clean_poly(crest_candidate, min_area_tol)
                if not crest_candidate:
                    continue

                crest = crest_candidate.intersection(excavated_union)
                crest = clean_poly(crest.buffer(0), min_area_tol)
                if not crest:
                    continue

                toe_candidate = crest.buffer(-slope_run, join_style=JOIN_STYLE.mitre)
                toe_candidate = clean_poly(toe_candidate, min_area_tol)
                if not toe_candidate:
                    continue

                toe = toe_candidate.intersection(excavated_union)
                toe = clean_poly(toe.buffer(0), min_area_tol)
                if not toe:
                    continue

                toe_parts = [toe] if isinstance(toe, Polygon) else list(toe.geoms)

                for toe_poly in toe_parts:
                    if toe_poly.area < min_area_tol:
                        continue

                    if len(toe_parts) == 1:
                        actual_crest_geom = crest
                    else:
                        influence_zone = toe_poly.buffer(berm_width + slope_run, join_style=JOIN_STYLE.mitre)
                        actual_crest_geom = crest.intersection(influence_zone)

                    actual_crest_geom = clean_poly(actual_crest_geom.buffer(0), min_area_tol)
                    if not actual_crest_geom:
                        continue

                    crest_parts = (
                        [actual_crest_geom]
                        if isinstance(actual_crest_geom, Polygon)
                        else list(actual_crest_geom.geoms)
                    )

                    for crest_poly in crest_parts:
                        current_crests_for_berm.append(crest_poly)
                        _stitch_wall(
                            np.array(crest_poly.exterior.coords),
                            np.array(toe_poly.exterior.coords),
                            y_top, y_bot,
                            vertices, faces,
                            y_min=y_min, y_max=y_max,
                            use_lidar_color=use_lidar_colors,
                            vertex_colors=vertex_colors,
                        )

                    current_toe_polys.append(toe_poly)

            # Berma horizontal (plataforma entre taludes)
            if current_crests_for_berm:
                prev_union = clean_poly(unary_union(prev_toe_polys).buffer(0), min_area_tol)
                curr_crests_union = clean_poly(unary_union(current_crests_for_berm).buffer(0), min_area_tol)

                if prev_union and curr_crests_union:
                    berm_poly = prev_union.difference(curr_crests_union)
                    berm_poly = clean_poly(berm_poly.buffer(0), block_size ** 0.5)

                    if berm_poly:
                        berm_parts = (
                            [berm_poly] if isinstance(berm_poly, Polygon)
                            else list(berm_poly.geoms)
                        )
                        for bp in berm_parts:
                            _triangulate_polygon(
                                bp, y_top, vertices, faces,
                                y_min=y_min, y_max=y_max,
                                use_lidar_color=use_lidar_colors,
                                vertex_colors=vertex_colors,
                            )

        prev_toe_polys = current_toe_polys if current_toe_polys else prev_toe_polys
        prev_y = y_bot

    # Fondo del rajo
    if prev_toe_polys:
        for poly in prev_toe_polys:
            _triangulate_polygon(
                poly, prev_y, vertices, faces,
                y_min=y_min, y_max=y_max,
                use_lidar_color=use_lidar_colors,
                vertex_colors=vertex_colors,
            )

    if not vertices or not faces:
        return trimesh.Trimesh()

    verts_np = np.array(vertices, dtype=np.float64)
    faces_np = np.array(faces, dtype=np.int64)

    mesh = trimesh.Trimesh(vertices=verts_np, faces=faces_np, process=True)

    try:
        _safe_cleanup_mesh(mesh)

        if not np.isfinite(mesh.vertices).all():
            mask = np.isfinite(mesh.vertices).all(axis=1)
            mesh.update_vertices(mask)

        # ---------------------------------------------------------------
        # UVs triplanares — textura de roca sin depender de UE5
        # ---------------------------------------------------------------
        uvs = _compute_triplanar_uvs(mesh.vertices, uv_scale=uv_scale)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uvs)

        # ---------------------------------------------------------------
        # Colores por vértice (LiDAR o color de fase)
        # ---------------------------------------------------------------
        if use_lidar_colors and len(vertex_colors) == len(mesh.vertices):
            vc = np.array(vertex_colors, dtype=np.uint8)
            mesh.visual.vertex_colors = vc
        else:
            mesh.visual.vertex_colors = color

        # ---------------------------------------------------------------
        # Material PBR doble cara
        # ---------------------------------------------------------------
        base_color = [1.0, 1.0, 1.0, 1.0] if use_lidar_colors else [c / 255.0 for c in color]
        mat = PBRMaterial(
            name="Roca_Minera",
            baseColorFactor=base_color,
            roughnessFactor=0.85,
            metallicFactor=0.0,
            doubleSided=True,
        )
        mesh.visual.material = mat

        # ---------------------------------------------------------------
        # Orientacion Three.js: Y-up, superficie arriba (Y=0) y bancos
        # descendiendo en Y negativa. Centramos solo en planta.
        # ---------------------------------------------------------------
        bounds = mesh.bounds
        center_x = (bounds[0][0] + bounds[1][0]) / 2.0
        center_z = (bounds[0][2] + bounds[1][2]) / 2.0
        mesh.apply_translation([-center_x, -bounds[1][1], -center_z])

    except Exception as e:
        print(f"[PitMesh] Advertencia: {e}")

    return mesh
