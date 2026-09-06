"""Fase 27 — el instalador falla en voz alta cuando falta una dependencia.

Cierra NUEVO-4, NUEVO-5 y la parte de H-23 que quedaba viva.

QUÉ DEFIENDE CADA BLOQUE
========================
* **el `.spec`** — antes recolectaba `[]` ante cualquier fallo y seguía. El
  ejecutable salía sin OMF (o sin los datos de pyproj) y el build terminaba en
  verde; el cliente se lo encontraba al exportar.
* **el lock** — `requirements.txt` declara intención con rangos deliberados;
  `requirements.lock` es el cierre resuelto y con hashes que se instala con
  `--require-hashes`.
* **`build_desktop.ps1`** — llamaba a `python` a secas y nunca lo comparaba con
  `.python-version`. En la máquina de desarrollo ese `python` es 3.11.9 SIN
  numpy mientras `.python-version` declara 3.14.4.

EL MATIZ QUE LA FICHA NO TENÍA
==============================
La ficha de NUEVO-4 culpaba al `except Exception` del `.spec`. MEDIDO: ése no
era el camino. `collect_submodules` **no lanza** cuando el paquete falta —
devuelve `[]` con un log de nivel DEBUG que el `--log-level WARN` del build ni
imprime. Hacer que la excepción se propagara, que es lo que pedía el plan, no
habría cambiado nada. Por eso estos tests comprueban el RESULTADO de la
recolección, no que se lance una excepción.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SPEC = BACKEND_ROOT / "terraquantum_backend.spec"
LOCKFILE = BACKEND_ROOT / "requirements.lock"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"
BUILD_PS1 = REPO_ROOT / "scripts" / "build_desktop.ps1"

sys.path.insert(0, str(BACKEND_ROOT / "scripts" / "ci"))
import check_env_against_lock as env_check  # noqa: E402


# ── utilidades para ejecutar el .spec de verdad ───────────────────────────────

class _FakeAnalysis:
    """Sustituye a Analysis: captura lo que el spec le pasa y no analiza nada."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.pure = object()
        self.scripts, self.binaries, self.datas = [], [], []


def _healthy_submodules(pkg, *args, **kwargs):
    return [pkg, f"{pkg}.uno", f"{pkg}.dos"]


def _healthy_datafiles(pkg, *args, **kwargs):
    return [(f"{pkg}/datos.bin", pkg)]


def _install_fake_hooks(monkeypatch, submodules, datafiles):
    """Pone un `PyInstaller.utils.hooks` de mentira en sys.modules.

    Es lo que permite que estos tests corran EN LA CI, donde PyInstaller no se
    instala (vive en requirements-build.txt, aparte a propósito). Lo que se
    prueba es la guarda del spec, no la recolección de PyInstaller — así que
    simularla no debilita nada y evita que el gate se quede en `skip`, que es
    como los gates dejan de defender.
    """
    import types

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = submodules
    hooks.collect_data_files = datafiles
    utils = types.ModuleType("PyInstaller.utils")
    utils.hooks = hooks
    root = types.ModuleType("PyInstaller")
    root.utils = utils
    monkeypatch.setitem(sys.modules, "PyInstaller", root)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)


