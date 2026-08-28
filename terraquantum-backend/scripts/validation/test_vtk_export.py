"""
FASE 10 — Test de Exportación VTK Industrial
============================================

Valida que export_service.py genera correctamente un archivo .vtr
compatible con ParaView y Leapfrog, sin necesitar un servidor FastAPI.

Uso:
    cd terraquantum-backend
    python scripts/validation/test_vtk_export.py

Resultado esperado:
    ✅  3 pruebas PASS → .vtr generado en tmp/vtk_test/
    (Si pyevtk no está instalado → SKIP con instrucción de instalación)
"""

import sys
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

# ── Añadir raíz del backend al path (redundante con conftest.py, inofensivo) ─
_SCRIPT_DIR  = Path(__file__).resolve()
BACKEND_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"

_PYEVTK_AVAILABLE = False
try:
    from pyevtk.hl import gridToVTK  # noqa: F401
    _PYEVTK_AVAILABLE = True
except ImportError:
    try:
        from pyevtk.hl import rectilinearToVTK  # noqa: F401
        _PYEVTK_AVAILABLE = True
    except ImportError:
        pass

_pyevtk_required = pytest.mark.skipif(
    not _PYEVTK_AVAILABLE,
    reason="pyevtk no instalado — instala con: pip install pyevtk",
)


# ─────────────────────────────────────────────────────────────────────────────
def check_pyevtk():
    """True si alguna variante de pyevtk está disponible."""
    try:
        from pyevtk.hl import gridToVTK       # noqa: F401
        return True
    except ImportError:
        pass
    try:
        from pyevtk.hl import rectilinearToVTK  # noqa: F401
        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
def test_build_vtk_core_arrays():
    """Prueba la construcción de edges y data_dict desde arrays Core."""
    from services.export_service import build_vtk_core_arrays

    nx, ny, nz, dx = 4, 3, 5, 100.0  # 4×3×5 bloque, 100 m de celda
    n_core = nx * ny * nz

    # Densidades: mezcla de activos e inactivos (NaN = aire)
    rng = np.random.default_rng(42)
    density = np.full(n_core, 2.7)
    density[::3] = np.nan   # cada 3ra celda es aire
    sensitivity = rng.uniform(0.0, 1.0, n_core)

    # FASE 22 (ACAD-13): `base_density` ya no tiene default. Antes esta llamada lo
    # omitía y el contraste salía contra el literal 2.6 del módulo; el assert de más
    # abajo (≈ 0.1 = 2.7 − 2.6) pasaba en verde APOYÁNDOSE en el defecto. Declararlo
    # deja la dependencia a la vista: el 0.1 esperado es 2.7 − 2.6, no una constante.
    x_e, y_e, z_e, data_dict = build_vtk_core_arrays(
        nx=nx, ny=ny, nz=nz, dx=dx,
        est_density=density,
        sensitivity=sensitivity,
        base_density=2.6,
    )

    # ── Verificar edges ──────────────────────────────────────────────────────
    assert len(x_e) == nx + 1, f"x_edges len={len(x_e)}, esperado {nx+1}"
    assert len(y_e) == ny + 1, f"y_edges len={len(y_e)}, esperado {ny+1}"
    assert len(z_e) == nz + 1, f"z_edges len={len(z_e)}, esperado {nz+1}"

    assert np.isclose(x_e[0], 0.0),       "x_edges[0] debe ser 0.0"
    assert np.isclose(x_e[-1], nx * dx),  f"x_edges[-1] debe ser {nx*dx}"
    assert np.isclose(y_e[-1], ny * dx),  f"y_edges[-1] debe ser {ny*dx}"
    assert np.isclose(z_e[-1], nz * dx),  f"z_edges[-1] debe ser {nz*dx}"

    # ── Verificar data_dict ──────────────────────────────────────────────────
    assert "Density_Contrast_gcm3" in data_dict
    assert "Sensitivity_Proxy"     in data_dict
    assert "Is_Active"             in data_dict

    for key, arr in data_dict.items():
        assert arr.shape == (nx, ny, nz), f"{key}: shape {arr.shape} ≠ ({nx},{ny},{nz})"

    # ── Verificar valores ────────────────────────────────────────────────────
    dc   = data_dict["Density_Contrast_gcm3"]
    ia   = data_dict["Is_Active"]
    sens = data_dict["Sensitivity_Proxy"]

    # Celdas activas deben tener contraste ≈ 0.1 (2.7 - 2.6)
    active_mask_3d = ia == 1
    active_contrasts = dc[active_mask_3d]
    assert np.allclose(active_contrasts, 0.1, atol=1e-9), (
        f"Contraste activo esperado ≈ 0.1, obtenido: {active_contrasts[:5]}"
    )

    # Celdas de aire deben tener sentinel -9999.0
    air_contrasts = dc[ia == 0]
    assert np.all(air_contrasts == -9999.0), "Celdas de aire deben ser -9999.0"

    # Sensibilidad de aire debe ser 0
    assert np.all(sens[ia == 0] == 0.0), "Sensibilidad de celdas de aire debe ser 0.0"

    print(f"  {PASS} build_vtk_core_arrays: edges OK, shapes OK, valores OK")


