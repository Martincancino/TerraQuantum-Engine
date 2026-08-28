"""
FASE 22 — Las unidades de la exportación dejan de mentir · backend · ACAD-12, ACAD-13.
=====================================================================================

Dos defectos con la misma firma —el fichero de salida dice una cosa y contiene otra—
y ambos nacidos de un cambio cosmético que nadie volvió a medir.

**ACAD-12.** `TargetingEngine.extract_and_export` calcula `volumen · densidad`, que en
m³ × t/m³ da **toneladas**, y lo exportaba en una columna llamada `bulk_rock_mass_kg`:
factor 1.000 entre el nombre y el valor. El renombrado que lo creó está documentado en
el propio código como «compliance-safe» (Fase 7).

**ACAD-13.** El contraste de densidad de la exportación se restaba contra el literal
`2.6` mientras el motor invierte contra `base_density`, un parámetro de contrato con
rango 1,0–6,0 t/m³ (`schemas/geophysics_schema.py:782`).

Lo que estos tests fijan, y que las fichas del plan no decían:

  · **ACAD-13 estaba en TRES escritores**, no en uno. Además del `.vtr`
    (`export_service.VTK_BASE_DENSITY`) estaban `exploration/gravimetry.py:4213`
    (`density_contrast = density - 2.6`) y —el más grave— el `Density_Contrast` del
    **ASEG-GDF2**, que es formato de ENTREGA REGULATORIA en Australia/NZ y cuyo `.dfn`
    declaraba por escrito «Density minus 2.6 g/cm3 base». Los tres viajan al cliente
    dentro del ZIP industrial (`model.vtr`, `model.dat`), copiados del disco sin
    regenerarse. Un cuarto sitio repetía la mentira en prosa: la nota del bloque
    `vtk_export` del reporte.

  · **ACAD-12 no era sólo la unidad.** La llamada de producción no pasaba `block_size`,
    así que la firma caía en su default de **10 m** y el volumen de celda quedaba fijo
    en 1.000 m³ — medido sobre `data/projects`: **1.034 de 2.089 corridas** usan un dx
    distinto de 10, hasta 8.315 m. Encima había un tope silencioso
    (`MAX_BLOCK_VOLUME_M3 = 1_000_000`) que recortaba el volumen sin decirlo. Renombrar
    la columna a toneladas y dejar el volumen mal habría cerrado el factor 1.000 y
    dejado vivo uno de hasta 10⁹.

  · **Nadie consume la columna.** Grep sobre el monorepo entero (backend, frontend,
    scripts de validación, notebooks, docs): cero lectores de `bulk_rock_mass_kg`. Por
    eso se RENOMBRA en vez de multiplicar — y con la palabra que el repositorio ya
    eligió cuando resolvió este mismo defecto en la ruta canónica (commit `d424c7c`:
    `modeled_rock_mass_kg` → `modeled_rock_mass_tonnes`).

Gate del plan: *«un test que invierte con `base_density ≠ 2.6` y exige que la columna
exportada coincida con la que consume el frontend (`density_contrast_t_m3`)»*. Está en
`test_e2e_el_vtr_del_disco_coincide_con_la_columna_que_pinta_el_frontend`, y no afirma
sobre arrays en memoria: **parsea el `.vtr` que queda escrito en disco**, que es el
fichero que el cliente abre en ParaView.
"""
from __future__ import annotations

import math
import os
import re
import struct
import sys

import numpy as np
import polars as pl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_inversion

NX, NY, NZ, BLOCK = 6, 8, 6, 20.0

# La roca caja del caso de prueba. 4,5 t/m³ es magnetita masiva — el valor que el
# propio contrato pone de ejemplo (`geophysics_schema.py:782`) y el que usa la Fase 20.
# La distancia al literal es exactamente 1,9 t/m³: si un test pasa con 2,6 y con 4,5
# indistintamente, no está midiendo nada.
BASE_ALT = 4.5
LITERAL_VIEJO = 2.6


# ═════════════════════════════════════════════════════════════════════════════
# Builders
# ═════════════════════════════════════════════════════════════════════════════