def _run_spec(monkeypatch, specpath=None, submodules=None, datafiles=None, real=False):
    """Ejecuta el .spec REAL con Analysis/PYZ/EXE simulados.

    Con `real=True` usa los recolectores de verdad (exige PyInstaller). Si no,
    inyecta unos sintéticos: así se simula una dependencia ausente sin
    desinstalar nada y sin depender de la cadena de build.
    Devuelve el dict de globals resultante (`hiddenimports`, `datas`, …).
    """
    if real:
        import PyInstaller.utils.hooks  # noqa: F401 - carga el módulo verdadero
    else:
        _install_fake_hooks(monkeypatch,
                            submodules or _healthy_submodules,
                            datafiles or _healthy_datafiles)
    monkeypatch.setattr(sys, "path", list(sys.path))

    pedidos = {"submodules": [], "datafiles": []}
    hooks = sys.modules["PyInstaller.utils.hooks"]
    base_sub, base_data = hooks.collect_submodules, hooks.collect_data_files

    def _spy_sub(pkg, *args, **kwargs):
        pedidos["submodules"].append(pkg)
        return base_sub(pkg, *args, **kwargs)

    def _spy_data(pkg, *args, **kwargs):
        pedidos["datafiles"].append(pkg)
        return base_data(pkg, *args, **kwargs)

    monkeypatch.setattr(hooks, "collect_submodules", _spy_sub)
    monkeypatch.setattr(hooks, "collect_data_files", _spy_data)

    captured = {}

    def _analysis(*args, **kwargs):
        analysis = _FakeAnalysis(*args, **kwargs)
        captured["analysis"] = analysis
        return analysis

    namespace = {
        "Analysis": _analysis,
        "PYZ": lambda *a, **k: object(),
        "EXE": lambda *a, **k: object(),
        "SPECPATH": str(specpath or BACKEND_ROOT),
    }
    code = compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec")
    exec(code, namespace)          # noqa: S102 - ejecutar el spec ES la prueba
    namespace["_captured"] = captured
    namespace["_pedidos"] = pedidos
    return namespace


def _expect_abort(monkeypatch, **kwargs):
    """El spec DEBE abortar. Devuelve el mensaje para poder comprobarlo."""
    with pytest.raises(Exception) as excinfo:      # noqa: PT011 - clase del spec
        _run_spec(monkeypatch, **kwargs)
    assert type(excinfo.value).__name__ == "BuildDependencyError", (
        f"El spec murió con {type(excinfo.value).__name__} en vez de abortar "
        f"a propósito: {excinfo.value}"
    )
    return str(excinfo.value)


# ── NUEVO-4: el .spec aborta en vez de empaquetar a medias ────────────────────

@pytest.mark.parametrize("ausente", ["omf", "properties", "vectormath", "scipy",
                                     "services", "exploration", "uvicorn"])
def test_spec_aborta_si_collect_submodules_devuelve_vacio(monkeypatch, ausente):
    """El modo de fallo REAL: el paquete no está y `collect_submodules`
    devuelve `[]` sin lanzar nada. Antes de la Fase 27 esto se empaquetaba.

    Se recorren varios paquetes porque la guarda tiene que valer para TODOS:
    con la lista antigua bastaba que uno cayera para enviar un exe incompleto.
    """
    def fake(pkg, *args, **kwargs):
        return [] if pkg == ausente else _healthy_submodules(pkg)

    message = _expect_abort(monkeypatch, submodules=fake)
    assert ausente in message
    assert "0 submódulos" in message


def test_spec_aborta_si_el_paquete_no_es_escaneable(monkeypatch):
    """Segundo modo medido: importable pero no recorrible ⇒ `[pkg]` a secas.
    El ejecutable saldría con el paquete y sin ninguno de sus submódulos."""
    def fake(pkg, *args, **kwargs):
        return [pkg] if pkg == "properties" else _healthy_submodules(pkg)

    message = _expect_abort(monkeypatch, submodules=fake)
    assert "properties" in message
    assert "sólo devolvió el nombre del paquete" in message


@pytest.mark.parametrize("ausente", ["pyproj", "skimage", "scipy", "pandas",
                                     "pyarrow", "charset_normalizer"])
def test_spec_aborta_si_faltan_los_datafiles(monkeypatch, ausente):
    """pyproj sin su base de proyecciones arranca y revienta al primer uso."""
    def fake(pkg, *args, **kwargs):
        return [] if pkg == ausente else _healthy_datafiles(pkg)

    message = _expect_abort(monkeypatch, datafiles=fake)
    assert ausente in message
    assert "0 archivos de datos" in message


def test_spec_aborta_si_falta_el_igrf(monkeypatch, tmp_path):
    """Sin los coeficientes IGRF-14 no hay campo de referencia, y el producto
    es offline por diseño: no hay descarga que lo arregle en el cliente."""
    message = _expect_abort(monkeypatch, specpath=tmp_path)
    assert "igrf14coeffs.txt" in message


