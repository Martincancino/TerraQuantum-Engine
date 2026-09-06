"""Fase 27 (H-23) — genera `requirements.lock`: el cierre resuelto y con hashes.

QUÉ RESUELVE
============
`requirements.txt` declara INTENCIÓN: 34 requisitos directos, unos pineados
exactos (razón numérica) y otros acotados por rango (razón de cadena de
suministro). Eso no basta para reconstruir el instalador firmado: entre dos
builds de la MISMA versión de TerraQuantum, un rango puede resolver distinto y
un `==` sin hash puede resolver a un artefacto distinto con el mismo número.

MEDIDO el 2026-09-03 en esta máquina: `requirements.txt` resuelve HOY a
`zarr 3.3.0` y `dask 2026.8.0`, mientras el propio comentario del archivo anota
«verificado 3.2.1» y «verificado 2026.3.0». El rango es deliberado y no se toca;
lo que faltaba era el artefacto que dice *qué salió realmente*.

`requirements.lock` es ese artefacto: los paquetes del cierre transitivo,
pineados exactos, cada uno con el sha256 de **todos** sus ficheros publicados.
Se instala con `--require-hashes`, que además obliga a que el fichero esté
completo: si pip necesitara algo que no está listado, aborta.

POR QUÉ NO `pip-compile`
========================
`pip-compile --generate-hashes` (pip-tools) es la herramienta estándar y es lo
que pedía el plan. No se usó porque instalar pip-tools es una dependencia nueva
y la regla del proyecto exige permiso expreso. Este script hace lo mismo con la
biblioteca estándar: pip resuelve (`--dry-run --report`, que no instala nada) y
la API JSON de PyPI aporta los hashes de todos los ficheros de cada versión.

POR QUÉ LOS HASHES DE **TODOS** LOS FICHEROS
============================================
El informe de pip trae el hash del wheel elegido PARA ESTA plataforma. El
instalador se construye en Windows y la CI corre en Linux: con un solo hash, la
CI no podría instalar. Se listan todos los ficheros de la versión —igual que
hace pip-compile— y pip elige el que le sirve.

MEDIDO: el conjunto resuelto es IDÉNTICO en Windows (cp314, nativo) y en Linux
(manylinux/cp314): 105 paquetes, mismas versiones, cero diferencias. Por eso el
lock no necesita marcadores de entorno. `--check` vuelve a medirlo.

USO
===
    py -3.14 scripts/ci/gen_lockfile.py            # regenera requirements.lock
    py -3.14 scripts/ci/gen_lockfile.py --check    # ¿está al día? (exit 1 si no)

Ambos modos SALEN A LA RED (PyPI). Por eso `--check` no es una puerta de CI:
la puerta de CI es instalar con `--require-hashes`, que valida los hashes de
verdad, más `tests/test_f27_build_guards.py`, que comprueba sin red que el lock
cubre cada requisito directo y respeta su rango.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"
LOCKFILE = BACKEND_ROOT / "requirements.lock"

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"

# Etiquetas de plataforma con las que se comprueba que el cierre no depende del
# sistema operativo. Varias porque los wheels no usan todos la misma: pydantic
# publica `manylinux_2_17`, otros `manylinux_2_28`; con una sola, pip no
# encuentra candidato y el chequeo cruzado falla por una razón que no es la real.
LINUX_PLATFORMS = (
    "manylinux_2_28_x86_64",
    "manylinux_2_17_x86_64",
    "manylinux2014_x86_64",
    "linux_x86_64",
)

# Estos tres se publican SÓLO como sdist (`omf` y su cadena, ver requirements.txt).
# La resolución cruzada exige `--only-binary=:all:`, que los rechazaría por no
# tener wheel; se excluyen de ESA comprobación y se reinyectan. Son Python puro y
# están pineados exactos, así que su resolución no depende de la plataforma.
SDIST_ONLY = ("omf", "properties", "vectormath")

HEADER = """\
# TerraQuantum — CIERRE RESUELTO Y VERIFICADO de las dependencias del backend.
#
# GENERADO. No se edita a mano:
#     py -3.14 scripts/ci/gen_lockfile.py
#
# La fuente de verdad de la INTENCION es `requirements.txt` (rangos deliberados,
# con su razon escrita). Este archivo es lo que esa intencion resolvio, pineado
# exacto y con el sha256 de todos los ficheros publicados de cada version.
#
# Se instala asi — el `--require-hashes` es el punto entero del archivo:
#     pip install --require-hashes -r requirements.lock
#
# Fase 27 (H-23). Interprete de referencia: Python {python_version}
# (`.python-version`). Paquetes: {count}.
"""


def _run_pip_report(args, label):
    """Resuelve con pip SIN instalar nada y devuelve el informe JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run",
               "--ignore-installed", "--quiet", "--report", str(report), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write("\n[%s] pip fallo:\n%s\n%s\n" % (label, proc.stdout, proc.stderr))
            raise SystemExit("No se pudo resolver (%s)." % label)
        return json.loads(report.read_text(encoding="utf-8"))