def _gravity_input(*, base_density=None, run_id="f22") -> GeophysicsInvertInput:
    """Input gravimétrico pequeño con un cuerpo compacto sintético (contraste +0,8).

    Copiado a propósito del harness de la Fase 20 (`test_f20_effective_contrast.py`):
    es el mismo mundo, así que si una de las dos fases se rompe, se rompe contra el
    mismo problema y la comparación entre fichas sigue siendo legítima.
    """
    from exploration.gravimetry import GravimetryForward

    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    r = np.sqrt((x_c - NX * BLOCK / 2) ** 2 + (y_c - 70.0) ** 2 + (z_c - NZ * BLOCK / 2) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(
        np.arange(5, NX * BLOCK, BLOCK), np.arange(5, NZ * BLOCK, BLOCK), indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    params = GeophysicsInvertInput(
        project_id="pytest_f22", run_id=run_id,
        depth=int(NY * BLOCK), nir=83, fe=79, region="norte_chile",
        lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BLOCK), cutoff_radius=int(NX * BLOCK * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
    )
    if base_density is not None:
        # `density_min`/`density_max` se mueven CON la base: mover sólo la base deja el
        # bound desacoplado (Fase 20) y recorta el modelo entero contra el piso, lo que
        # haría el contraste constante y el test tautológico.
        params = params.model_copy(update={
            "base_density": base_density,
            "density_min": base_density - 1.0,
            "density_max": base_density + 1.0,
        })
    return params


def _vtr_cell_array(vtr_path: str, name: str) -> np.ndarray:
    """Lee un CellData array del `.vtr` REAL en disco. Sin pyevtk, sin VTK.

    El gate exige afirmar sobre el fichero que se entrega, no sobre lo que una función
    devolvió en memoria: entre las dos cosas está justo el código que esta fase tocó.
    Formato: VTKFile XML con `header_type="UInt64"` y `<AppendedData encoding="raw">`;
    cada array va precedido de su tamaño en bytes (uint64 little-endian) en el offset
    que declara su `<DataArray ... offset="N"/>`.
    """
    raw = open(vtr_path, "rb").read()
    cabecera = raw[: raw.find(b"<AppendedData")].decode("ascii", errors="replace")

    m = re.search(
        r'<DataArray Name="%s"[^>]*?type="(?P<t>\w+)"[^>]*?offset="(?P<o>\d+)"' % re.escape(name),
        cabecera,
    )
    assert m, f"El .vtr no declara el array {name!r}. Cabecera:\n{cabecera}"
    dtype = {"Float64": np.float64, "Float32": np.float32, "Int32": np.int32}[m.group("t")]

    marca = raw.find(b"_", raw.find(b"<AppendedData"))
    inicio = marca + 1 + int(m.group("o"))
    n_bytes = struct.unpack("<Q", raw[inicio:inicio + 8])[0]
    return np.frombuffer(raw[inicio + 8: inicio + 8 + n_bytes], dtype=dtype)


# ═════════════════════════════════════════════════════════════════════════════
# 1. ACAD-13 — el contraste del .vtr deja de restar un literal
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("base", [2.6, 4.5, 1.9, 5.5])
def test_el_contraste_del_vtr_usa_la_base_de_la_corrida(base):
    """La resta se hace contra el argumento, no contra una constante del módulo."""
    from services.export_service import build_vtk_core_arrays

    nx, ny, nz = 2, 3, 4
    dens = np.linspace(2.0, 4.0, nx * ny * nz)

    _, _, _, data = build_vtk_core_arrays(
        nx=nx, ny=ny, nz=nz, dx=10.0,
        est_density=dens, sensitivity=np.zeros_like(dens), base_density=base,
    )
    obtenido = data["Density_Contrast_gcm3"].flatten(order="F")
    assert np.allclose(obtenido, dens - base, atol=1e-12)


def test_el_vtr_ya_no_puede_construirse_sin_declarar_la_base(tmp_path):
    """`base_density` es obligatorio a propósito: un default aquí es un sesgo mudo.

    Es la guardia estructural de ACAD-13. Mientras hubiera un valor por omisión, un
    llamador nuevo podía olvidarlo y obtener un fichero plausible y equivocado; ahora
    olvidarlo es un TypeError en el sitio de la llamada.
    """
    from services.export_service import build_vtk_core_arrays, export_core_to_vtr

    with pytest.raises(TypeError):
        build_vtk_core_arrays(                                       # type: ignore[call-arg]
            nx=1, ny=1, nz=1, dx=10.0,
            est_density=np.array([2.7]), sensitivity=np.array([0.0]),
        )
    # `output_dir` va a un temporal, no a `.`: si la guardia se rompe (o se muta para
    # comprobar que este test la defiende), la llamada tiene éxito y ESCRIBE un .vtr.
    # Apuntando al repo, ese fichero se quedaba dentro de `terraquantum-backend/`.
    with pytest.raises(TypeError):
        export_core_to_vtr(                                          # type: ignore[call-arg]
            output_dir=str(tmp_path), run_prefix="x", nx=1, ny=1, nz=1, dx=10.0,
            est_density=np.array([2.7]), sensitivity=np.array([0.0]),
        )


def test_el_modulo_de_exportacion_ya_no_expone_una_densidad_base():
    """La constante se borró, no se corrigió: no queda dónde volver a agarrarla."""
    import services.export_service as export_service

    assert not hasattr(export_service, "VTK_BASE_DENSITY")
    assert hasattr(export_service, "VTK_AIR_SENTINEL")     # el otro sentinel SÍ sigue


def test_las_celdas_de_aire_siguen_llevando_el_sentinel_y_no_la_resta():
    """El arreglo no debe filtrar `−base_density` a las celdas inactivas."""
    from services.export_service import build_vtk_core_arrays, VTK_AIR_SENTINEL

    dens = np.array([2.7, np.nan, 3.1, np.nan, 2.9, np.nan], dtype=float)
    _, _, _, data = build_vtk_core_arrays(
        nx=1, ny=2, nz=3, dx=10.0,
        est_density=dens, sensitivity=np.zeros(6), base_density=BASE_ALT,
    )
    dc = data["Density_Contrast_gcm3"].flatten(order="F")
    ia = data["Is_Active"].flatten(order="F")
    assert np.all(dc[ia == 0] == float(VTK_AIR_SENTINEL))
    assert np.allclose(dc[ia == 1], dens[np.isfinite(dens)] - BASE_ALT)


# ═════════════════════════════════════════════════════════════════════════════
# 2. GATE DEL PLAN — corrida real con base ≠ 2.6, contra el fichero del disco
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_e2e_el_vtr_del_disco_coincide_con_la_columna_que_pinta_el_frontend():
    """GATE — el gate literal de la Fase 22, sobre artefactos reales.

    Se invierte con `base_density = 4.5`, se abre el `.vtr` QUE QUEDÓ EN DISCO (el que
    el ZIP industrial copia como `model.vtr`) y se compara celda a celda contra
    `density_contrast_t_m3` del parquet — la columna que lee
    `lib/terraquantum/frontendApi.ts:2104` para pintar el 3D.

    Antes de esta fase divergían en 1,9 t/m³ constantes: la pantalla y el fichero
    entregado describían dos cuerpos distintos.
    """
    pytest.importorskip("pyevtk", reason="sin pyevtk no se escribe .vtr (ruta non-fatal)")

    res = run_geophysics_inversion(_gravity_input(base_density=BASE_ALT, run_id="f22_e2e"))
    report = res["report"]

    vtr_path = (report.get("vtk_export") or {}).get("vtr_path")
    assert vtr_path and os.path.exists(vtr_path), "la corrida no dejó .vtr en disco"

    df = pl.read_parquet(report["blockModelPath"])
    contraste_parquet = df["density_contrast_t_m3"].to_numpy().astype(float)

    contraste_vtr = _vtr_cell_array(vtr_path, "Density_Contrast_gcm3")
    activo_vtr = _vtr_cell_array(vtr_path, "Is_Active").astype(bool)

    assert contraste_vtr.size == contraste_parquet.size, (
        "el .vtr y el parquet no describen el mismo número de celdas"
    )

    vivas = activo_vtr & np.isfinite(contraste_parquet)
    assert vivas.sum() > 0, "no quedó ninguna celda activa que comparar"

    # LA AFIRMACIÓN DE LA FASE: mismo número en el fichero y en la pantalla.
    assert np.allclose(contraste_vtr[vivas], contraste_parquet[vivas], atol=1e-9)

    # Y que el caso NO sea trivial: con el literal viejo la diferencia sería 1,9 t/m³.
    # Sin esto, un test que pasara por casualidad con base=2.6 se leería como gate.
    densidad = df["density"].to_numpy().astype(float)
    con_literal = densidad[vivas] - LITERAL_VIEJO
    assert not np.allclose(contraste_vtr[vivas], con_literal, atol=1e-3)
    assert np.allclose(np.median(con_literal - contraste_vtr[vivas]),
                       BASE_ALT - LITERAL_VIEJO, atol=1e-6)


@pytest.mark.integration
def test_e2e_el_reporte_declara_la_base_con_la_que_se_calculo_el_vtr():
    """La nota del bloque `vtk_export` decía «Densidad base: 2.6 g/cm³» como texto fijo.

    Era la mentira derivada: aun con el `.vtr` corregido, el reporte seguía diciéndole
    al usuario contra qué NO se había calculado.
    """
    res = run_geophysics_inversion(_gravity_input(base_density=BASE_ALT, run_id="f22_nota"))
    vtk = res["report"]["vtk_export"]

    assert vtk["base_density_t_m3"] == pytest.approx(BASE_ALT)
    assert "4.5" in vtk["note"]
    assert "2.6" not in vtk["note"]


# ═════════════════════════════════════════════════════════════════════════════
# 3. ACAD-13 en el ASEG-GDF2 — el sitio que ninguna ficha nombraba
# ═════════════════════════════════════════════════════════════════════════════

def _columnas_dat(texto: str) -> np.ndarray:
    """Filas de datos del .dat (las que no empiezan por `!`), como matriz de floats."""
    filas = [l.split() for l in texto.splitlines() if l and not l.startswith("!")]
    return np.array([[float(v) for v in f] for f in filas], dtype=float)


def test_el_aseg_gdf2_resta_la_base_de_la_corrida():
    """`Density_Contrast` del .dat es densidad absoluta menos la base declarada."""
    from services.export_service import _aseg_gdf2_dat_text

    dens = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]
    filas = _columnas_dat(_aseg_gdf2_dat_text(dens, 2, 2, 2, 25.0, base_density=BASE_ALT))

    absoluta, contraste = filas[:, 3], filas[:, 4]
    assert np.allclose(absoluta, dens, atol=1e-6)
    assert np.allclose(contraste, np.array(dens) - BASE_ALT, atol=1e-6)
    # Y no contra el literal viejo.
    assert not np.allclose(contraste, np.array(dens) - LITERAL_VIEJO, atol=1e-3)


def test_la_definicion_aseg_declara_la_misma_base_que_usa_el_dato():
    """ASEG-GDF2 es entrega regulatoria: el `.dfn` DEFINE el `.dat`.

    Declarar una base que no es la usada no es un número feo, es un fichero incorrecto
    por contrato. Se comprueban las dos mitades juntas para que no puedan divergir.
    """
    from services.export_service import _aseg_gdf2_dat_text, _aseg_gdf2_dfn_text

    dfn = _aseg_gdf2_dfn_text(2, 2, 2, 25.0, "19S", base_density=BASE_ALT)
    assert "4.5" in dfn
    assert "minus 2.6" not in dfn

    dat = _aseg_gdf2_dat_text([3.0] * 8, 2, 2, 2, 25.0, base_density=BASE_ALT)
    assert "4.5" in dat.splitlines()[3]          # la cabecera `!` lo dice también
    assert np.allclose(_columnas_dat(dat)[:, 4], 3.0 - BASE_ALT, atol=1e-6)


def test_el_aseg_marca_nodata_sin_restarle_la_base():
    """Una celda de aire sale como NODATA en las dos columnas, no como −4,5."""
    from services.export_service import _aseg_gdf2_dat_text

    filas = _columnas_dat(_aseg_gdf2_dat_text(
        [2.9, float("nan")], 2, 1, 1, 10.0, base_density=BASE_ALT))
    assert filas[1, 3] == pytest.approx(-9999.0)
    assert filas[1, 4] == pytest.approx(-9999.0)


# ═════════════════════════════════════════════════════════════════════════════
# 4. El ZIP industrial: de dónde saca la base, y qué declara cuando no la tiene
# ═════════════════════════════════════════════════════════════════════════════

def test_la_base_se_lee_del_reporte_antes_que_de_los_inputs():
    """Orden de fuentes, y que cada una se NOMBRE en el resultado."""
    from services.export_service import base_density_of_run

    assert base_density_of_run({"base_density": 3.0},
                               {"effective_contrast": {"base_density": BASE_ALT}}) == \
        (BASE_ALT, "report.effective_contrast")
    assert base_density_of_run({"base_density": 3.0}, None) == (3.0, "inputs.json")
    assert base_density_of_run({}, {}) == (2.6, "contract_default_assumed")


def test_una_base_no_numerica_no_se_cuela_como_valor():
    """`None`, texto o NaN en disco no deben convertirse en una base silenciosa."""
    from services.export_service import base_density_of_run

    for basura in (None, "4.5", float("nan"), True):
        valor, fuente = base_density_of_run(
            {}, {"effective_contrast": {"base_density": basura}})
        assert (valor, fuente) == (2.6, "contract_default_assumed"), basura


def test_los_escritores_aseg_exigen_la_base_no_la_suponen():
    """Ninguno de los dos tiene default, y el motivo está MEDIDO.

    La primera versión de esta fase les dejó `base_density = 2.6` por omisión. La
    mutación «el bundle deja de pasar la base al .dat» ESCAPÓ al gate: el `.dat` volvía
    al literal y ningún test se enteraba, porque todos llamaban a la función directamente
    con el argumento puesto. El default era el defecto esperando un kwarg olvidado.
    """
    from services.export_service import _aseg_gdf2_dat_text, _aseg_gdf2_dfn_text

    with pytest.raises(TypeError):
        _aseg_gdf2_dat_text([2.7], 1, 1, 1, 10.0)          # type: ignore[call-arg]
    with pytest.raises(TypeError):
        _aseg_gdf2_dfn_text(1, 1, 1, 10.0, "19S")          # type: ignore[call-arg]


@pytest.mark.integration
def test_el_zip_industrial_entrega_el_contraste_contra_la_base_de_la_corrida(tmp_path,
                                                                             monkeypatch):
    """GATE del entregable — se arma el ZIP REAL y se leen sus ficheros.

    Los tests de arriba llaman a los escritores uno a uno, con el argumento en la mano;
    ninguno veía si `create_run_bundle_zip` se lo pasa. Éste sí: monta una corrida en
    disco cuyo `report.json` declara `base_density = 4.5`, arma el bundle y comprueba
    que `model.dat`, su definición `model.dfn` y el `manifest.json` cuentan los tres la
    misma historia.
    """
    import json
    import zipfile

    import services.block_model_store as store
    from core.config import RUN_BLOCK_MODEL_FILENAME

    proyectos = tmp_path / "projects"
    monkeypatch.setattr(store, "PROJECTS_DIR", proyectos)

    nx, ny, nz, bs = 2, 2, 2, 25.0
    dens = np.array([2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5], dtype=float)

    run_dir = proyectos / "p_f22" / "runs" / "r_f22"
    run_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"density": dens}).write_parquet(str(run_dir / RUN_BLOCK_MODEL_FILENAME))
    (run_dir / "inputs.json").write_text(
        json.dumps({"nx": nx, "ny": ny, "nz": nz, "block_size": bs}), encoding="utf-8")
    (run_dir / "report.json").write_text(
        json.dumps({"effective_contrast": {"base_density": BASE_ALT}}), encoding="utf-8")

    from services.export_service import create_run_bundle_zip

    payload, _ = create_run_bundle_zip("p_f22", "r_f22")
    with zipfile.ZipFile(__import__("io").BytesIO(payload)) as zf:
        dat = zf.read("model.dat").decode("utf-8")
        dfn = zf.read("model.dfn").decode("utf-8")
        man = json.loads(zf.read("manifest.json").decode("utf-8"))

    contraste = _columnas_dat(dat)[:, 4]
    assert np.allclose(sorted(contraste), sorted(dens - BASE_ALT), atol=1e-6)
    assert not np.allclose(sorted(contraste), sorted(dens - LITERAL_VIEJO), atol=1e-3)

    assert "4.5" in dfn and "minus 2.6" not in dfn
    assert man["density_reference"]["base_density_t_m3"] == pytest.approx(BASE_ALT)
    assert man["density_reference"]["source"] == "report.effective_contrast"


