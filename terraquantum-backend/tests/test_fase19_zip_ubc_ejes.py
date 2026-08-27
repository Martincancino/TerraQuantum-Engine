"""
FASE 19 — ACAD-1c: el ZIP industrial deja de contradecir al fichero del disco.

El mismo error que ACAD-1, en el otro extremo del pipeline. TerraQuantum escribía
DOS ficheros ``model.msh`` distintos para la misma corrida:

  · ``services/gravity_import_service.py`` (ruta de disco, ``load-package``)
    permutaba correctamente a ejes UBC-GIF ``(nE, nN, nZ) = (nx, nz, ny)``;
  · ``services/export_service.py`` (bundle ZIP, lo que el cliente DESCARGA)
    escribía ``{nx} {ny} {nz}`` crudo, con Norte y profundidad intercambiados.

Medido sobre una corrida real de ``20 × 10 × 20``: el fichero del disco decía
``20 20 10`` y el del ZIP ``20 10 20``.

**Con malla cúbica el defecto es INVISIBLE**, así que un test cúbico no vale.
Toda esta suite usa ``NX, NY, NZ = 20, 10, 20`` — asimétrica en el eje que
importa — y ``test_una_malla_cubica_no_serviria_de_gate`` deja pinchada la razón,
para que nadie la "simplifique" a un cubo.

Ejes TerraQuantum (``docs/11_CONVENCION_DE_EJES.md``):
    nx = ESTE      ny = PROFUNDIDAD (+abajo)      nz = NORTE
Ejes UBC-GIF:
    nE = Este      nN = Norte                     nZ = vertical, + hacia ARRIBA
"""

from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from services.block_model_store import PROJECTS_DIR

# Malla NO cúbica: ny (profundidad) distinta de nx y nz. Es la única forma de ver
# la permutación. Los tres valores del gate de la Fase 19.
NX, NY, NZ, BS = 20, 10, 20, 25.0
EASTING0, NORTHING0 = 356534.1, 5999890.6


def _huella(ix: int, iy: int, iz: int) -> float:
    """Huella digital de la celda: ningún par de celdas comparte valor.

    Con ``nx=nz=20`` hace falta que la huella distinga ix de iz, o una
    transposición E↔N pasaría desapercibida dentro de esta suite.
    """
    return 1000.0 * ix + 10.0 * iy + 0.1 * iz + 1.0


def _crear_run(tmp_id: str, *, georreferenciado: bool) -> tuple[str, str]:
    """Corrida en disco con la MISMA forma que las reales (medido: 1951/1951 de
    los parquets en `data/projects` son densos y en orden Fortran
    `ix + nx·iy + nx·ny·iz`, que es lo que el bundle asume al leerlos)."""
    project_id = f"test_fase19_{tmp_id}"
    run_id = "run_zip"
    run_dir = PROJECTS_DIR / project_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = ix.flatten(order="F"); iy = iy.flatten(order="F"); iz = iz.flatten(order="F")
    densidad = np.array([_huella(a, b, c) for a, b, c in zip(ix, iy, iz)], dtype=np.float64)

    pl.DataFrame({
        "ix": ix.astype(np.int64), "iy": iy.astype(np.int64), "iz": iz.astype(np.int64),
        "x_m": (ix * BS) + BS / 2, "y_m": (iy * BS) + BS / 2, "z_m": (iz * BS) + BS / 2,
        "density": densidad,
        "density_t_m3": densidad,
        "density_contrast_t_m3": densidad - 2.6,
        "is_active": np.ones(len(densidad), dtype=bool),
        "run_type": ["gravity"] * len(densidad),
        "schema_version": ["v4.0"] * len(densidad),
    }).write_parquet(str(run_dir / "block_model.parquet"))

    (run_dir / "inputs.json").write_text(
        json.dumps({"nx": NX, "ny": NY, "nz": NZ, "block_size": BS, "depth": NY * BS}),
        encoding="utf-8",
    )

    if georreferenciado:
        (PROJECTS_DIR / project_id / "project_meta.json").write_text(json.dumps({
            "project_id": project_id, "epsg_code": 32719, "utm_zone": "19S",
            "utm_hemisphere": "S", "horizontal_datum": "WGS84",
            "georef_confidence": "MEDIUM", "georef_type": "csv_utm",
            "crs_contract": {"input_crs": "EPSG:32719", "epsg_code": 32719,
                             "utm_zone": "19S", "utm_hemisphere": "S",
                             "horizontal_datum": "WGS84", "vertical_datum": None},
        }), encoding="utf-8")
        (run_dir / "gravity_import_metadata.json").write_text(json.dumps({
            "coordinate_transform": {
                "method": "utm_sw_origin_shift", "transformed": True,
                "absolute_origin": {"easting": EASTING0, "northing": NORTHING0},
            }
        }), encoding="utf-8")
    return project_id, run_id


@pytest.fixture
def run_local():
    pid, rid = _crear_run(uuid.uuid4().hex[:8], georreferenciado=False)
    yield pid, rid
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