# ─────────────────────────────────────────────────────────────────────────────
@_pyevtk_required
def test_export_block_model_to_vtr(tmp_dir: str):
    """Prueba la escritura del archivo .vtr con pyevtk."""
    from services.export_service import build_vtk_core_arrays, export_block_model_to_vtr

    nx, ny, nz, dx = 8, 6, 10, 50.0
    n_core = nx * ny * nz

    rng = np.random.default_rng(7)
    # Bloque sintético: anomalía densa en el centro
    density = rng.uniform(2.55, 3.2, n_core)
    # Aire en el borde superior (iz=9, iy=0..ny-1, ix=0..nx-1)
    ix_arr = np.tile(np.arange(nx), ny * nz)
    iy_arr = np.repeat(np.tile(np.arange(ny), nz), nx)
    iz_arr = np.repeat(np.arange(nz), nx * ny)
    air_mask = iz_arr == (nz - 1)
    density[air_mask] = np.nan

    sensitivity = np.clip(1.0 - iz_arr / nz, 0.0, 1.0) * rng.uniform(0.8, 1.0, n_core)

    x_e, y_e, z_e, data_dict = build_vtk_core_arrays(
        nx=nx, ny=ny, nz=nz, dx=dx,
        est_density=density,
        sensitivity=sensitivity,
        base_density=2.6,       # FASE 22: obligatorio, ver test_build_vtk_core_arrays
    )

    filename_prefix = str(Path(tmp_dir) / "block_model_core")
    vtr_path = export_block_model_to_vtr(
        filename_prefix=filename_prefix,
        x_edges=x_e,
        y_edges=y_e,
        z_edges=z_e,
        data_dict=data_dict,
    )

    assert vtr_path is not None, "vtr_path no debe ser None"
    assert vtr_path.endswith(".vtr"), f"Extensión incorrecta: {vtr_path}"
    assert Path(vtr_path).exists(), f"Archivo no creado: {vtr_path}"

    size_bytes = Path(vtr_path).stat().st_size
    assert size_bytes > 100, f"Archivo demasiado pequeño: {size_bytes} bytes"

    print(f"  {PASS} export_block_model_to_vtr: archivo={Path(vtr_path).name} | size={size_bytes/1024:.1f} KB")
    print(f"         Ruta completa: {vtr_path}")