def test_el_manifiesto_declara_la_referencia_del_contraste():
    """Un contraste sin su referencia es media resta. El manifiesto la publica, y
    publica también de DÓNDE salió: `contract_default_assumed` avisa de que en esa
    corrida el dato no estaba en disco."""
    from services.export_service import _build_bundle_manifest

    man = _build_bundle_manifest(
        "p", "r", {"nx": 2, "ny": 2, "nz": 2},
        {"effective_contrast": {"base_density": BASE_ALT}}, "hash")
    ref = man["density_reference"]
    assert ref["base_density_t_m3"] == pytest.approx(BASE_ALT)
    assert ref["source"] == "report.effective_contrast"
    assert "model.vtr:Density_Contrast_gcm3" in ref["applies_to"]

    viejo = _build_bundle_manifest("p", "r", {}, None, "hash")
    assert viejo["density_reference"]["source"] == "contract_default_assumed"
    assert viejo["density_reference"]["base_density_t_m3"] == pytest.approx(2.6)


# ═════════════════════════════════════════════════════════════════════════════
# 5. ACAD-12 — la masa: la unidad del nombre y el volumen de la celda
# ═════════════════════════════════════════════════════════════════════════════

def _exportar(tmp_path, *, block_size, base_density, densidad):
    """Corre el exportador del TargetingEngine y devuelve el parquet COMPLETO."""
    from exploration.gravimetry import TargetingEngine

    n = len(densidad)
    ix = np.arange(n, dtype=np.int32)
    ceros = np.zeros(n, dtype=np.int32)
    coord = ix.astype(float) * block_size + block_size / 2

    destino = str(tmp_path / "bm.parquet")
    TargetingEngine.extract_and_export(
        coord, coord * 0.0, coord * 0.0,
        np.asarray(densidad, dtype=float), np.full(n, 0.5),
        ix=ix, iy=ceros, iz=ceros,
        block_size=block_size, cutoff_density=0.0,
        export_path=destino, base_density=base_density,
    )
    return pl.read_parquet(destino)


