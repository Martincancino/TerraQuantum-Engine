"""FASE 10 (H-16) — Genera los tipos TypeScript del frontend desde el OpenAPI.

    python scripts/ci/generate_frontend_types.py            # escribe el archivo
    python scripts/ci/generate_frontend_types.py --check     # falla si hay deriva

**El problema que resuelve.** El frontend declaraba a mano los contratos del
backend, leyendo Python. Nada garantizaba que siguieran coincidiendo: el backend
añade un campo y no falla nada hasta que un usuario ve un dato vacío. Es la clase
de bug que no tiene test posible — porque el "test" sería volver a escribir el
contrato a mano por tercera vez.

**Por qué NO se usa `openapi-typescript`.** Es la herramienta que sugería la
auditoría y sería una elección razonable, pero: (1) añadir una dependencia de npm
necesita permiso expreso en este repositorio; (2) el generador tiene que correr
en el job de **backend** de la CI, que es donde vive la app que produce el
esquema y donde NO hay Node; y (3) lo que hay que generar son 30 tipos de un
esquema que ya está en memoria — no justifica un árbol de dependencias. Esto son
~200 líneas de Python sin dependencias nuevas, y el `--check` es el guard.

**Lo que el generador NO hace, a propósito.** No inventa uniones discriminadas.
`POST /v2/gravity-import/load-package` devuelve tres formas distintas según
`status`, y OpenAPI sólo sabe expresar «todos los campos, casi todos opcionales».
El frontend conserva ahí su unión escrita a mano —que es MÁS precisa que lo
generado— y el guard de la fase comprueba que cada variante suya siga existiendo
en el contrato generado. Sustituir un tipo bueno por uno peor porque es
automático sería cambiar un riesgo por otro.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB_ROOT = (BACKEND_ROOT.parent / "terraquantum-web").resolve()
DESTINO = WEB_ROOT / "types" / "backend-contracts.generated.ts"

#: Rutas cuyo contrato de respuesta interesa al frontend. Se emite el cierre
#: transitivo de sus esquemas, no el catálogo entero: `components.schemas` trae
#: también modelos de entrada del motor que ningún cliente ve, y un archivo
#: generado que nadie lee es ruido que envejece.
RUTAS_DEL_CABLE = (
    # ── superficie de sistema (los 5 endpoints que la Fase 9 dejó nombrados) ──
    "/health",
    "/system-status",
    "/system/connectivity",
    "/license/status",
    "/license/activate",
    "/diagnostics/manifest",
    # ── camino dorado: ingesta ────────────────────────────────────────────────
    "/v2/gravity-import/analyze-columns",
    "/v2/gravity-import/parse-rows",
    "/v2/gravity-import/enrich-package",
    "/v2/gravity-import/load-package",
    "/gravity-import/preview",
    "/gravity-import/invert",
    # ── camino dorado: inversión, modelo y diagnóstico ────────────────────────
    "/geophysics-invert",
    "/v2/geophysics-invert",
    "/geophysics-status/{project_id}/{run_id}",
    "/geophysics-misfit/{project_id}/{run_id}",
    "/v2/geophysics-convergence/{project_id}/{run_id}",
    "/block-model",
    # ── historial y gabinete ──────────────────────────────────────────────────
    "/v2/history/runs",
    "/v2/history/runs/{project_id}/{run_id}",
    "/gravity-corrections/apply",
    "/multimodal/plan",
    "/borehole/parse-csv",
    "/borehole/parse-csv-file",
)

CABECERA = """\
// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  ARCHIVO GENERADO — NO EDITAR A MANO                                     ║
// ╚══════════════════════════════════════════════════════════════════════════╝
//
// Fase 10 (H-16). Lo produce el backend a partir del esquema OpenAPI que FastAPI
// publica, con:
//
//     cd terraquantum-backend
//     python scripts/ci/generate_frontend_types.py
//
// Si editas esto a mano, el `--check` de la CI lo revierte con un rojo. Y ése es
// el punto de la fase: **el contrato tiene un solo dueño, y es el backend**.
// Antes había 209 tipos escritos a mano en el frontend copiando esquemas
// Pydantic; cuando el backend cambiaba un campo, no fallaba nada — el usuario
// veía un dato vacío semanas después.
//
// QUÉ ES CADA COSA:
//  · Un `[key: string]: unknown` significa que el modelo Pydantic lleva
//    `extra="allow"`: el endpoint emite además campos que el contrato no fija.
//    Está declarado porque es verdad, no por comodidad.
//  · Un campo `?` es opcional EN EL CONTRATO: el backend puede no mandarlo.
//    Comprobarlo antes de usarlo no es defensivo, es leer el contrato.
//
// LO QUE ESTE ARCHIVO NO SUSTITUYE: las uniones discriminadas escritas a mano en
// `lib/terraquantum/frontendApi.ts` (p. ej. `LoadPackageResult` por `status`).
// OpenAPI no las expresa y son MÁS precisas que lo generado; un test del backend
// comprueba que sus variantes sigan existiendo aquí.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Esquema → TypeScript
# ─────────────────────────────────────────────────────────────────────────────

