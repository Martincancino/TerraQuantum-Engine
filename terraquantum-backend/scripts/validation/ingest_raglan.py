"""
Raglan (Ni-Cu, Quebec) — Adaptador de ingestión → formato TerraQuantum
=======================================================================

SEGUNDO benchmark externo. A diferencia de DO-27 (synthetic-based-on), Raglan es
**dato de campo REAL**: TMI de un survey magnético real del depósito de Ni-Cu de Raglan
(Northern Quebec), invertido en 3D hacia 1997 (la inversión que ayudó a ubicar un sondaje
mineralizado). Tutorial SimPEG Transform 2021.

Reusa la maquinaria de DO-27 (`ingest_do27.LocalFrame`, convención del motor x=Norte/
z=Este/y=prof) y la generaliza a las particularidades de Raglan:
  • Coordenadas LOCALES (no UTM) → no se resta origen UTM; se usa el origen de la malla.
  • Z ≈ 40 m constante = altura de drape (vuelo) sobre la superficie (z0=0).
  • Std_nT por estación = incertidumbre REAL → se usa como σ (no adaptativo).
  • IGRF se EXTRAE del encabezado de `data/Raglan_1997/obs.mag` (no del CSV; no se inventa).
  • NO hay modelo verdadero sintético: el ground truth es la INVERSIÓN DE REFERENCIA
    publicada (`data/Raglan_1997/maginv3d.sus`, UBC maginv3d) + la posición de la anomalía
    dominante en los datos.

CAVEAT (a favor, no en contra): al ser dato real, pasar este benchmark es evidencia MÁS
fuerte que DO-27. El precio es que la "verdad" es una inversión de referencia (difusa), no
un cuerpo sintético nítido → la métrica es estructura/posición, no un valor puntual.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.validation.ingest_do27 import LocalFrame, _read_csv_rows, _to_float

_DEFAULT_RAGLAN_ROOT = Path(__file__).resolve().parents[3] / "Raglan_Magnetic"


@dataclass
class RaglanMagneticSurvey:
    """Magnetometría Raglan: TMI (nT) real + σ por estación + IGRF del header."""
    east: np.ndarray         # X local (m)  → Este
    north: np.ndarray        # Y local (m)  → Norte
    elevation: np.ndarray    # Z (m, drape)
    tmi_nt: np.ndarray
    sigma_nt: np.ndarray     # Std_nT real por estación
    inclination_deg: float
    declination_deg: float
    field_intensity_nt: float
    n_dropped_nan: int

    @property
    def n(self) -> int:
        return int(self.east.shape[0])


@dataclass
class RaglanReference:
    """Ground truth = inversión de referencia maginv3d (1997) + anomalía dominante.

    El modelo de referencia es difuso (inversión de campo real con depth-weighting), así
    que se reporta tanto el PICO (celda de máxima susc, ≈ blanco de sondaje) como el
    centroide de la región fuerte (susc > frac·max).
    """
    peak_east: float
    peak_north: float
    peak_depth_m: float       # profundidad bajo superficie (+abajo)
    strong_centroid_east: float
    strong_centroid_north: float
    strong_centroid_depth_m: float
    data_anomaly_east: float  # centroide de la anomalía fuerte en los DATOS (independiente)
    data_anomaly_north: float
    n_strong_cells: int
    susc_max: float
    threshold_frac: float


# ── Ordenamiento del modelo de referencia UBC maginv3d, validado por correlación 0.90
# entre su forward (motor de TQ) y los datos observados: reshape (ny,nx,nz) C-order y
# transponer a (nx,ny,nz). NO es order='F' directo. Ver do27 para el patrón de validación.
def _ref_cube(sus: np.ndarray, nx: int, ny: int, nz: int) -> np.ndarray:
    return sus.reshape((ny, nx, nz), order="C").transpose(1, 0, 2)


def load_raglan_magnetic(
    csv_path: Optional[Path] = None, obs_path: Optional[Path] = None
) -> RaglanMagneticSurvey:
    """Carga el TMI real de Raglan + σ por estación + IGRF (del header de obs.mag)."""
    root = _DEFAULT_RAGLAN_ROOT
    csv_path = Path(csv_path) if csv_path else root / "Raglan_Magnetic_TMI_nT.csv"
    obs_path = Path(obs_path) if obs_path else root / "data" / "Raglan_1997" / "obs.mag"

    # IGRF del encabezado UBC: "incl  decl  geomag" en la primera línea de obs.mag.
    incl, decl, b0 = _read_igrf_from_obs(obs_path)

    _header, rows = _read_csv_rows(csv_path)
    raw = np.array([[_to_float(c) for c in r[:5]] for r in rows], dtype=np.float64)
    finite = np.isfinite(raw).all(axis=1)
    n_dropped = int(np.sum(~finite))
    raw = raw[finite]
    return RaglanMagneticSurvey(
        east=raw[:, 0], north=raw[:, 1], elevation=raw[:, 2],
        tmi_nt=raw[:, 3], sigma_nt=raw[:, 4],
        inclination_deg=incl, declination_deg=decl, field_intensity_nt=b0,
        n_dropped_nan=n_dropped,
    )


def _read_igrf_from_obs(obs_path: Path) -> tuple[float, float, float]:
    """Extrae (inclinación, declinación, intensidad) del header UBC de obs.mag.

    Línea 1: `incl  decl  geomag  !! comentario`. Sanity-check (Quebec ártico ~62°N:
    I≈83°, |D|≈32°, B0≈60000 nT).
    """
    first = Path(obs_path).read_text().splitlines()[0]
    parts = first.split("!!")[0].split()
    incl, decl, b0 = float(parts[0]), float(parts[1]), float(parts[2])
    if not (70.0 <= incl <= 90.0):
        raise ValueError(f"Inclinación IGRF Raglan fuera de rango esperado: {incl}")
    if not (-90.0 <= decl <= 90.0):
        raise ValueError(f"Declinación IGRF fuera de rango: {decl}")
    if not (40000.0 <= b0 <= 70000.0):
        raise ValueError(f"Intensidad IGRF fuera de rango: {b0} nT")
    return incl, decl, b0


def load_raglan_reference(
    *, root: Optional[Path] = None, threshold_frac: float = 0.5,
    survey: Optional[RaglanMagneticSurvey] = None,
) -> RaglanReference:
    """Carga la inversión de referencia maginv3d y extrae la posición del cuerpo dominante.

    threshold_frac: la región "fuerte" del modelo de referencia = celdas con
    susc > threshold_frac · max(susc). El PICO (celda máx) es el blanco de sondaje.
    """
    root = Path(root) if root else _DEFAULT_RAGLAN_ROOT
    refdir = root / "data" / "Raglan_1997"
    nx, ny, nz, x0, y0, hx, hy, hz = _read_ubc_msh_2d(refdir / "mesh.msh")
    xc = x0 + (np.arange(nx) + 0.5) * hx        # Este (data X)
    yc = y0 + (np.arange(ny) + 0.5) * hy        # Norte (data Y)
    zc = (np.arange(nz) + 0.5) * hz             # profundidad bajo superficie (+abajo)

    sus = np.loadtxt(refdir / "maginv3d.sus")
    cube = _ref_cube(sus, nx, ny, nz)
    smax = float(cube.max())

    am = np.unravel_index(int(np.argmax(cube)), cube.shape)
    peak_e, peak_n, peak_d = float(xc[am[0]]), float(yc[am[1]]), float(zc[am[2]])

    thr = threshold_frac * smax
    mk = cube > thr
    ii, jj, kk = np.where(mk)
    w = cube[mk]
    sc_e = float(np.average(xc[ii], weights=w))
    sc_n = float(np.average(yc[jj], weights=w))
    sc_d = float(np.average(zc[kk], weights=w))

    # Anomalía dominante en los DATOS (independiente del modelo de referencia): centroide
    # de las estaciones con TMI más fuerte (señal real del cuerpo principal).
    da_e, da_n = (None, None)
    if survey is not None:
        t = survey.tmi_nt
        strong = t > np.percentile(t, 97)   # cola positiva = cuerpo magnético principal
        da_e = float(np.average(survey.east[strong], weights=t[strong]))
        da_n = float(np.average(survey.north[strong], weights=t[strong]))

    return RaglanReference(
        peak_east=peak_e, peak_north=peak_n, peak_depth_m=peak_d,
        strong_centroid_east=sc_e, strong_centroid_north=sc_n, strong_centroid_depth_m=sc_d,
        data_anomaly_east=da_e, data_anomaly_north=da_n,
        n_strong_cells=int(mk.sum()), susc_max=smax, threshold_frac=threshold_frac,
    )


def load_reference_cube(*, root: Optional[Path] = None):
    """Devuelve (cube[nx,ny,nz], xc(Este), yc(Norte), zc(prof+abajo)) del modelo de
    referencia, con el ordenamiento UBC validado. Para comparación estructural en el
    dominio del modelo (no solo picos)."""
    root = Path(root) if root else _DEFAULT_RAGLAN_ROOT
    refdir = root / "data" / "Raglan_1997"
    nx, ny, nz, x0, y0, hx, hy, hz = _read_ubc_msh_2d(refdir / "mesh.msh")
    xc = x0 + (np.arange(nx) + 0.5) * hx
    yc = y0 + (np.arange(ny) + 0.5) * hy
    zc = (np.arange(nz) + 0.5) * hz
    cube = _ref_cube(np.loadtxt(refdir / "maginv3d.sus"), nx, ny, nz)
    return cube, xc, yc, zc


def _read_ubc_msh_2d(path: Path):
    """Lee la malla UBC compacta de Raglan: `nx ny nz` / `x0 y0 z0` / `40*100.0` ...."""
    lines = Path(path).read_text().splitlines()
    nx, ny, nz = map(int, lines[0].split())
    x0, y0, z0 = map(float, lines[1].split())

    def _spacing(line: str) -> float:
        # formato "40*100.0" (n celdas iguales) → ancho de celda
        return float(line.split("*")[1]) if "*" in line else float(line.split()[0])

    return nx, ny, nz, x0, y0, _spacing(lines[2]), _spacing(lines[3]), _spacing(lines[4])


def build_raglan_frame(survey: RaglanMagneticSurvey, *, root: Optional[Path] = None) -> LocalFrame:
    """Frame local alineado con la malla de referencia (origen = esquina de la malla).

    x=Norte ← data Y, z=Este ← data X, y=prof ← (datum=0 superficie) − elevación. Los
    sensores quedan a y=−40 (40 m sobre la superficie, su altura de drape).
    """
    root = Path(root) if root else _DEFAULT_RAGLAN_ROOT
    nx, ny, nz, x0, y0, *_ = _read_ubc_msh_2d(root / "data" / "Raglan_1997" / "mesh.msh")
    return LocalFrame(origin_east=float(x0), origin_north=float(y0), datum_elev=0.0)


def summarize(survey: RaglanMagneticSurvey) -> dict:
    return {
        "n_stations": survey.n,
        "n_dropped_nan": survey.n_dropped_nan,
        "east_range": [float(survey.east.min()), float(survey.east.max())],
        "north_range": [float(survey.north.min()), float(survey.north.max())],
        "elevation_range": [float(survey.elevation.min()), float(survey.elevation.max())],
        "tmi_nt_range": [float(survey.tmi_nt.min()), float(survey.tmi_nt.max())],
        "sigma_nt_range": [float(survey.sigma_nt.min()), float(survey.sigma_nt.max())],
        "sigma_nt_median": float(np.median(survey.sigma_nt)),
        "n_nan": int(np.sum(~np.isfinite(survey.tmi_nt))),
        "igrf": {
            "inclination_deg": survey.inclination_deg,
            "declination_deg": survey.declination_deg,
            "field_intensity_nt": survey.field_intensity_nt,
        },
    }


if __name__ == "__main__":
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    s = load_raglan_magnetic()
    print(json.dumps(summarize(s), indent=2, ensure_ascii=False))
    ref = load_raglan_reference(survey=s)
    print("\nReferencia (maginv3d 1997):")
    print(f"  PICO susc: Este={ref.peak_east:.0f} Norte={ref.peak_north:.0f} prof={ref.peak_depth_m:.0f}m (max κ={ref.susc_max:.3f})")
    print(f"  centroide fuerte (>{ref.threshold_frac}·max): Este={ref.strong_centroid_east:.0f} Norte={ref.strong_centroid_north:.0f} prof={ref.strong_centroid_depth_m:.0f}m (n={ref.n_strong_cells})")
    print(f"  anomalía dominante en DATOS: Este={ref.data_anomaly_east:.0f} Norte={ref.data_anomaly_north:.0f}")
    fr = build_raglan_frame(s)
    print(f"\nFrame: origin_east={fr.origin_east} origin_north={fr.origin_north} datum={fr.datum_elev}")