def test_la_columna_de_masa_se_llama_en_la_unidad_que_lleva(tmp_path):
    """m³ × t/m³ = TONELADAS. La columna decía `_kg`."""
    df = _exportar(tmp_path, block_size=10.0, base_density=2.6, densidad=[2.7, 3.1])

    assert "bulk_rock_mass_tonnes" in df.columns
    assert "bulk_rock_mass_kg" not in df.columns, (
        "el nombre en kg volvió: la columna lleva toneladas"
    )
    assert df["bulk_rock_mass_tonnes"].to_list() == pytest.approx([2700.0, 3100.0])


def test_la_masa_usa_el_tamano_de_celda_de_la_corrida(tmp_path):
    """El volumen es dx³ de VERDAD, no los 1.000 m³ del default de 10 m.

    Con dx = 125 m —el `BLOCK` del harness de honestidad del repositorio— el volumen
    real es 1.953.125 m³. La versión anterior reportaba 1.000 m³: un factor 1.953.
    """
    df = _exportar(tmp_path, block_size=125.0, base_density=2.6, densidad=[2.7])
    assert df["bulk_rock_mass_tonnes"][0] == pytest.approx(125.0 ** 3 * 2.7)


def test_no_queda_tope_silencioso_de_volumen(tmp_path):
    """`MAX_BLOCK_VOLUME_M3 = 1_000_000` recortaba toda celda de más de 100 m sin
    decirlo. Con dx = 520 m (292 corridas reales en disco) el tope declaraba 1e6 m³
    donde la celda mide 1,4e8."""
    df = _exportar(tmp_path, block_size=520.0, base_density=2.6, densidad=[3.0])
    esperado = 520.0 ** 3 * 3.0
    assert df["bulk_rock_mass_tonnes"][0] == pytest.approx(esperado)
    assert df["bulk_rock_mass_tonnes"][0] > 1_000_000 * 3.0 * 100      # ni cerca del tope