def test_spec_aborta_si_el_paquete_no_esta_instalado(monkeypatch):
    """`find_spec` es la pregunta que el spec no hacía: ¿está en ESTE intérprete?"""
    import importlib.util

    real_find = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name == "vectormath":
            return None
        return real_find(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    message = _expect_abort(monkeypatch)
    assert "vectormath" in message
    assert "no está instalado" in message


def test_el_mensaje_de_aborto_dice_como_arreglarlo(monkeypatch):
    """Un build que falla sin decir qué hacer se salta con `--skip`."""
    message = _expect_abort(
        monkeypatch,
        submodules=lambda pkg, *a, **k: [] if pkg == "omf" else _healthy_submodules(pkg),
    )
    assert "requirements.lock" in message
    assert "--require-hashes" in message
    assert sys.version.split()[0] in message, "El mensaje debe decir con qué Python falló."


def test_el_spec_sano_no_aborta_y_pide_lo_que_debe(monkeypatch):
    """Camino feliz con recolectores sintéticos: el spec llega hasta Analysis y
    pide exactamente los paquetes que el instalador necesita."""
    namespace = _run_spec(monkeypatch)
    pedidos = namespace["_pedidos"]

    for pkg in ("api", "services", "core", "exploration", "schemas", "middleware",
                "reporting", "uvicorn", "anyio", "slowapi", "limits",
                "scipy", "skimage", "pyproj", "omf", "properties", "vectormath"):
        assert pkg in pedidos["submodules"], f"El spec ya no recolecta {pkg}."
    for pkg in ("pyproj", "skimage", "scipy", "pandas", "pyarrow", "charset_normalizer"):
        assert pkg in pedidos["datafiles"], f"El spec ya no recolecta datos de {pkg}."

    analysis = namespace["_captured"]["analysis"]
    assert analysis.kwargs["hiddenimports"], "Analysis recibió hiddenimports vacíos."
    assert any(str(d[0]).endswith("igrf14coeffs.txt")
               for d in analysis.kwargs["datas"])


@pytest.mark.slow
def test_el_spec_sano_recolecta_de_verdad(monkeypatch):
    """Sin simular nada: el spec REAL sobre el entorno REAL no aborta y trae
    los submódulos de la app, del stack científico y de la cadena OMF.

    Sólo corre donde está la cadena de build (la máquina que construye el
    instalador). Los tests de arriba cubren la GUARDA en cualquier entorno.
    """
    pytest.importorskip("PyInstaller", reason="cadena de build (requirements-build.txt)")

    namespace = _run_spec(monkeypatch, real=True)
    hidden = namespace["hiddenimports"]
    datas = namespace["datas"]

    for pkg in ("api", "services", "core", "exploration", "schemas", "middleware",
                "reporting", "omf", "properties", "vectormath", "scipy", "skimage",
                "pyproj", "uvicorn", "anyio", "slowapi", "limits"):
        assert any(m == pkg or m.startswith(pkg + ".") for m in hidden), (
            f"El ejecutable saldría sin {pkg}."
        )
    assert any(m.startswith("omf.") for m in hidden), (
        "OMF sin submódulos: es el caso que NUEVO-4 describe."
    )
    assert any(m.startswith("services.") for m in hidden), (
        "Los paquetes de la app dependían del cwd; el spec ancla SPECPATH."
    )
    assert any(str(d[0]).endswith("igrf14coeffs.txt") for d in datas)
    assert len(hidden) > 500, f"Sólo {len(hidden)} hiddenimports: la recolección se rompió."


def test_email_validator_ya_no_se_recolecta(monkeypatch):
    """No está instalado, no está en requirements.txt y el backend no usa
    `EmailStr`. Aportaba `[]` en cada build y nadie se enteró: es la prueba de
    que el mecanismo silencioso ya estaba escondiendo algo."""
    namespace = _run_spec(monkeypatch)
    assert "email_validator" not in namespace["_pedidos"]["submodules"]

    users = [p for p in BACKEND_ROOT.glob("**/*.py")
             if "EmailStr" in p.read_text(encoding="utf-8", errors="ignore")
             and "test_f27" not in p.name]
    assert not users, f"Alguien usa EmailStr: hay que volver a declarar la dependencia ({users})."


def test_el_spec_no_traga_excepciones():
    """La regresión más probable: que alguien reponga el `try/except` que
    devolvía `[]`.

    Se mira el ÁRBOL, no el texto: el docstring del spec cita a propósito el
    `return []` de PyInstaller, y un test que buscara la cadena se pondría rojo
    por la explicación del defecto en vez de por el defecto.
    """
    import ast

    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    culpables = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.List) and not node.value.elts
    ]
    assert not culpables, (
        f"`return []` en el spec (líneas {culpables}) es exactamente NUEVO-4: "
        "recolección vacía que sigue adelante y produce un instalador incompleto."
    )

    def _aborta(node):
        """¿Este `except` termina el build, por `raise` o llamando a `_fail`?"""
        for inner in ast.walk(node):
            if isinstance(inner, ast.Raise):
                return True
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_fail"):
                return True
        return False

    manejadores = [node.lineno for node in ast.walk(tree)
                   if isinstance(node, ast.ExceptHandler) and not _aborta(node)]
    assert not manejadores, (
        f"`except` que no aborta (líneas {manejadores}): el spec no debe "
        "tragarse ningún fallo de recolección."
    )