# ─────────────────────────────────────────────────────────────────────────────
@_pyevtk_required
def test_export_core_to_vtr_pipeline(tmp_dir: str):
    """Prueba el pipeline completo de alto nivel export_core_to_vtr."""
    from services.export_service import export_core_to_vtr

    # Parámetros Demo Industrial v1: 32×20×32, blockSize=1552 m
    nx, ny, nz, dx = 32, 20, 32, 1552.0
    n_core = nx * ny * nz

    rng = np.random.default_rng(99)
    # Depósito Cu porfídico sintético: anomalía de alta densidad en iy=5..14
    density = np.full(n_core, 2.65)
    ix_arr = np.tile(np.arange(nx), ny * nz)
    iy_arr = np.repeat(np.tile(np.arange(ny), nz), nx)
    iz_arr = np.repeat(np.arange(nz), nx * ny)

    # Zona de depósito: densidad alta
    deposit = (
        (ix_arr >= 12) & (ix_arr <= 20) &
        (iy_arr >= 5)  & (iy_arr <= 14) &
        (iz_arr >= 10) & (iz_arr <= 22)
    )
    density[deposit] = rng.uniform(2.85, 3.4, deposit.sum())
    # Aire en la capa más superficial (iy=0, y=0..ny*dx)
    air = iy_arr == 0
    density[air] = np.nan

    sensitivity = np.clip(
        np.exp(-iy_arr / ny) * rng.uniform(0.7, 1.0, n_core),
        0.0, 1.0
    )

    vtr_path = export_core_to_vtr(
        output_dir=tmp_dir,
        run_prefix="block_model_core_demo_v1",
        nx=nx, ny=ny, nz=nz, dx=dx,
        est_density=density,
        sensitivity=sensitivity,
        base_density=2.6,       # FASE 22: obligatorio, ver test_build_vtk_core_arrays
    )

    assert vtr_path is not None, "Pipeline devolvió None — ¿pyevtk instalado?"
    assert Path(vtr_path).exists(), f"Archivo no encontrado: {vtr_path}"

    size_mb = Path(vtr_path).stat().st_size / (1024 * 1024)
    active_count = int(np.isfinite(density).sum())
    air_count    = int((~np.isfinite(density)).sum())

    print(f"  {PASS} export_core_to_vtr (Demo v1): {nx}×{ny}×{nz} | dx={dx}m")
    print(f"         Vóxeles activos={active_count:,} | aire={air_count:,}")
    print(f"         Archivo: {Path(vtr_path).name} | {size_mb:.2f} MB")
    print(f"         Ruta completa: {vtr_path}")
    print()
    print("  ParaView: File > Open -> selecciona el .vtr")
    print("            Filters > Common > Threshold -> Is_Active = [1, 1]")
    print("            Color by: Density_Contrast_gcm3")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("FASE 10 - Test Exportacion VTK Industrial (TerraQuantum)")
    print("=" * 65)
    print()

    if not check_pyevtk():
        print(f"{SKIP} pyevtk no está instalado.")
        print()
        print("  Instala con:")
        print("    pip install pyevtk")
        print()
        print("  Luego vuelve a ejecutar este script.")
        print()
        # Las pruebas de build_vtk_core_arrays no dependen de pyevtk
        print("  Ejecutando pruebas que no requieren pyevtk...")
        print()

    tmp_dir = str(BACKEND_ROOT / "tmp" / "vtk_test")
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    results = []

    # Prueba 1: sin pyevtk (solo arrays)
    print(">> Prueba 1: build_vtk_core_arrays (sin pyevtk)")
    try:
        test_build_vtk_core_arrays()
        results.append(("build_vtk_core_arrays", True))
    except Exception as exc:
        print(f"  {FAIL}: {exc}")
        results.append(("build_vtk_core_arrays", False))

    if check_pyevtk():
        # Prueba 2: escritura real de .vtr
        print()
        print(">> Prueba 2: export_block_model_to_vtr (escritura .vtr)")
        try:
            test_export_block_model_to_vtr(tmp_dir)
            results.append(("export_block_model_to_vtr", True))
        except Exception as exc:
            print(f"  {FAIL}: {exc}")
            results.append(("export_block_model_to_vtr", False))

        # Prueba 3: pipeline completo Demo v1
        print()
        print(">> Prueba 3: export_core_to_vtr -- Demo Industrial v1 (32x20x32)")
        try:
            test_export_core_to_vtr_pipeline(tmp_dir)
            results.append(("export_core_to_vtr_pipeline", True))
        except Exception as exc:
            print(f"  {FAIL}: {exc}")
            results.append(("export_core_to_vtr_pipeline", False))
    else:
        print()
        print(f"  {SKIP} Pruebas 2 y 3 omitidas (pyevtk no disponible)")

    # Resumen
    print()
    print("-" * 65)
    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print(f"Resultado: {passed}/{total} pruebas PASS")

    if all(ok for _, ok in results):
        print()
        print("ENTENDIDO. FASE 10 IMPLEMENTADA: "
              "EXPORTADOR VTR INTEGRADO PARA PARAVIEW/LEAPFROG.")
        print()
        print(f"  Archivos .vtr generados en: {tmp_dir}")
    else:
        failed = [name for name, ok in results if not ok]
        print(f"  Fallaron: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