def test_la_masa_coincide_con_la_columna_canonica_del_producto(tmp_path):
    """Las DOS columnas de masa de TerraQuantum deben dar el mismo número.

    `modeled_rock_mass_tonnes` (ruta canónica, la que alimenta el reporte) usa
    `dx*dx*dx` sin tope. Que ésta coincida es lo que convierte el renombrado en una
    corrección y no en un cambio de etiqueta: mismo nombre de unidad, mismo valor.
    """
    from services.inversion_postprocess_service import build_full_block_model_dataframe

    # `build_full_block_model_dataframe` toma el dx de `params.block_size`, así que el
    # de la comparación es el del harness (BLOCK), no un número suelto.
    dx, dens = BLOCK, np.array([2.7, 3.4, 2.9], dtype=float)
    n = len(dens)
    ix = np.arange(n, dtype=np.int32)
    ceros = np.zeros(n, dtype=np.int32)
    coord = ix.astype(float) * dx + dx / 2

    canonico = build_full_block_model_dataframe(
        params=_gravity_input(run_id="f22_masa"),
        ix=ix, iy=ceros, iz=ceros,
        x_c=coord, y_c=coord * 0.0, z_c=coord * 0.0,
        est_density=dens, probability=np.full(n, 0.5),
        base_density=2.6, cutoff_density=2.75,
    )
    targeting = _exportar(tmp_path, block_size=dx, base_density=2.6, densidad=dens)

    assert targeting["bulk_rock_mass_tonnes"].to_numpy() == pytest.approx(
        canonico["modeled_rock_mass_tonnes"].to_numpy()
    )