@pytest.fixture
def run_utm():
    pid, rid = _crear_run(uuid.uuid4().hex[:8], georreferenciado=True)
    yield pid, rid
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


def _bundle(pid: str, rid: str) -> dict[str, str]:
    from services.export_service import create_run_bundle_zip

    payload, _ = create_run_bundle_zip(pid, rid)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {n: zf.read(n).decode("utf-8") for n in zf.namelist()
                if n.endswith((".msh", ".den", ".gslib", ".dat", ".dfn"))}


def _msh_del_disco(tmp_path: Path, *, origin_east=0.0, origin_north=0.0) -> tuple[str, str]:
    """Escribe la MISMA corrida por la ruta de disco y devuelve (.msh, .den).

    Réplica exacta del empalme de `gravity_import_service.py` §7: reshape Fortran
    (nx, ny, nz) → transpose (0,2,1) → flip del eje vertical → `export_core_to_ubc`
    con `(nE, nN, nZ) = (nx, nz, ny)`.
    """
    from services.export_service import export_core_to_ubc

    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    dens = np.array([_huella(a, b, c) for a, b, c in
                     zip(ix.flatten(order="F"), iy.flatten(order="F"), iz.flatten(order="F"))])
    arr3d = dens.reshape((NX, NY, NZ), order="F")            # (E, prof, N)
    arr_ubc = np.transpose(arr3d, (0, 2, 1))[:, :, ::-1]     # (E, N, Z-arriba)

    salida = export_core_to_ubc(
        output_dir=str(tmp_path), run_prefix="model",
        nx=NX, ny=NZ, nz=NY,                                  # UBC: nE, nN, nZ
        dx=BS,
        est_density=np.ascontiguousarray(arr_ubc).ravel(order="F"),
        origin_x=origin_east, origin_y=origin_north,
        origin_z=-float(NY * BS),                             # techo del modelo = 0 m
        project_id="test", run_id="test",
    )
    assert salida, "la ruta de disco no produjo el par .msh/.den"
    return (Path(salida["mesh_path"]).read_text(encoding="ascii"),
            Path(salida["model_path"]).read_text(encoding="ascii"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. EL GATE — las dos rutas UBC escriben lo mismo
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.integration
def test_la_cabecera_ubc_del_zip_declara_nE_nN_nZ(run_local):
    """El número que medía el defecto: `20 20 10`, no `20 10 20`."""
    ficheros = _bundle(*run_local)
    primera = ficheros["model.msh"].splitlines()[0]

    assert primera == f"{NX} {NZ} {NY}", (
        f"la cabecera UBC del ZIP dice «{primera}»; UBC-GIF es (nE, nN, nZ) = "
        f"({NX}, {NZ}, {NY}). Con «{NX} {NY} {NZ}» el cliente descarga un modelo "
        f"con el Norte y la profundidad intercambiados (ACAD-1c).")


@pytest.mark.integration
def test_las_dos_rutas_ubc_escriben_la_misma_malla(run_local, tmp_path):
    """El gate de la Fase 19: los dos escritores, byte a byte.

    No compara "cabeceras parecidas": compara el fichero entero. Es la única
    forma de que la divergencia no pueda volver por el origen o por los anchos
    de celda en vez de por la permutación.
    """
    del_zip = _bundle(*run_local)["model.msh"]
    del_disco, _ = _msh_del_disco(tmp_path)

    assert del_zip == del_disco, (
        "el `model.msh` del ZIP y el del disco vuelven a discrepar:\n"
        f"  ZIP   : {del_zip.splitlines()[:2]}\n"
        f"  disco : {del_disco.splitlines()[:2]}")


@pytest.mark.integration
def test_las_dos_rutas_ubc_colocan_cada_celda_en_el_mismo_sitio(run_local, tmp_path):
    """Y el modelo, no sólo la malla. Cada celda lleva una huella única."""
    del_zip = _bundle(*run_local)["model.den"]
    _, del_disco = _msh_del_disco(tmp_path)

    v_zip = np.array([float(s) for s in del_zip.split()])
    v_disco = np.array([float(s) for s in del_disco.split()])
    assert v_zip.size == NX * NY * NZ
    assert v_zip.size == v_disco.size
    assert np.array_equal(v_zip, v_disco), (
        f"{int(np.sum(v_zip != v_disco))} de {v_zip.size} celdas caen en distinto "
        f"sitio según se descargue el ZIP o se lea el fichero del disco")


@pytest.mark.unit
def test_una_malla_cubica_no_serviria_de_gate():
    """Por qué esta suite usa 20×10×20 y no un cubo.

    Con `nx == ny == nz` la permutación (nx, nz, ny) es la identidad: un test
    cúbico pasa con el defecto puesto. Queda pinchado para que nadie lo
    "simplifique".
    """
    from services.export_service import _ubc_msh_text

    cubica = _ubc_msh_text(12, 12, 12, 50.0).splitlines()[0]
    assert cubica == "12 12 12", "una malla cúbica es invisible a la permutación"

    no_cubica = _ubc_msh_text(NX, NY, NZ, BS).splitlines()[0]
    assert no_cubica != f"{NX} {NY} {NZ}", (
        "con malla no cúbica la cabecera TIENE que diferir del orden TQ crudo")


@pytest.mark.integration
def test_el_origen_del_zip_es_el_de_la_corrida(run_utm, tmp_path):
    """«Escribir el origen real en vez de `0 0 0`» (Fase 19, trabajo 2).

    Con georreferencia declarada, el `.msh` publica el origen UTM absoluto — y
    las dos rutas siguen coincidiendo.
    """
    del_zip = _bundle(*run_utm)["model.msh"]
    origen = [float(v) for v in del_zip.splitlines()[1].split()]

    assert origen[0] == pytest.approx(EASTING0, abs=1e-3), "el origen Este no es el real"
    assert origen[1] == pytest.approx(NORTHING0, abs=1e-3), "el origen Norte no es el real"
    # Z UBC es + hacia arriba y el techo del modelo es la superficie (0 m).
    assert origen[2] == pytest.approx(0.0, abs=1e-6)

    del_disco, _ = _msh_del_disco(tmp_path, origin_east=EASTING0, origin_north=NORTHING0)
    assert del_zip == del_disco


@pytest.mark.integration
def test_sin_georreferencia_el_origen_es_local_y_se_declara(run_local):
    """Sin CRS ni origen absoluto, el frame es local: `0 0 0` es la verdad."""
    origen = [float(v) for v in _bundle(*run_local)["model.msh"].splitlines()[1].split()]
    assert origen == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# 2. LOS OTROS DOS FICHEROS DEL MISMO ZIP — GSLIB y ASEG-GDF2
# ══════════════════════════════════════════════════════════════════════════════
def _celda_de_la_huella(valor: float) -> tuple[int, int, int]:
    """Invierte `_huella` → (ix, iy, iz). Sin esto no se puede afirmar nada."""
    v = round(valor - 1.0, 6)
    ix = int(v // 1000.0); v -= ix * 1000.0
    iy = int(v // 10.0);   v -= iy * 10.0
    iz = int(round(v / 0.1))
    return ix, iy, iz


@pytest.mark.integration
def test_el_gslib_etiqueta_los_ejes_que_dice_etiquetar(run_local):
    """`X_m / Y_m / Z_m` sobre índices internos: la columna Y llevaba PROFUNDIDAD.

    Un consumidor de GSLIB (SGeMS, ISATIS) lee X=Este, Y=Norte, Z=cota. El
    escritor ponía Y=(iy+½)·bs, e `iy` es la profundidad; y Z=−(iz+½)·bs, e `iz`
    es el Norte. El modelo entregado salía tumbado.
    """
    texto = _bundle(*run_local)["model.gslib"]
    lineas = texto.splitlines()
    n_cols = int(lineas[1])
    filas = lineas[2 + n_cols:]
    assert len(filas) == NX * NY * NZ

    for fila in (filas[0], filas[1], filas[NX], filas[NX * NY], filas[-1]):
        campos = fila.split()
        x, y, z, dens = float(campos[0]), float(campos[1]), float(campos[2]), float(campos[3])
        ix, iy, iz = _celda_de_la_huella(dens)
        assert x == pytest.approx((ix + 0.5) * BS, abs=1e-6), "X_m no es el Este"
        assert y == pytest.approx((iz + 0.5) * BS, abs=1e-6), (
            f"Y_m={y} para la celda (ix={ix}, iy={iy}, iz={iz}); Y_m es el NORTE, "
            f"que vale {(iz + 0.5) * BS}. Si sale {(iy + 0.5) * BS}, se está "
            f"escribiendo la profundidad en la columna del northing.")
        assert z == pytest.approx(-(iy + 0.5) * BS, abs=1e-6), (
            "Z_m es la cota relativa al techo del modelo (negativa hacia abajo)")


@pytest.mark.integration
def test_el_aseg_gdf2_etiqueta_los_ejes_que_declara_su_dfn(run_local):
    """El `.dfn` declara Y_m = «Northing» y Z_m = «Depth positive downward».

    El `.dat` escribía `iy` (profundidad) en Y_m y `iz` (Norte) en Z_m: el mismo
    defecto que el GSLIB, en el fichero que va a Oasis Montaj.
    """
    ficheros = _bundle(*run_local)
    assert "Northing" in ficheros["model.dfn"]
    filas = [l for l in ficheros["model.dat"].splitlines() if not l.startswith("!")]
    assert len(filas) == NX * NY * NZ

    for fila in (filas[0], filas[1], filas[NX], filas[NX * NY], filas[-1]):
        campos = fila.split()
        x, y, z, dens = float(campos[0]), float(campos[1]), float(campos[2]), float(campos[3])
        ix, iy, iz = _celda_de_la_huella(dens)
        assert x == pytest.approx((ix + 0.5) * BS, abs=1e-6), "X_m no es el Este"
        assert y == pytest.approx((iz + 0.5) * BS, abs=1e-6), "Y_m no es el Norte"
        assert z == pytest.approx((iy + 0.5) * BS, abs=1e-6), (
            "Z_m se declara «Depth positive downward»: tiene que ser el eje iy")
