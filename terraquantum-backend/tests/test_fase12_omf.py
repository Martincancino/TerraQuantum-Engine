"""FASE 12 (auditoría 06 §10) — OMF: dejar de ser una isla, MEDIDO.

El criterio de aceptación de la fase es EXTERNO: *«un archivo OMF generado por TQ
abre correctamente en un visor OMF de terceros, con geometría y atributos
íntegros»*. Un visor de terceros no se puede ejecutar en CI, así que aquí se mide
lo que sí es medible, y se dice con precisión qué queda fuera:

  1. **Geometría íntegra** — cada celda del parquet cae en la celda del OMF que le
     corresponde, con su valor. Con un CONTROL que demuestra que la comparación
     sabe distinguir (la lección de la Fase 11: un probe que no puede fallar no
     defiende nada).
  2. **El orden de celdas es el de la especificación de GMG** — «Ordering
     increases U first, then V, then W». El dato de prueba es asimétrico a
     propósito: cualquier transposición cambia el resultado.
  3. **El contenedor cumple el formato publicado** — la cabecera se parsea A MANO
     siguiendo la documentación, sin usar el lector de `omf`. Es la única parte
     del fichero que se puede verificar sin caer en «lo que escribió `omf` lo lee
     `omf`».
  4. **Nada se inventa** — ni malla cuando no es reconstruible, ni georreferencia
     cuando el proyecto no la declara, ni atributos vacíos o duplicados.
  5. **Ida y vuelta de sondajes** — exportar e importar devuelve el intervalo
     original, litología incluida.

LO QUE ESTA SUITE NO PRUEBA, y hay que decirlo: el CONTENEDOR lo escribe la
implementación de referencia (`omf==1.0.1`), así que leerlo con esa misma
librería no es una verificación independiente de la serialización. Lo que sí
verifica de forma independiente es el MAPEO de TerraQuantum (ejes, orden,
coordenadas, atributos), que es donde vive el riesgo real de esta fase.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import struct
import sys
import uuid

import numpy as np
import polars as pl
import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.block_model_store import PROJECTS_DIR  # noqa: E402
from services.omf_export_service import (  # noqa: E402
    OmfExportError,
    OmfGridSpec,
    build_omf_project,
    export_run_to_omf,
    load_georef,
    permute_tq_grid_to_omf,
)
from services.omf_import_service import import_omf_boreholes  # noqa: E402

# Malla deliberadamente ASIMÉTRICA en los tres ejes: con nx=ny=nz una permutación
# equivocada pasaría desapercibida, que es exactamente el fallo que esta fase
# viene a impedir.
NX, NY, NZ, BS = 3, 2, 4, 10.0     # nx=Este, ny=PROFUNDIDAD, nz=Norte
EASTING0, NORTHING0 = 356534.1, 5999890.6


def _valor(ix: int, iy: int, iz: int) -> float:
    """Huella digital de la celda: ningún par de celdas comparte valor."""
    return 100.0 * ix + 10.0 * iy + 1.0 * iz


def _crear_run(tmp_id: str, *, georreferenciado: bool, con_sondajes: bool) -> tuple[str, str]:
    """Fabrica una corrida en disco con la MISMA forma que las reales."""
    project_id = f"test_fase12_{tmp_id}"
    run_id = "run_omf"
    run_dir = PROJECTS_DIR / project_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = ix.flatten(order="F"); iy = iy.flatten(order="F"); iz = iz.flatten(order="F")
    densidad = np.array([_valor(a, b, c) for a, b, c in zip(ix, iy, iz)], dtype=np.float64)

    pl.DataFrame({
        "ix": ix.astype(np.int64), "iy": iy.astype(np.int64), "iz": iz.astype(np.int64),
        "x_m": (ix * BS) + BS / 2, "y_m": (iy * BS) + BS / 2, "z_m": (iz * BS) + BS / 2,
        "density_t_m3": densidad,
        "rho": densidad,                                   # duplicada a propósito
        "density_contrast_t_m3": densidad - 2.6,
        "grade": np.full(len(densidad), np.nan),           # vacía a propósito
        "is_active": np.ones(len(densidad), dtype=bool),
        "run_type": ["gravity"] * len(densidad),
        "schema_version": ["v4.0"] * len(densidad),
    }).write_parquet(str(run_dir / "block_model.parquet"))

    (run_dir / "inputs.json").write_text(
        json.dumps({"nx": NX, "ny": NY, "nz": NZ, "block_size": BS, "depth": NY * BS}),
        encoding="utf-8",
    )

    if con_sondajes:
        (run_dir / "boreholes.json").write_text(json.dumps([
            {"x_m": 15.0, "z_m": 25.0, "y_from_m": 2.0, "y_to_m": 9.0,
             "density_t_m3": 2.85, "lithology": "sulfuro"},
            {"x_m": 15.0, "z_m": 25.0, "y_from_m": 9.0, "y_to_m": 17.0,
             "density_t_m3": 3.10, "lithology": "magnetita"},
        ]), encoding="utf-8")

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
    project_id, run_id = _crear_run(uuid.uuid4().hex[:8], georreferenciado=False, con_sondajes=True)
    yield project_id, run_id
    shutil.rmtree(PROJECTS_DIR / project_id, ignore_errors=True)


@pytest.fixture
def run_utm():
    project_id, run_id = _crear_run(uuid.uuid4().hex[:8], georreferenciado=True, con_sondajes=False)
    yield project_id, run_id
    shutil.rmtree(PROJECTS_DIR / project_id, ignore_errors=True)


def _leer_volumen(payload: bytes, tmp_path: pathlib.Path):
    import omf

    destino = tmp_path / "leido.omf"
    destino.write_bytes(payload)
    with destino.open("rb") as handle:
        proyecto = omf.OMFReader(handle).get_project()
    volumen = [e for e in proyecto.elements if type(e).__name__ == "VolumeElement"][0]
    return proyecto, volumen


# ═════════════════════════════════════════════════════════════════════════════
# 1. La permutación de ejes
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_la_permutacion_lleva_profundidad_a_altura_y_norte_a_v():
    """(Este, profundidad↓, Norte) → (Este, Norte, arriba), sin tocar los valores."""
    spec = OmfGridSpec(nx=NX, ny=NY, nz=NZ, block_size=BS)
    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    plano = np.array([
        _valor(a, b, c) for a, b, c in zip(
            ix.flatten(order="F"), iy.flatten(order="F"), iz.flatten(order="F"))
    ])

    salida = permute_tq_grid_to_omf(plano, spec)

    assert salida.shape == (NX * NY * NZ,)
    assert sorted(salida.tolist()) == sorted(plano.tolist()), (
        "la permutación inventó o perdió valores: debe ser una reordenación pura"
    )
    for m, valor in enumerate(salida):
        iu = m % NX                       # u = Este
        iv = (m // NX) % NZ               # v = Norte
        iw = m // (NX * NZ)               # w = arriba
        esperado = _valor(iu, NY - 1 - iw, iv)
        assert valor == esperado, f"celda OMF {m} (u={iu} v={iv} w={iw}) mal colocada"


@pytest.mark.unit
def test_control_la_comprobacion_de_permutacion_detecta_una_transposicion():
    """CONTROL: si el test de arriba no cazara una transposición, no defendería nada."""
    spec = OmfGridSpec(nx=NX, ny=NY, nz=NZ, block_size=BS)
    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    plano = np.array([
        _valor(a, b, c) for a, b, c in zip(
            ix.flatten(order="F"), iy.flatten(order="F"), iz.flatten(order="F"))
    ])
    correcta = permute_tq_grid_to_omf(plano, spec)

    # La mutación: NO voltear el eje vertical (olvidar que profundidad crece hacia
    # abajo y altura hacia arriba) — el error más plausible de esta fase.
    mutada = np.transpose(
        plano.reshape((NX, NY, NZ), order="F"), (0, 2, 1)
    ).ravel(order="F")

    assert not np.array_equal(correcta, mutada), (
        "olvidar el volteo vertical daría el MISMO resultado: el test es inerte"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Geometría íntegra, celda a celda
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_cada_celda_del_parquet_cae_donde_debe_en_el_omf(run_local, tmp_path):
    project_id, run_id = run_local
    payload, _, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)
    _, volumen = _leer_volumen(payload, tmp_path)

    geometria = volumen.geometry
    nu, nv, nw = (len(geometria.tensor_u), len(geometria.tensor_v), len(geometria.tensor_w))
    assert (nu, nv, nw) == (NX, NZ, NY), (
        f"la malla OMF debe ser (Este={NX}, Norte={NZ}, vertical={NY}), salió {(nu, nv, nw)}"
    )

    origen = [float(v) for v in geometria.origin]
    assert origen == [0.0, 0.0, -NY * BS], "el fondo del modelo debe estar a -profundidad"

    valores = {d.name: np.asarray(d.array.array) for d in volumen.data}["Density_t_m3"]
    indices = np.arange(nu * nv * nw)
    este = origen[0] + (indices % nu + 0.5) * BS
    norte = origen[1] + ((indices // nu) % nv + 0.5) * BS
    altura = origen[2] + (indices // (nu * nv) + 0.5) * BS
    tabla = {
        (round(e, 3), round(n, 3), round(z, 3)): valores[i]
        for i, (e, n, z) in enumerate(zip(este, norte, altura))
    }

    frame = pl.read_parquet(str(PROJECTS_DIR / project_id / "runs" / run_id / "block_model.parquet"))
    coincidencias = 0
    for x, y, z, densidad in zip(frame["x_m"], frame["y_m"], frame["z_m"], frame["density_t_m3"]):
        clave = (round(x, 3), round(z, 3), round(-y, 3))
        assert clave in tabla, f"la celda del parquet en {clave} no existe en el OMF"
        assert tabla[clave] == pytest.approx(densidad), f"valor equivocado en {clave}"
        coincidencias += 1
    assert coincidencias == NX * NY * NZ


@pytest.mark.integration
def test_control_la_comparacion_celda_a_celda_discrimina(run_local, tmp_path):
    """CONTROL del test anterior: con los valores alterados TIENE que fallar."""
    project_id, run_id = run_local
    payload, _, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)
    _, volumen = _leer_volumen(payload, tmp_path)
    valores = {d.name: np.asarray(d.array.array) for d in volumen.data}["Density_t_m3"]

    frame = pl.read_parquet(str(PROJECTS_DIR / project_id / "runs" / run_id / "block_model.parquet"))
    esperados = sorted(frame["density_t_m3"].to_list())
    assert sorted(valores.tolist()) == esperados
    assert sorted((valores + 1.0).tolist()) != esperados, (
        "sumar 1.0 a todo no cambia la comparación: es inerte"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. El contenedor cumple el formato publicado (sin usar el lector de omf)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_la_cabecera_cumple_el_formato_documentado(run_local):
    """Cabecera de 60 bytes parseada A MANO según la documentación de OMF v1.

    Es la única comprobación del fichero que no pasa por el lector de `omf`, y por
    tanto la única que no es circular respecto de su escritor.
    """
    project_id, run_id = run_local
    payload, nombre, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)

    assert nombre.endswith(".omf")
    assert payload[:4] == b"\x84\x83\x82\x81", "número mágico de OMF ausente"

    version = struct.unpack("<32s", payload[4:36])[0].rstrip(b"\x00")
    assert version == b"OMF-v0.9.0", f"versión de contenedor inesperada: {version!r}"

    uid_proyecto = uuid.UUID(bytes=struct.unpack("<16s", payload[36:52])[0])
    inicio_json = struct.unpack("<Q", payload[52:60])[0]
    assert 60 <= inicio_json < len(payload), "el puntero al JSON cae fuera del fichero"

    registro = json.loads(payload[inicio_json:].decode("utf-8"))
    assert str(uid_proyecto) in registro, "el UID de la cabecera no está en el índice JSON"
    proyecto = registro[str(uid_proyecto)]
    assert proyecto["__class__"] == "Project"
    assert proyecto["units"] == "m"

    clases = {registro[uid]["__class__"] for uid in proyecto["elements"]}
    assert "VolumeElement" in clases


# ═════════════════════════════════════════════════════════════════════════════
# 4. Nada se inventa
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_los_atributos_vacios_y_duplicados_no_se_publican(run_local):
    project_id, run_id = run_local
    _, manifiesto = build_omf_project(project_id, run_id, include_surfaces=False)
    publicados = manifiesto["volume_attributes"]

    assert "Density_t_m3" in publicados
    assert "Is_Active" in publicados
    assert not any("grade" in nombre.lower() for nombre in publicados), (
        "`grade` es NaN en todas las celdas: publicarla sería una ley falsa"
    )
    assert len(publicados) == len(set(publicados))


@pytest.mark.integration
def test_georreferencia_absoluta_solo_cuando_el_proyecto_la_declara(run_utm, run_local):
    utm_project, utm_run = run_utm
    local_project, local_run = run_local

    absoluta = load_georef(utm_project, utm_run)
    assert absoluta.is_absolute and absoluta.epsg == 32719
    assert (absoluta.easting0, absoluta.northing0) == (EASTING0, NORTHING0)

    local = load_georef(local_project, local_run)
    assert not local.is_absolute
    assert (local.easting0, local.northing0) == (0.0, 0.0), (
        "sin origen declarado NO se inventa un desplazamiento"
    )
    assert "local" in local.describe().lower()

    _, manifiesto = build_omf_project(utm_project, utm_run, include_surfaces=False)
    assert manifiesto["georeferenced"] is True
    assert manifiesto["vertical_datum"] is None, (
        "no hay datum vertical en el repo: declararlo sería inventarlo"
    )


@pytest.mark.integration
def test_rechaza_la_malla_no_reconstruible_en_vez_de_inventarla(run_local):
    """El caso medido: la tabla dispersa de la inversión conjunta."""
    project_id, run_id = run_local
    run_dir = PROJECTS_DIR / project_id / "runs" / run_id
    frame = pl.read_parquet(str(run_dir / "block_model.parquet"))
    frame.drop("ix", "iy", "iz").write_parquet(str(run_dir / "block_model.parquet"))

    with pytest.raises(OmfExportError) as error:
        export_run_to_omf(project_id, run_id, include_surfaces=False)
    assert "ix" in str(error.value) and "invent" in str(error.value).lower()


@pytest.mark.integration
def test_sin_inputs_json_no_se_adivina_la_malla(run_local):
    project_id, run_id = run_local
    (PROJECTS_DIR / project_id / "runs" / run_id / "inputs.json").unlink()

    with pytest.raises(OmfExportError) as error:
        export_run_to_omf(project_id, run_id, include_surfaces=False)
    assert "inputs.json" in str(error.value)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Ida y vuelta de sondajes
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_ida_y_vuelta_de_sondajes_devuelve_el_intervalo_original(run_local):
    project_id, run_id = run_local
    payload, _, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)

    resultado = import_omf_boreholes(payload, surface_z=0.0)
    originales = json.loads(
        (PROJECTS_DIR / project_id / "runs" / run_id / "boreholes.json").read_text(encoding="utf-8")
    )
    assert len(resultado.survey.holes) == len(originales)

    reconstruido = sorted(
        [(h.x_m, h.z_m, h.depth_from_m, h.depth_to_m, h.density_t_m3, h.lithology)
         for h in resultado.survey.holes]
    )
    esperado = sorted(
        [(o["x_m"], o["z_m"], o["y_from_m"], o["y_to_m"], o["density_t_m3"], o["lithology"])
         for o in originales]
    )
    assert reconstruido == esperado, "la ida y vuelta perdió o alteró un intervalo"

    intervalos = resultado.survey.to_intervals()
    assert len(intervalos) == len(originales), "el survey importado alimenta el solver"


@pytest.mark.integration
def test_sin_datum_declarado_la_profundidad_cambia_y_se_avisa(run_local):
    """El parámetro `surface_z` no es decorativo: cambia el resultado y se declara."""
    project_id, run_id = run_local
    payload, _, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)

    con_datum = import_omf_boreholes(payload, surface_z=0.0)
    sin_datum = import_omf_boreholes(payload)

    profundidades_con = sorted(h.depth_from_m for h in con_datum.survey.holes)
    profundidades_sin = sorted(h.depth_from_m for h in sin_datum.survey.holes)
    assert profundidades_con != profundidades_sin
    assert any("collar" in aviso.lower() for aviso in sin_datum.warnings), (
        "medir desde el collar sin decirlo sería un desplazamiento silencioso"
    )


@pytest.mark.integration
def test_un_sondaje_desviado_se_descarta_y_se_nombra(tmp_path):
    """No se aplasta a vertical: se descarta y se dice cuál."""
    import omf

    vertices = np.array([[0.0, 0.0, 0.0], [50.0, 50.0, -100.0]])   # 70 m de desviación
    proyecto = omf.Project(name="desviado", elements=[omf.LineSetElement(
        name="BH-desviado",
        geometry=omf.LineSetGeometry(vertices=vertices, segments=np.array([[0, 1]])),
        data=[omf.ScalarData(name="density", array=np.array([2.9]), location="segments")],
    )])
    destino = tmp_path / "desviado.omf"
    omf.OMFWriter(proyecto, str(destino))

    resultado = import_omf_boreholes(destino.read_bytes())

    assert resultado.stats["deviated_holes"] == 1
    assert resultado.survey.holes == []
    assert any("BH-desviado" in aviso for aviso in resultado.warnings)


@pytest.mark.integration
def test_el_inventario_declara_lo_que_no_consume(run_local):
    """Lo que TerraQuantum no usa se lista, no se finge usar."""
    project_id, run_id = run_local
    payload, _, _ = export_run_to_omf(project_id, run_id, include_surfaces=False)

    resultado = import_omf_boreholes(payload, surface_z=0.0)
    por_tipo = {item.kind: item for item in resultado.inventory}

    assert por_tipo["VolumeElement"].consumed is False
    assert "todavia no consume" in por_tipo["VolumeElement"].note
    assert por_tipo["VolumeElement"].n_primitives == NX * NY * NZ
    assert por_tipo["LineSetElement"].consumed is True
    assert resultado.stats["bounds_raw"] is not None, (
        "la caja envolvente se publica siempre: es lo que deja ver si venía en UTM"
    )


@pytest.mark.integration
def test_leer_un_omf_no_deja_el_fichero_abierto(tmp_path):
    """Regresión del gotcha de Windows: `OMFReader` sobre una RUTA no cierra nunca.

    Con el descriptor abierto, borrar el temporal revienta con WinError 32 y un
    422 limpio se convertía en 500. Se comprueba que un fichero inválido produce
    el error de dominio y que el temporal queda limpio.
    """
    from services.omf_import_service import OmfImportError, read_omf_project

    antes = {p.name for p in pathlib.Path(tempfile_gettempdir()).glob("tq_omf_in_*")}
    with pytest.raises(OmfImportError):
        read_omf_project(b"esto no es un omf en absoluto")
    despues = {p.name for p in pathlib.Path(tempfile_gettempdir()).glob("tq_omf_in_*")}
    assert despues <= antes, "quedó un directorio temporal sin limpiar"


def tempfile_gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()


# ═════════════════════════════════════════════════════════════════════════════
# 6. Defectos MEDIDOS por esta fase, pinchados donde están
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_defecto_h_f12_1_cerrado_el_bundle_zip_permuta_los_ejes():
    """H-F12-1 — CERRADO por la FASE 19 (2026-08-26). Era un test-trampa.

    La Fase 12 midió que `gravity_import_service` escribía `model.msh` en el
    run_dir CON la permutación (nE, nN, nZ) = (nx, nz, ny) y que el bundle ZIP
    regeneraba un `model.msh` con el MISMO nombre SIN permutar: sobre una corrida
    real (nx=20, ny=10, nz=20) el fichero del disco decía «20 20 10» y el del ZIP
    «20 10 20». La Fase 12 no lo corrigió —tocar el bundle industrial no era su
    alcance— y dejó este test PINCHANDO el defecto, con el encargo explícito de
    que quien lo arreglara lo actualizara en vez de arreglarlo de tapadillo.

    Esto es ese cambio. El gate completo —las dos rutas byte a byte, el modelo, el
    origen, GSLIB y ASEG— vive en `tests/test_fase19_zip_ubc_ejes.py`.
    """
    from services.export_service import _ubc_msh_text

    nx, ny, nz = 20, 10, 20      # ny es la PROFUNDIDAD
    primera_linea = _ubc_msh_text(nx, ny, nz, 100.0).splitlines()[0]

    assert primera_linea == f"{nx} {nz} {ny}", (
        "el orden UBC correcto es (nE, nN, nZ) = (nx, nz, ny), el mismo que hace "
        "gravity_import_service al exportar desde load-package"
    )
    assert primera_linea != f"{nx} {ny} {nz}", "H-F12-1 ha vuelto"


@pytest.mark.unit
def test_defecto_h_f12_2_omfvista_lee_las_celdas_transpuestas():
    """H-F12-2 — el lector de PyVista discrepa de la especificación de GMG.

    GMG documenta para el modelo de bloques: «Ordering increases U first, then V,
    then W». `omfvista.volume_to_vtk` hace `np.reshape(arr, (nu,nv,nw))` en orden
    C —que interpreta W como índice rápido— y luego `.flatten(order="F")`. Es una
    transposición respecto de la especificación.

    TerraQuantum escribe según la ESPECIFICACIÓN. Este test deja constancia
    ejecutable de que las dos lecturas dan resultados distintos, para que nadie
    "corrija" el exportador al ver el modelo raro en omfvista.
    """
    spec = OmfGridSpec(nx=NX, ny=NY, nz=NZ, block_size=BS)
    ix, iy, iz = np.mgrid[0:NX, 0:NY, 0:NZ]
    plano = np.array([
        _valor(a, b, c) for a, b, c in zip(
            ix.flatten(order="F"), iy.flatten(order="F"), iz.flatten(order="F"))
    ])
    escrito = permute_tq_grid_to_omf(plano, spec)

    segun_especificacion = escrito.reshape((NX, NZ, NY), order="F")
    segun_omfvista = escrito.reshape((NX, NZ, NY))            # orden C, como omfvista

    assert not np.array_equal(segun_especificacion, segun_omfvista), (
        "si ambas lecturas coincidieran, la malla de prueba sería demasiado "
        "simétrica para detectar la discrepancia y el test no probaría nada"
    )