@pytest.mark.parametrize("base", [2.6, 4.5])
def test_el_contraste_del_targeting_tambien_deja_de_restar_el_literal(tmp_path, base):
    """ACAD-13 en el tercer escritor: `density_contrast = density - 2.6`."""
    dens = [2.7, 3.1, 4.9]
    df = _exportar(tmp_path, block_size=10.0, base_density=base, densidad=dens)
    assert df["density_contrast"].to_numpy() == pytest.approx(np.array(dens) - base)


@pytest.mark.integration
def test_e2e_produccion_pasa_la_malla_y_la_base_reales_al_targeting(monkeypatch):
    """La firma admitía los cuatro argumentos; la llamada de producción no los pasaba.

    Se espía la llamada REAL durante una inversión: sin esto, los tests de arriba
    seguirían verdes con la producción cayendo en `block_size=10.0` y `base_density=2.6`
    — que es exactamente el estado que esta fase corrige.
    """
    import exploration.gravimetry as gravimetry

    visto: dict = {}
    original = gravimetry.TargetingEngine.extract_and_export

    def espia(*args, **kwargs):
        visto.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(gravimetry.TargetingEngine, "extract_and_export",
                        staticmethod(espia))
    import services.geophysics_service as gs
    monkeypatch.setattr(gs.TargetingEngine, "extract_and_export", staticmethod(espia))

    run_geophysics_inversion(_gravity_input(base_density=BASE_ALT, run_id="f22_espia"))

    assert visto, "la exportación del TargetingEngine no llegó a ejecutarse"
    assert visto["block_size"] == pytest.approx(BLOCK)          # no 10.0
    assert visto["base_density"] == pytest.approx(BASE_ALT)     # no 2.6
    # Los índices llegan de la malla en vez de re-derivarse con floor(coord/10.0).
    for eje in ("ix", "iy", "iz"):
        assert visto[eje] is not None
    assert int(np.max(visto["ix"])) == NX - 1
    assert int(np.max(visto["iy"])) == NY - 1
    assert int(np.max(visto["iz"])) == NZ - 1