def _resolved(report):
    return {
        p["metadata"]["name"].lower().replace("_", "-"): p["metadata"]["version"]
        for p in report["install"]
    }


def resolve_native():
    return _resolved(_run_pip_report(["-r", str(REQUIREMENTS)], "nativo"))


def resolve_linux():
    """Mismo cierre, resuelto para Linux/cp314 (lo que corre la CI)."""
    kept = [
        line for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.split("==")[0].strip().lower() not in SDIST_ONLY
    ]
    with tempfile.TemporaryDirectory() as tmp:
        filtered = Path(tmp) / "requirements-nosdist.txt"
        filtered.write_text("\n".join(kept), encoding="utf-8")
        target = Path(tmp) / "_target"
        args = ["--only-binary=:all:", "--python-version", "3.14", "--abi", "cp314",
                "--target", str(target)]
        for plat in LINUX_PLATFORMS:
            args += ["--platform", plat]
        args += ["-r", str(filtered)]
        return _resolved(_run_pip_report(args, "linux"))


def hashes_for(name, version):
    """sha256 de TODOS los ficheros publicados de esa version, ordenados."""
    url = PYPI_JSON.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:            # pragma: no cover - red
        raise SystemExit("PyPI no conoce %s==%s: %s" % (name, version, exc)) from exc
    digests = sorted({f["digests"]["sha256"] for f in payload.get("urls", [])})
    if not digests:
        raise SystemExit(
            "%s==%s no publica ficheros con sha256: sin hashes no se puede "
            "pinear, y un lock sin hashes no defiende nada." % (name, version)
        )
    return digests


def render(resolved):
    python_version = (BACKEND_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    out = [HEADER.format(python_version=python_version, count=len(resolved))]
    for name in sorted(resolved):
        version = resolved[name]
        lines = ["%s==%s \\" % (name, version)]
        digests = hashes_for(name, version)
        for index, digest in enumerate(digests):
            suffix = "" if index == len(digests) - 1 else " \\"
            lines.append("    --hash=sha256:%s%s" % (digest, suffix))
        out.append("\n".join(lines))
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Genera requirements.lock.")
    parser.add_argument("--check", action="store_true",
                        help="No escribe: falla si el lock del disco no coincide.")
    args = parser.parse_args()

    print("Resolviendo requirements.txt (nativo)...", file=sys.stderr)
    native = resolve_native()
    print("  %d paquetes." % len(native), file=sys.stderr)

    print("Resolviendo para Linux/cp314 (lo que corre la CI)...", file=sys.stderr)
    linux = resolve_linux()
    linux.update({p: native[p] for p in SDIST_ONLY if p in native})

    if native != linux:
        only_win = sorted(set(native) - set(linux))
        only_lnx = sorted(set(linux) - set(native))
        drift = sorted((k, native[k], linux[k]) for k in set(native) & set(linux)
                       if native[k] != linux[k])
        raise SystemExit(
            "El cierre DEPENDE de la plataforma, asi que un lock sin marcadores "
            "de entorno mentiria en una de las dos.\n"
            "  solo en esta maquina: %s\n"
            "  solo en Linux:        %s\n"
            "  version distinta:     %s" % (only_win, only_lnx, drift)
        )
    print("  identico al nativo: el lock no necesita marcadores.", file=sys.stderr)

    print("Pidiendo hashes a PyPI...", file=sys.stderr)
    rendered = render(native)

    if args.check:
        if not LOCKFILE.exists():
            print("FALTA requirements.lock.", file=sys.stderr)
            return 1
        if LOCKFILE.read_text(encoding="utf-8") != rendered:
            print("requirements.lock esta DESACTUALIZADO respecto de "
                  "requirements.txt. Regeneralo:\n"
                  "    py -3.14 scripts/ci/gen_lockfile.py", file=sys.stderr)
            return 1
        print("requirements.lock al dia.", file=sys.stderr)
        return 0

    LOCKFILE.write_text(rendered, encoding="utf-8")
    print("Escrito %s (%d paquetes)." % (LOCKFILE, len(native)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