def test_fail_del_spec_lanza_de_verdad():
    """Aceptar `_fail(...)` como aborto sólo vale si `_fail` aborta. Si algún
    día devolviera en vez de lanzar, el test de arriba pasaría a ser cómplice."""
    import ast

    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    fail = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "_fail")
    assert any(isinstance(inner, ast.Raise) for inner in ast.walk(fail)), (
        "`_fail` ya no lanza: el spec seguiría construyendo tras un fallo."
    )


# ── H-23: el lockfile con hashes ──────────────────────────────────────────────

def test_existe_el_lockfile():
    assert LOCKFILE.exists(), (
        "Falta requirements.lock. Genéralo:  py -3.14 scripts/ci/gen_lockfile.py"
    )


def test_cada_paquete_del_lock_lleva_al_menos_un_hash():
    pins = env_check.read_lock()
    assert pins, "El lock no declara ningún paquete."
    text = LOCKFILE.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9])", text)
    sin_hash = []
    for block in blocks:
        match = re.match(r"^([A-Za-z0-9_.\-]+)==", block)
        if not match:
            continue
        if not re.search(r"--hash=sha256:[0-9a-f]{64}", block):
            sin_hash.append(match.group(1))
    assert not sin_hash, (
        "Un pin sin hash no defiende nada — `--require-hashes` ni lo aceptaría: "
        + ", ".join(sin_hash)
    )


def test_el_lock_cubre_y_respeta_requirements_txt():
    """El lock es lo que `requirements.txt` RESOLVIÓ: cada requisito directo
    tiene que estar, y con una versión que su especificador admita."""
    from packaging.requirements import Requirement

    pins = env_check.read_lock()
    faltan, violan = [], []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = Requirement(line)
        name = env_check._canon(requirement.name)
        if name not in pins:
            faltan.append(requirement.name)
            continue
        if not requirement.specifier.contains(pins[name], prereleases=True):
            violan.append(f"{requirement.name}{requirement.specifier} vs lock {pins[name]}")
    assert not faltan, f"Requisitos directos ausentes del lock: {faltan}"
    assert not violan, f"El lock contradice a requirements.txt: {violan}"


def test_el_nucleo_numerico_del_lock_es_el_declarado():
    """numpy/scipy/pyproj/polars deciden el resultado del solver. Si el lock
    los mueve, el instalador ya no reproduce la física validada."""
    exact = env_check.read_exact_pins()
    pins = env_check.read_lock()
    for pkg in ("numpy", "scipy", "pyproj", "polars"):
        assert exact[pkg] == pins[pkg], (
            f"{pkg}: requirements.txt=={exact[pkg]} pero el lock dice {pins[pkg]}."
        )