# ═════════════════════════════════════════════════════════════════════════════
# 6. Los fallbacks que fingían: densidad inventada y contraste servido como absoluto
# ═════════════════════════════════════════════════════════════════════════════

def test_sin_parquet_el_bundle_dice_no_hay_dato_y_no_inventa_roca(tmp_path):
    """Devolvía `[2.6] * n`: un modelo uniforme inventado que salía por `model.den`,
    `model.gslib` y `model.dat` con la misma cara que un resultado de inversión."""
    from services.export_service import _densities_from_parquet

    dens = _densities_from_parquet(tmp_path, 12)
    assert len(dens) == 12
    assert all(math.isnan(d) for d in dens)


def test_un_contraste_no_puede_entrar_por_el_hueco_de_la_densidad_absoluta(tmp_path):
    """`_densities_from_parquet` aceptaba `density_contrast` como si fuera densidad.

    De haberse alcanzado esa rama, el `.den`/`.gslib`/`Density_gcm3` habrían llevado un
    contraste rotulado como densidad absoluta — el mismo defecto de esta fase con el
    signo cambiado. Se comprueba que un parquet SIN `density` no produce números.
    """
    from services.export_service import _densities_from_parquet
    from core.config import RUN_BLOCK_MODEL_FILENAME

    pl.DataFrame({
        "density_contrast": [0.1, 0.2, 0.3, 0.4],
        "density_contrast_t_m3": [0.1, 0.2, 0.3, 0.4],
    }).write_parquet(str(tmp_path / RUN_BLOCK_MODEL_FILENAME))

    dens = _densities_from_parquet(tmp_path, 4)
    assert all(math.isnan(d) for d in dens), (
        "un contraste se está sirviendo como densidad absoluta"
    )


