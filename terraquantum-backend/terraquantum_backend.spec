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

FASE 27 (NUEVO-4) — POR QUÉ ESTE ARCHIVO ABORTA EN VEZ DE SEGUIR
================================================================
Este spec devolvía `[]` ante cualquier fallo de recolección y seguía adelante:
el instalador podía salir sin OMF, sin scipy o sin los datos de pyproj, y el
build terminaba en verde. El daño no se ve hasta que el cliente exporta a OMF
y la app se cae en su máquina.

MEDIDO el 2026-09-03, y el diagnóstico de la ficha se quedaba corto: el
`except Exception` NO era la vía por la que fallaba en silencio. `collect_submodules`
**no lanza** cuando el paquete no está — mira su propio código: `if not is_package(pkg):
… return []`, con un log de nivel DEBUG que `--log-level WARN` (el que usa
`scripts/build_desktop.ps1`) ni siquiera imprime. Medido con los tres modos de
fallo posibles:

    paquete ausente del entorno   -> DEVUELVE []      (no lanza)
    paquete presente pero roto    -> DEVUELVE []      (no lanza)
    paquete presente e importable -> DEVUELVE [pkg]   si no es escaneable

O sea: hacer que `_safe_submodules` propague la excepción —el trabajo que pedía
el plan— no habría cambiado NADA, porque no hay excepción que propagar. Lo que
defiende es comprobar el RESULTADO, que es lo que hace `_submodules` abajo.

La prueba de que el mecanismo ya escondía algo: `email_validator` llevaba
recolectándose aquí sin estar instalado, sin estar en `requirements.txt` y sin
un solo uso en el código (0 `EmailStr` en todo el backend). Aportaba `[]` cada
build y nadie se enteró. Se retira en esta fase.

El gate vive en `tests/test_f27_build_guards.py`.
"""
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# PyInstaller inyecta SPECPATH al evaluar este archivo. Los paquetes propios de
# la app sólo son importables si su carpeta está en sys.path, y hasta ahora eso
# dependía de que el build se lanzara con el cwd correcto: desde otro directorio,
# `collect_submodules("services")` devolvía [] —en silencio, como todo lo demás—
# y el ejecutable salía sin los 121 submódulos de la aplicación. Se ancla aquí.
_SPEC_DIR = os.path.abspath(globals().get("SPECPATH") or os.getcwd())
if _SPEC_DIR not in sys.path:
    sys.path.insert(0, _SPEC_DIR)


class BuildDependencyError(Exception):
    """Falta algo que el instalador DEBE llevar. Aborta el build a propósito."""


def _fail(pkg, detail):
    raise BuildDependencyError(
        "\n"
        "==================================================================\n"
        " BUILD ABORTADO — falta una dependencia del instalador\n"
        "==================================================================\n"
        f"  paquete : {pkg}\n"
        f"  problema: {detail}\n"
        f"  python  : {sys.executable}\n"
        f"  version : {sys.version.split()[0]}\n"
        "\n"
        "  Antes de la Fase 27 esto NO paraba el build: se empaquetaba igual y\n"
        "  el fallo aparecía en la máquina del cliente. Instala el cierre\n"
        "  verificado con el intérprete de `.python-version`:\n"
        "\n"
        "      py -3.14 -m pip install --require-hashes -r requirements.lock\n"
        "==================================================================\n"
    )


def _require_importable(pkg):
    """¿Está el paquete en ESTE intérprete? Es la pregunta que nadie hacía."""
    try:
        found = importlib.util.find_spec(pkg)
    except Exception as exc:            # ImportError, ValueError, y lo que traiga
        _fail(pkg, f"no se puede resolver el import ({type(exc).__name__}: {exc})")
    if found is None:
        _fail(pkg, "no está instalado en este intérprete")


def _submodules(pkg):
    """Submódulos de un paquete REQUERIDO. Vacío o degenerado ⇒ aborta.

    Sin `try/except`: si `collect_submodules` lanza, que la excepción mate el
    build. Lo que se comprueba de verdad es el resultado, porque el modo de
    fallo real —paquete ausente— no lanza nada (ver el docstring de arriba).
    """
    _require_importable(pkg)
    found = collect_submodules(pkg)
    if not found:
        _fail(pkg, "collect_submodules devolvió 0 submódulos (importable pero "
                   "no escaneable, o instalación rota)")
    if found == [pkg]:
        _fail(pkg, "collect_submodules sólo devolvió el nombre del paquete: no "
                   "pudo recorrerlo, así que el ejecutable saldría sin sus "
                   "submódulos y fallaría en tiempo de ejecución")
    return found


def _datafiles(pkg):
    """Data files de un paquete REQUERIDO. Cero ⇒ aborta.

    pyproj sin su base de datos de proyecciones y skimage/scipy sin los suyos
    producen un ejecutable que arranca y revienta al primer uso real. Medido
    hoy: pyproj 66, skimage 115, scipy 443, pandas 95, pyarrow 622,
    charset_normalizer 1 — ninguno legítimamente vacío.
    """
    _require_importable(pkg)
    found = collect_data_files(pkg)
    if not found:
        _fail(pkg, "collect_data_files devolvió 0 archivos de datos")
    return found


hiddenimports = []
datas = []

# El IGRF-14 offline: sin él la reducción magnética no tiene campo de referencia
# y el producto es offline POR DISEÑO, así que no hay descarga que lo salve.
_IGRF = os.path.join(_SPEC_DIR, "services", "data", "igrf14coeffs.txt")
if not os.path.isfile(_IGRF):
    _fail("services/data/igrf14coeffs.txt",
          "falta el fichero de coeficientes IGRF-14 que se empaqueta como dato")
datas.append((_IGRF, "services/data"))

# Paquetes propios de la app: bundlear completo para resolver imports lazy.
for _pkg in ("api", "services", "core", "exploration", "schemas", "middleware", "reporting"):
    hiddenimports += _submodules(_pkg)

# Servidor web + validación.
# `email_validator` estaba en esta lista y se retira en la Fase 27: no está
# instalado, no está declarado en requirements.txt y el backend no usa `EmailStr`
# en ningún sitio. Era exactamente el `[]` silencioso que esta fase persigue.
for _pkg in ("uvicorn", "anyio", "slowapi", "limits"):
    hiddenimports += _submodules(_pkg)

# Stack científico (data files + submódulos que el análisis estático suele perder).
for _pkg in ("pyproj", "skimage", "scipy", "pandas", "pyarrow", "charset_normalizer"):
    datas += _datafiles(_pkg)
hiddenimports += _submodules("scipy")
hiddenimports += _submodules("skimage")
hiddenimports += _submodules("pyproj")

# Fase 12 — OMF. `omf` y `properties` resuelven clases por metaclase y registro
# (`properties.HasProperties`), que es justo lo que el análisis estático de
# PyInstaller pierde: sin esto el sidecar empaquetado exporta/importa OMF en
# desarrollo y falla en el instalador.
for _pkg in ("omf", "properties", "vectormath"):
    hiddenimports += _submodules(_pkg)

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