def _nombre_ref(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _ts_tipo(esquema: dict, requeridos_ref: set[str]) -> str:
    """Traduce un (sub)esquema de OpenAPI a una expresión de tipo TypeScript."""
    if not esquema:
        return "unknown"

    if "$ref" in esquema:
        nombre = _nombre_ref(esquema["$ref"])
        requeridos_ref.add(nombre)
        return nombre

    if "anyOf" in esquema or "oneOf" in esquema:
        partes = esquema.get("anyOf") or esquema.get("oneOf")
        vistos: list[str] = []
        for p in partes:
            t = _ts_tipo(p, requeridos_ref)
            if t not in vistos:
                vistos.append(t)
        return " | ".join(vistos) if vistos else "unknown"

    if "allOf" in esquema:
        partes = [_ts_tipo(p, requeridos_ref) for p in esquema["allOf"]]
        return " & ".join(partes) if partes else "unknown"

    if "const" in esquema:
        return json.dumps(esquema["const"])

    if "enum" in esquema:
        return " | ".join(json.dumps(v) for v in esquema["enum"])

    tipo = esquema.get("type")
    if tipo == "array":
        interno = _ts_tipo(esquema.get("items", {}), requeridos_ref)
        # Paréntesis obligatorios: `A | B[]` no es `(A | B)[]`.
        return f"({interno})[]" if "|" in interno or "&" in interno else f"{interno}[]"
    if tipo == "object":
        props = esquema.get("properties")
        if props:
            return _ts_objeto_inline(esquema, requeridos_ref)
        extra = esquema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {_ts_tipo(extra, requeridos_ref)}>"
        return "Record<string, unknown>"
    if tipo == "string":
        return "string"
    if tipo in ("integer", "number"):
        return "number"
    if tipo == "boolean":
        return "boolean"
    if tipo == "null":
        return "null"
    if isinstance(tipo, list):
        return " | ".join(_ts_tipo({"type": t}, requeridos_ref) for t in tipo)
    return "unknown"


def _clave_ts(nombre: str) -> str:
    """Comilla la clave si no es un identificador JS válido."""
    return nombre if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", nombre) else json.dumps(nombre)


def _ts_objeto_inline(esquema: dict, requeridos_ref: set[str]) -> str:
    req = set(esquema.get("required", []))
    campos = []
    for nombre, sub in (esquema.get("properties") or {}).items():
        opt = "" if nombre in req else "?"
        campos.append(f"{_clave_ts(nombre)}{opt}: {_ts_tipo(sub, requeridos_ref)}")
    if esquema.get("additionalProperties") is True:
        campos.append("[key: string]: unknown")
    return "{ " + "; ".join(campos) + " }"


def _comentario(texto: str | None, sangria: str = "") -> str:
    if not texto:
        return ""
    lineas = [l.rstrip() for l in texto.strip().split("\n")]
    if len(lineas) == 1:
        return f"{sangria}/** {lineas[0]} */\n"
    cuerpo = "\n".join(f"{sangria} *{(' ' + l) if l else ''}" for l in lineas)
    return f"{sangria}/**\n{cuerpo}\n{sangria} */\n"


def _emitir_tipo(nombre: str, esquema: dict, requeridos_ref: set[str]) -> str:
    doc = _comentario(esquema.get("description"))
    props = esquema.get("properties")
    if not props:
        return f"{doc}export type {nombre} = {_ts_tipo(esquema, requeridos_ref)};\n"

    req = set(esquema.get("required", []))
    lineas = [f"{doc}export type {nombre} = {{"]
    for campo, sub in props.items():
        desc = sub.get("description")
        # Pydantic mete el título autogenerado ("Total Voxels") en todos los
        # campos; sólo se emite comentario si alguien escribió una descripción.
        if desc:
            lineas.append(_comentario(desc, "  ").rstrip("\n"))
        opt = "" if campo in req else "?"
        lineas.append(f"  {_clave_ts(campo)}{opt}: {_ts_tipo(sub, requeridos_ref)};")
    if esquema.get("additionalProperties") is True:
        lineas.append("  /** `extra=\"allow\"`: el endpoint emite además campos que el contrato no fija. */")
        lineas.append("  [key: string]: unknown;")
    lineas.append("};\n")
    return "\n".join(lineas)


# ─────────────────────────────────────────────────────────────────────────────
# Recolección: qué esquemas entran
# ─────────────────────────────────────────────────────────────────────────────

def _esquemas_de_respuesta(spec: dict) -> tuple[dict[str, str], set[str]]:
    """Devuelve ({ruta+método: nombre de esquema}, {semillas}) para RUTAS_DEL_CABLE."""
    mapa: dict[str, str] = {}
    semillas: set[str] = set()
    for ruta in RUTAS_DEL_CABLE:
        ops = spec.get("paths", {}).get(ruta)
        if ops is None:
            raise SystemExit(
                f"[fase10] La ruta '{ruta}' no existe en el OpenAPI.\n"
                "         O se renombró o se borró: actualiza RUTAS_DEL_CABLE.\n"
                "         (Esta lista es portante: no puede quedarse con nombres muertos.)"
            )
        for metodo, op in ops.items():
            sch = (op.get("responses", {}).get("200", {})
                     .get("content", {}).get("application/json", {}).get("schema"))
            if not sch:
                continue
            if "$ref" in sch:
                nombre = _nombre_ref(sch["$ref"])
                mapa[f"{metodo.upper()} {ruta}"] = nombre
                semillas.add(nombre)
            elif sch.get("type") == "array" and "$ref" in sch.get("items", {}):
                nombre = _nombre_ref(sch["items"]["$ref"])
                mapa[f"{metodo.upper()} {ruta}"] = f"{nombre}[]"
                semillas.add(nombre)
    return mapa, semillas


def _cierre_transitivo(spec: dict, semillas: set[str]) -> list[str]:
    todos = spec.get("components", {}).get("schemas", {})
    pendientes, vistos = list(semillas), set()
    while pendientes:
        n = pendientes.pop()
        if n in vistos or n not in todos:
            continue
        vistos.add(n)
        refs: set[str] = set()
        _emitir_tipo(n, todos[n], refs)
        pendientes.extend(r for r in refs if r not in vistos)
    return sorted(vistos)


def construir(spec: dict) -> str:
    mapa, semillas = _esquemas_de_respuesta(spec)
    nombres = _cierre_transitivo(spec, semillas)
    todos = spec["components"]["schemas"]

    partes = [CABECERA, "\n// ── Qué ruta devuelve qué ──────────────────────────────────────────────────\n//\n"]
    for clave in sorted(mapa):
        partes.append(f"//   {clave:52s} → {mapa[clave]}\n")
    partes.append(f"//\n// {len(nombres)} tipos, cierre transitivo de {len(semillas)} contratos de respuesta.\n\n")

    for n in nombres:
        refs: set[str] = set()
        partes.append(_emitir_tipo(n, todos[n], refs))
        partes.append("\n")
    return "".join(partes).rstrip("\n") + "\n"


def cargar_spec() -> dict:
    os.environ.setdefault("TQ_AUTH_ENABLED", "false")
    sys.path.insert(0, str(BACKEND_ROOT))
    import main  # noqa: PLC0415 — perezoso a propósito: monta la app entera
    return main.app.openapi()


def main_cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="No escribe: falla si el archivo del repositorio no coincide.")
    args = ap.parse_args()

    generado = construir(cargar_spec())

    if args.check:
        if not DESTINO.exists():
            print(f"[fase10] FALTA {DESTINO.relative_to(WEB_ROOT.parent)}")
            return 1
        actual = DESTINO.read_text(encoding="utf-8")
        if actual != generado:
            import difflib
            diff = list(difflib.unified_diff(
                actual.splitlines(), generado.splitlines(),
                fromfile="en el repositorio", tofile="lo que produce el backend HOY",
                lineterm="", n=2,
            ))
            print("[fase10] DERIVA DE CONTRATO: el backend cambió y los tipos del "
                  "frontend no.\n         Corre `python scripts/ci/generate_frontend_types.py` "
                  "y revisa qué se rompe al compilar.\n")
            print("\n".join(diff[:120]))
            if len(diff) > 120:
                print(f"... y {len(diff) - 120} líneas más de diferencia.")
            return 1
        print(f"[fase10] OK — los tipos generados están al día ({len(generado.splitlines())} líneas).")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(generado, encoding="utf-8")
    print(f"[fase10] escrito {DESTINO} ({len(generado.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