def test_six_esta_pineada():
    """NUEVO-5: el comentario de requirements.txt nombraba CUATRO transitivas de
    `omf` y pineaba tres."""
    exact = env_check.read_exact_pins()
    for pkg in ("properties", "vectormath", "pypng", "six"):
        assert pkg in exact, f"{pkg} (transitiva de omf sin techo aguas arriba) sin pin exacto."
    assert "six" in env_check.read_lock()


def test_ninguna_transitiva_de_omf_queda_sin_pin():
    """La regla que generó NUEVO-5, escrita para que no vuelva a pasar: `omf`
    declara sus cuatro dependencias sin techo, así que las cuatro se pinean."""
    from importlib import metadata

    exact = env_check.read_exact_pins()
    sin_pin = []
    for requirement in metadata.requires("omf") or []:
        name = env_check._canon(re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0])
        if name not in exact:
            sin_pin.append(name)
    assert not sin_pin, (
        f"Transitivas de omf sin pin exacto en requirements.txt: {sin_pin}"
    )


# ── el comprobador de entorno decide bien ─────────────────────────────────────

def test_una_dependencia_ausente_es_fatal():
    missing, fatal, soft = env_check.audit({"paquete-que-no-existe-xyz": "1.0"}, {})
    assert missing == ["paquete-que-no-existe-xyz"]
    assert not fatal and not soft


def test_la_deriva_de_un_pin_exacto_es_fatal():
    """`numpy==2.4.4` está pineado por determinismo del solver."""
    _, fatal, soft = env_check.audit({"numpy": "0.0.1"}, {"numpy": "0.0.1"})
    assert [n for n, _, _ in fatal] == ["numpy"]
    assert not soft


def test_la_deriva_dentro_de_un_rango_no_bloquea():
    """`zarr>=2.14.0,<4.0.0` es un rango deliberado; bloquear aquí sólo haría
    que alguien desactivara el gate."""
    missing, fatal, soft = env_check.audit({"zarr": "0.0.1"}, {})
    assert not missing and not fatal
    assert [n for n, _, _ in soft] == ["zarr"]


def test_el_entorno_de_esta_maquina_puede_construir():
    """Sin faltantes ni derivas de pineados exactos. Si esto se pone rojo, el
    instalador que salga de aquí no es el que dice ser."""
    missing, fatal, _ = env_check.audit(env_check.read_lock(), env_check.read_exact_pins())
    assert not missing, f"Faltan dependencias en este intérprete: {missing}"
    assert not fatal, f"Pines exactos incumplidos: {fatal}"


_CHECKER = BACKEND_ROOT / "scripts" / "ci" / "check_env_against_lock.py"


def _run_checker(*extra):
    return subprocess.run([sys.executable, str(_CHECKER), *extra],
                          capture_output=True, text=True, cwd=str(BACKEND_ROOT))


def test_el_comprobador_de_entorno_se_ejecuta_de_verdad():
    """El script es lo que llama el build; que corra, no sólo que importe."""
    result = _run_checker()
    assert result.returncode == 0, result.stdout + result.stderr


def test_el_comprobador_SALE_CON_ERROR_si_falta_una_dependencia(tmp_path):
    """El agujero que destapó la mutación M14 del gate de esta fase.

    Los tests de `audit()` comprobaban la CLASIFICACIÓN; ninguno comprobaba la
    DECISIÓN — el código de salida, que es lo único que `build_desktop.ps1`
    mira. Con eso, volver no-fatal la ausencia de una dependencia pasaba el
    gate en verde: el defecto que la fase entera dice cerrar.
    """
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "paquete-que-no-existe-en-ningun-sitio==1.0 \\\n"
        "    --hash=sha256:" + "0" * 64 + "\n",
        encoding="utf-8",
    )
    result = _run_checker("--lock", str(lock))
    assert result.returncode == 1, (
        "Una dependencia ausente TIENE que abortar el build.\n"
        + result.stdout + result.stderr
    )
    assert "paquete-que-no-existe-en-ningun-sitio" in (result.stdout + result.stderr)