def test_el_parquet_con_densidad_sigue_leyendose_igual(tmp_path):
    """La rama viva (2.684 de 2.684 parquets en disco) no cambia de comportamiento."""
    from services.export_service import _densities_from_parquet
    from core.config import RUN_BLOCK_MODEL_FILENAME

    pl.DataFrame({"density": [2.7, 3.1, 2.9]}).write_parquet(
        str(tmp_path / RUN_BLOCK_MODEL_FILENAME))

    assert _densities_from_parquet(tmp_path, 3) == pytest.approx([2.7, 3.1, 2.9])
    # Y se rellena con NaN, no con roca, si la corrida declara más celdas que el parquet.
    largo = _densities_from_parquet(tmp_path, 5)
    assert largo[:3] == pytest.approx([2.7, 3.1, 2.9])
    assert all(math.isnan(d) for d in largo[3:])


# ═════════════════════════════════════════════════════════════════════════════
# 7. El snapshot de entradas: la base deja de faltar en el audit trail
# ═════════════════════════════════════════════════════════════════════════════

def test_el_snapshot_de_entradas_guarda_la_base_de_la_corrida():
    """0 de 2.089 `inputs.json` en disco traían `base_density`, y no porque nadie la
    moviera: la lista blanca de `build_run_inputs_snapshot` no la copiaba nunca."""
    from services.geophysics_service import build_run_inputs_snapshot

    snap = build_run_inputs_snapshot(_gravity_input(base_density=BASE_ALT,
                                                    run_id="f22_snap"))
    assert snap["base_density"] == pytest.approx(BASE_ALT)


def test_anadir_la_base_al_snapshot_no_movio_el_hash_de_configuracion():
    """`_AUDIT_KEYS` no incluye `base_density`, así que el `config_hash` de las corridas
    existentes NO cambia. (Que el hash de auditoría siga ciego a la roca caja es un
    hallazgo abierto de esta fase, declarado en el plan, no algo que arregle.)"""
    from services.export_service import _AUDIT_KEYS, _cfg_hash

    assert "base_density" not in _AUDIT_KEYS
    base = {"nx": 6, "ny": 8, "nz": 6, "block_size": 20}
    assert _cfg_hash(base) == _cfg_hash({**base, "base_density": BASE_ALT})
