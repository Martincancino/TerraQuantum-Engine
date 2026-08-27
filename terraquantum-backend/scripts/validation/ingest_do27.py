"""
DO-27 (Tli Kwi Cho) — Adaptador de ingestión → formato TerraQuantum
====================================================================

Carga el benchmark PUBLICADO de la kimberlita DO-27 (Astic & Oldenburg 2020,
SimPEG-research) y lo traduce al frame de coordenadas / convención que consume el
motor de TerraQuantum, SIN inventar física y SIN tunear nada.

Lo que hace:
  • load_gravity()  — lee DO27_Gravity_mGal.csv (anomalía de Bouguer, mGal).
  • load_magnetic() — lee DO27_Magnetic_TMI_nT.csv, EXTRAE el IGRF (inclinación,
                      declinación, intensidad) de las 2 filas "basura" del encabezado
                      y descarta las filas con NaN (validador Fase 14).
  • load_ground_truth() — lee la malla UBC + el modelo VERDADERO (.den/.sus) del
                      forward-model de los autores y extrae la GEOMETRÍA del pipe
                      (centroide, techo, extensión) — el ground truth peer-reviewed.
  • LocalFrame    — transforma UTM (Easting/Northing/elevación) ↔ frame local del
                      motor (x=Este, z=Norte, y=profundidad+abajo).

CAVEAT HONESTO (no se oculta): los datos geofísicos son "synthetic based on" DO-27
(forward-modelados desde la geología de sondajes), NO dato crudo de campo. Aun así,
el ground truth y las inversiones de referencia son EXTERNOS y peer-reviewed: es el
escalón correcto antes de datos de campo crudos.

Convención del motor TerraQuantum (`docs/11_CONVENCION_DE_EJES.md`):
    x = Este (horizontal),  z = Norte (horizontal),  y = profundidad (+ hacia abajo)
Mapeo UTM → local:
    x_local (Este)  = Easting_UTM  - origin_east
    z_local (Norte) = Northing_UTM - origin_north
    y_local (prof)  = datum_elev   - elevación      (datum = elevación de referencia)

FASE 19: hasta 2026-08-26 este adaptador armaba el frame al revés (col0=Norte),
igual que el motor. Las dos mitades eran consistentes entre sí, y por eso DO-27
NO podía ver ACAD-1: el harness nunca pasa por el importador. Voltear las dos a
la vez es un re-etiquetado exacto — la Fase 18 lo midió en el forward (3·10⁻¹⁶ nT)
y la Fase 19 lo confirmó corriendo el benchmark entero antes y después.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

# Raíz del dataset DO-27 (fuera del backend; NO se commitean datos, sólo código).
_DEFAULT_DO27_ROOT = (
    Path(__file__).resolve().parents[3] / "DO-27_Kimberlite"
)


# ══════════════════════════════════════════════════════════════════════════════
#  Estructuras
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class GravitySurvey:
    """Gravimetría DO-27: anomalía de Bouguer ya reducida (mGal)."""
    easting: np.ndarray      # UTM X (m)
    northing: np.ndarray     # UTM Y (m)
    elevation: np.ndarray    # Z (m, elevación del sensor)
    bouguer_mgal: np.ndarray # anomalía de Bouguer (mGal)
    error_est: np.ndarray    # incertidumbre reportada (mGal); 0 en DO-27

    @property
    def n(self) -> int:
        return int(self.easting.shape[0])


@dataclass
class MagneticSurvey:
    """Magnetometría DO-27: anomalía TMI (nT) + IGRF extraído del encabezado."""
    easting: np.ndarray
    northing: np.ndarray
    elevation: np.ndarray
    tmi_nt: np.ndarray
    error_est: np.ndarray
    inclination_deg: float   # IGRF (rumbo del campo): I
    declination_deg: float   # D
    field_intensity_nt: float  # B0
    n_dropped_nan: int       # filas descartadas por NaN (incluye las de metadatos)

    @property
    def n(self) -> int:
        return int(self.easting.shape[0])


@dataclass
class PipeGroundTruth:
    """Geometría VERDADERA del pipe (del modelo forward de los autores)."""
    centroid_easting: float
    centroid_northing: float
    centroid_elevation: float
    top_elevation: float        # techo (máx z de celdas del cuerpo)
    bottom_elevation: float
    surface_elevation: float    # superficie sobre el footprint del pipe
    depth_to_top_m: float       # surface - top
    horizontal_extent_m: tuple  # (ancho E-W p5..p95, ancho N-S p5..p95)
    n_body_cells: int
    label: str


@dataclass
class LocalFrame:
    """Frame local del motor (x=Este, z=Norte, y=prof). Origen + datum compartidos.

    Los métodos se llaman por lo que DEVUELVEN (`east_local`, `north_local`), no
    por el slot en que acaban: el slot lo decide `sensors()`, en un solo sitio.
    """
    origin_east: float    # se resta al Easting → x_local
    origin_north: float   # se resta al Northing → z_local
    datum_elev: float     # elevación de referencia → y_local = datum - elev

    # ── UTM → local ──────────────────────────────────────────────────────────
    def north_local(self, northing) -> np.ndarray:
        return np.asarray(northing, dtype=np.float64) - self.origin_north

    def east_local(self, easting) -> np.ndarray:
        return np.asarray(easting, dtype=np.float64) - self.origin_east

    def y_depth(self, elevation) -> np.ndarray:
        return self.datum_elev - np.asarray(elevation, dtype=np.float64)

    def sensors(self, easting, northing, elevation) -> np.ndarray:
        """Matriz (n,3) [x=Este, y=prof, z=Norte] que consume el forward del motor."""
        return np.column_stack([
            self.east_local(easting),
            self.y_depth(elevation),
            self.north_local(northing),
        ])

    # ── local → UTM (para reportar el cuerpo recuperado en UTM) ───────────────
    def to_easting(self, x_local) -> float:
        return float(x_local) + self.origin_east

    def to_northing(self, z_local) -> float:
        return float(z_local) + self.origin_north

    def to_elevation(self, y_depth) -> float:
        return self.datum_elev - float(y_depth)


# ══════════════════════════════════════════════════════════════════════════════
#  Lectura de los CSV geofísicos
# ══════════════════════════════════════════════════════════════════════════════
def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if r and any(c.strip() for c in r)]
    return header, rows


def _to_float(s: str) -> float:
    s = s.strip()
    if s == "" or s.lower() == "nan":
        return math.nan
    return float(s)


def load_gravity(path: Optional[Path] = None) -> GravitySurvey:
    """Carga la gravimetría DO-27. Descarta cualquier fila con NaN (no debería haber).

    Columnas: X, Y, Z, Anomalia_Bouguer_mGal, Error_Est. La anomalía YA es de Bouguer
    (terreno reducido) → el motor invierte el contraste directo con air-mask plana.
    """
    path = Path(path) if path else _DEFAULT_DO27_ROOT / "DO27_Gravity_mGal.csv"
    _header, rows = _read_csv_rows(path)
    data = np.array([[_to_float(c) for c in r[:5]] for r in rows], dtype=np.float64)
    finite = np.isfinite(data).all(axis=1)
    data = data[finite]
    return GravitySurvey(
        easting=data[:, 0], northing=data[:, 1], elevation=data[:, 2],
        bouguer_mgal=data[:, 3], error_est=data[:, 4],
    )


# Una coordenada UTM plausible en esta zona supera ampliamente este umbral; las filas
# de metadatos IGRF (X=83.8, Y=25.4) caen muy por debajo → criterio robusto de
# separación metadatos-vs-estación, además del NaN en la columna de dato.
_UTM_MIN_PLAUSIBLE = 1000.0


def load_magnetic(path: Optional[Path] = None) -> MagneticSurvey:
    """Carga la magnetometría DO-27, extrae el IGRF y limpia las filas inválidas.

    Las 2 primeras filas NO son estaciones: codifican el campo IGRF como
    `inclinación, declinación, intensidad, nan, nan`. Se extraen como PARÁMETROS del
    kernel magnético y se descartan (junto con cualquier otra fila NaN) de las
    estaciones. Sanity-check de rango sobre el IGRF (Canadá ártico: I≈83.8°,
    D≈25.4°, B0≈60308 nT).
    """
    path = Path(path) if path else _DEFAULT_DO27_ROOT / "DO27_Magnetic_TMI_nT.csv"
    _header, rows = _read_csv_rows(path)
    raw = np.array([[_to_float(c) for c in r[:5]] for r in rows], dtype=np.float64)

    # Filas de metadatos = coordenadas X/Y no plausibles como UTM (campo IGRF).
    is_meta = (np.abs(raw[:, 0]) < _UTM_MIN_PLAUSIBLE) & (np.abs(raw[:, 1]) < _UTM_MIN_PLAUSIBLE)
    meta = raw[is_meta]
    if meta.shape[0] == 0:
        raise ValueError(
            "No se encontraron las filas de metadatos IGRF en el CSV magnético "
            "(se esperaban filas con inclinación/declinación en X/Y)."
        )
    # I y D son consistentes en las filas de metadatos; B0 = intensidad (la mayor de Z).
    inclination = float(meta[0, 0])
    declination = float(meta[0, 1])
    intensity = float(np.nanmax(meta[:, 2]))

    if not (-90.0 <= inclination <= 90.0):
        raise ValueError(f"Inclinación IGRF fuera de rango físico: {inclination}")
    if not (-180.0 <= declination <= 180.0):
        raise ValueError(f"Declinación IGRF fuera de rango físico: {declination}")
    if not (20000.0 <= intensity <= 70000.0):
        raise ValueError(f"Intensidad IGRF fuera de rango terrestre: {intensity} nT")

    # Estaciones limpias = filas con coords UTM plausibles Y dato TMI finito.
    is_station = (~is_meta) & np.isfinite(raw[:, 3])
    n_dropped = int(np.sum(~is_station))
    st = raw[is_station]
    return MagneticSurvey(
        easting=st[:, 0], northing=st[:, 1], elevation=st[:, 2],
        tmi_nt=st[:, 3], error_est=st[:, 4],
        inclination_deg=inclination, declination_deg=declination,
        field_intensity_nt=intensity, n_dropped_nan=n_dropped,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Modelo VERDADERO (ground truth) — malla UBC + .den / .sus
# ══════════════════════════════════════════════════════════════════════════════
def _read_ubc_mesh(mesh_path: Path):
    """Lee una malla TensorMesh UBC-GIF y devuelve (n, centros x/y/z en UTM/elev).

    Formato UBC: línea 1 = nx ny nz; línea 2 = x0 (esquina superior-SW, z=techo);
    líneas 3-5 = anchos hx/hy/hz. El eje z se lista de ARRIBA hacia abajo.
    """
    lines = Path(mesh_path).read_text().split("\n")
    nx, ny, nz = map(int, lines[0].split())
    x0 = list(map(float, lines[1].split()))
    hx = np.array(list(map(float, lines[2].split())))
    hy = np.array(list(map(float, lines[3].split())))
    hz = np.array(list(map(float, lines[4].split())))
    xn = x0[0] + np.concatenate([[0.0], np.cumsum(hx)])
    yn = x0[1] + np.concatenate([[0.0], np.cumsum(hy)])
    zn = x0[2] - np.concatenate([[0.0], np.cumsum(hz)])  # z hacia abajo desde el techo
    xc = 0.5 * (xn[:-1] + xn[1:])
    yc = 0.5 * (yn[:-1] + yn[1:])
    zc = 0.5 * (zn[:-1] + zn[1:])
    return (nx, ny, nz), xc, yc, zc


# Ordenamiento del modelo UBC validado empíricamente contra esta malla: reshape C
# sobre (nx,ny,nz) sin volteo en z. Verificado porque (a) las celdas de aire (-100)
# quedan en el TECHO de cada columna y (b) el centroide del cuerpo cae en el centro
# del survey (≈557300, 7133600), que es donde el forward-model lo coloca.
_UBC_MODEL_RESHAPE_ORDER = "C"
_AIR_NDV = -100.0


def _load_ubc_model_cube(model_path: Path, dims) -> np.ndarray:
    vals = np.loadtxt(model_path)
    return vals.reshape(dims, order=_UBC_MODEL_RESHAPE_ORDER)


def _body_geometry(cube, xc, yc, zc, body_mask, weights, label) -> PipeGroundTruth:
    nx, ny, nz = cube.shape
    ii, jj, kk = np.where(body_mask)
    X, Y, Z = xc[ii], yc[jj], zc[kk]
    w = np.abs(weights[body_mask])
    # superficie sobre el footprint del cuerpo: techo de roca (no aire) por columna
    surf_vals = []
    for a, b in set(zip(ii.tolist(), jj.tolist())):
        col = cube[a, b, :]
        z_rock = zc[col != _AIR_NDV]
        if z_rock.size:
            surf_vals.append(float(z_rock.max()))
    surface = float(np.mean(surf_vals)) if surf_vals else float(Z.max())
    top = float(Z.max())
    return PipeGroundTruth(
        centroid_easting=float(np.average(X, weights=w)),
        centroid_northing=float(np.average(Y, weights=w)),
        centroid_elevation=float(np.average(Z, weights=w)),
        top_elevation=top,
        bottom_elevation=float(Z.min()),
        surface_elevation=surface,
        depth_to_top_m=float(surface - top),
        horizontal_extent_m=(
            float(np.percentile(X, 95) - np.percentile(X, 5)),
            float(np.percentile(Y, 95) - np.percentile(Y, 5)),
        ),
        n_body_cells=int(body_mask.sum()),
        label=label,
    )


def load_ground_truth(root: Optional[Path] = None):
    """Lee el modelo VERDADERO de densidad y susceptibilidad y extrae la geometría.

    Devuelve (grav_truth: PipeGroundTruth, mag_truth: PipeGroundTruth, raw) donde
    `raw` lleva los cubos y coords por si se quiere una comparación voxel a voxel.
    """
    root = Path(root) if root else _DEFAULT_DO27_ROOT
    fwd = root / "Forward"
    dims, xc, yc, zc = _read_ubc_mesh(fwd / "mesh_inverse_ubc.msh")
    den = _load_ubc_model_cube(fwd / "model_grav.den", dims)
    sus = _load_ubc_model_cube(fwd / "model_mag.sus", dims)

    # Gravedad: cuerpo = celdas con contraste de densidad no nulo (kimberlita: Δρ<0).
    grav_body = (den != 0.0) & (den != _AIR_NDV)
    grav_truth = _body_geometry(den, xc, yc, zc, grav_body, den, "grav_pipe")

    # Magnético: cuerpo = celdas con susceptibilidad > 0 (excluye aire/relleno).
    mag_body = (sus > 1e-6) & (sus < 50.0)
    mag_truth = _body_geometry(sus, xc, yc, zc, mag_body, sus, "mag_body")

    raw = {"dims": dims, "xc": xc, "yc": yc, "zc": zc, "den": den, "sus": sus}
    return grav_truth, mag_truth, raw


# ══════════════════════════════════════════════════════════════════════════════
#  Construcción del frame local compartido (grav + mag → misma malla)
# ══════════════════════════════════════════════════════════════════════════════
def build_local_frame(
    grav: GravitySurvey, mag: Optional[MagneticSurvey] = None, *, datum_pad_m: float = 0.0
) -> LocalFrame:
    """Origen común (min Easting/Northing) y datum (máx elevación de sensores).

    Compartir el frame entre gravimetría y magnetometría es lo que permite invertir
    ambas físicas sobre la MISMA malla (requisito del joint).
    """
    easts = [grav.easting]
    norths = [grav.northing]
    elevs = [grav.elevation]
    if mag is not None:
        easts.append(mag.easting)
        norths.append(mag.northing)
        elevs.append(mag.elevation)
    e = np.concatenate(easts)
    n = np.concatenate(norths)
    z = np.concatenate(elevs)
    return LocalFrame(
        origin_east=float(e.min()),
        origin_north=float(n.min()),
        datum_elev=float(z.max()) + float(datum_pad_m),
    )


def summarize(grav: GravitySurvey, mag: MagneticSurvey) -> dict:
    """Resumen de control de calidad de la ingestión (para el GATE del Paso 1)."""
    return {
        "gravity": {
            "n_stations": grav.n,
            "easting_range": [float(grav.easting.min()), float(grav.easting.max())],
            "northing_range": [float(grav.northing.min()), float(grav.northing.max())],
            "elevation_range": [float(grav.elevation.min()), float(grav.elevation.max())],
            "bouguer_mgal_range": [float(grav.bouguer_mgal.min()), float(grav.bouguer_mgal.max())],
            "n_nan": int(np.sum(~np.isfinite(grav.bouguer_mgal))),
        },
        "magnetic": {
            "n_stations": mag.n,
            "n_dropped_nan": mag.n_dropped_nan,
            "tmi_nt_range": [float(mag.tmi_nt.min()), float(mag.tmi_nt.max())],
            "n_nan": int(np.sum(~np.isfinite(mag.tmi_nt))),
            "igrf": {
                "inclination_deg": mag.inclination_deg,
                "declination_deg": mag.declination_deg,
                "field_intensity_nt": mag.field_intensity_nt,
            },
        },
    }


if __name__ == "__main__":
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    g = load_gravity()
    m = load_magnetic()
    summary = summarize(g, m)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    gt_g, gt_m, _ = load_ground_truth()
    print("\nGROUND TRUTH gravimétrico (pipe):")
    print(f"  centroide UTM = ({gt_g.centroid_easting:.1f}, {gt_g.centroid_northing:.1f})  "
          f"elev_centroide={gt_g.centroid_elevation:.0f}")
    print(f"  techo={gt_g.top_elevation:.0f} m  superficie={gt_g.surface_elevation:.0f} m  "
          f"prof_al_techo={gt_g.depth_to_top_m:.0f} m  | celdas={gt_g.n_body_cells}")
    print(f"  extensión horizontal (E-W, N-S) = {gt_g.horizontal_extent_m}")
    print("GROUND TRUTH magnético (cuerpo susceptible):")
    print(f"  centroide UTM = ({gt_m.centroid_easting:.1f}, {gt_m.centroid_northing:.1f})  "
          f"elev_centroide={gt_m.centroid_elevation:.0f}")
    fr = build_local_frame(g, m)
    print(f"\nFrame local: origin_east={fr.origin_east:.1f} origin_north={fr.origin_north:.1f} "
          f"datum_elev={fr.datum_elev:.1f}")