def test_el_comprobador_SALE_CON_ERROR_si_un_pin_exacto_deriva(tmp_path):
    """La otra mitad de la decisión: `numpy==` movido no puede pasar."""
    lock = tmp_path / "requirements.lock"
    lock.write_text("numpy==0.0.1 \\\n    --hash=sha256:" + "0" * 64 + "\n",
                    encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("numpy==0.0.1\n", encoding="utf-8")
    result = _run_checker("--lock", str(lock), "--requirements", str(requirements))
    assert result.returncode == 1, result.stdout + result.stderr


def test_el_comprobador_dice_como_regenerar_un_lock_ausente(tmp_path):
    """Sin lock, abortar no basta: un traceback de FileNotFoundError también
    aborta, y no le dice a nadie qué hacer. La fase promete voz alta, no ruido."""
    result = _run_checker("--lock", str(tmp_path / "no_existe.lock"))
    salida = result.stdout + result.stderr
    assert result.returncode == 1, salida
    assert "gen_lockfile.py" in salida, (
        "El mensaje no dice cómo regenerar el lock: " + salida
    )
    assert "Traceback" not in salida, "Se escapa un traceback en vez del aviso."


def test_el_comprobador_NO_aborta_por_una_deriva_dentro_de_rango(tmp_path):
    """Y no al revés: si bloqueara los rangos deliberados, alguien lo apagaría."""
    lock = tmp_path / "requirements.lock"
    lock.write_text("pytest==0.0.1 \\\n    --hash=sha256:" + "0" * 64 + "\n",
                    encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest>=0.0.1,<99.0.0\n", encoding="utf-8")
    result = _run_checker("--lock", str(lock), "--requirements", str(requirements))
    assert result.returncode == 0, result.stdout + result.stderr


# ── H-23: el build script comprueba el intérprete ─────────────────────────────

def test_el_build_compara_el_interprete_con_python_version():
    source = BUILD_PS1.read_text(encoding="utf-8")
    assert ".python-version" in source, (
        "H-23: build_desktop.ps1 no compara el intérprete con .python-version. "
        "En esta máquina el `python` del PATH es 3.11.9 SIN numpy."
    )
    assert "Interprete equivocado" in source, (
        "Detectar la discrepancia y no abortar es peor que no detectarla."
    )


def test_el_build_no_invoca_python_a_secas():
    """El defecto literal: `python -m PyInstaller` cogía el del PATH."""
    source = BUILD_PS1.read_text(encoding="utf-8")
    ofensivas = [
        line.strip() for line in source.splitlines()
        if re.search(r"(?<![\w$@-])python\s+-[mc]\b", line)
        and not line.strip().startswith("#")
    ]
    assert not ofensivas, (
        "Llamadas a `python` sin resolver contra .python-version: " + str(ofensivas)
    )


def test_el_build_comprueba_el_entorno_contra_el_lock():
    source = BUILD_PS1.read_text(encoding="utf-8")
    assert "check_env_against_lock.py" in source
    assert "requirements.lock" in source


def test_el_build_propaga_el_fallo_de_pyinstaller():
    """Antes sólo miraba si el exe existía: un PyInstaller que fallara dejando
    un dist/ viejo pasaba por bueno."""
    lines = BUILD_PS1.read_text(encoding="utf-8").splitlines()
    invocaciones = [i for i, line in enumerate(lines)
                    if "PyInstaller terraquantum_backend.spec" in line
                    and not line.strip().startswith("#")]
    assert invocaciones, "Nadie invoca el .spec en el build."
    for index in invocaciones:
        siguientes = "\n".join(lines[index + 1:index + 6])
        assert "LASTEXITCODE" in siguientes, (
            "Tras invocar PyInstaller no se comprueba su código de salida: un "
            "build fallido con un dist/ viejo pasaría por bueno."
        )
