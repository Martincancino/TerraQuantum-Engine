# -*- mode: python ; coding: utf-8 -*-
"""F7 — PyInstaller spec para empaquetar el backend TerraQuantum como sidecar.

Produce un ejecutable onefile `terraquantum-backend(.exe)` que levanta FastAPI/
uvicorn sin Python instalado en la máquina destino. Tauri lo lanza como sidecar.

Notas:
- Se bundlean TODOS los submódulos de la app (api/services/core/exploration/…)
  porque muchos se importan de forma LAZY dentro de funciones y el análisis
  estático no los vería.
- Data files: IGRF-14 offline + datos de pyproj/scikit-image/scipy/pandas.
- earthengine-api NO se incluye (import lazy, opcional, credenciales revocadas):
  offline por diseño.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
datas = [("services/data/igrf14coeffs.txt", "services/data")]


def _safe_submodules(pkg):
    try:
        return collect_submodules(pkg)
    except Exception:
        return []


def _safe_datafiles(pkg):
    try:
        return collect_data_files(pkg)
    except Exception:
        return []


# Paquetes propios de la app: bundlear completo para resolver imports lazy.
for _pkg in ("api", "services", "core", "exploration", "schemas", "middleware", "reporting"):
    hiddenimports += _safe_submodules(_pkg)

# Servidor web + validación.
for _pkg in ("uvicorn", "anyio", "slowapi", "limits", "email_validator"):
    hiddenimports += _safe_submodules(_pkg)

# Stack científico (data files + submódulos que el análisis estático suele perder).
for _pkg in ("pyproj", "skimage", "scipy", "pandas", "pyarrow", "charset_normalizer"):
    datas += _safe_datafiles(_pkg)
hiddenimports += _safe_submodules("scipy")
hiddenimports += _safe_submodules("skimage")
hiddenimports += _safe_submodules("pyproj")

# Fase 12 — OMF. `omf` y `properties` resuelven clases por metaclase y registro
# (`properties.HasProperties`), que es justo lo que el análisis estático de
# PyInstaller pierde: sin esto el sidecar empaquetado exporta/importa OMF en
# desarrollo y falla en el instalador.
for _pkg in ("omf", "properties", "vectormath"):
    hiddenimports += _safe_submodules(_pkg)

# Excluir lo pesado y opcional que NO es parte del camino dorado offline.
excludes = ["ee", "earthengine_api", "google.genai", "google.generativeai",
            "matplotlib", "tkinter", "IPython", "notebook", "pytest"]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="terraquantum-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
