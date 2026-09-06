#!/usr/bin/env python3
"""Construye el `latest.json` que lee `tauri-plugin-updater` (Fase 28, H-20).

El bundler de Tauri produce el instalador y su `.sig`, pero **NO** produce el
manifiesto: hay que escribirlo. Medido el 2026-09-05 sobre
`terraquantum-web/src-tauri/target/release/bundle/nsis/`, que contenía
exactamente `TerraQuantum_0.2.0_x64-setup.exe` y `TerraQuantum_0.2.0_x64-setup.exe.sig`.

Sólo biblioteca estándar, por la misma razón que `scripts/ci/gen_lockfile.py`:
una dependencia nueva exige permiso expreso.

═══ El contrato, leído del crate (tauri-plugin-updater 2.10.1) ═══════════════

`InnerRemoteRelease` (`src/updater.rs:1388-1398`) y `ReleaseManifestPlatform`
(`:71-77`):

  · `version`   OBLIGATORIO. `parse_version` (`:1443-1450`) quita una `v` inicial
                y exige semver COMPLETO: `0.2.1` vale, `0.2` no.
  · `platforms` mapa `{os}-{arch}` -> `{url, signature}`.
  · `notes`, `pub_date` opcionales; si `pub_date` está, ha de ser RFC3339
                ESTRICTO o falla el manifiesto entero (`:1402-1409`).

La clave de plataforma es **`windows-x86_64`**, no `windows-x86_64-nsis`:
`get_urls` (`:568-598`) prueba `{os}-{arch}-{installer}` sólo cuando el binario
lleva el marcador de bundle. Un `app.exe` de `cargo` no lo lleva (medido:
`__TAURI_BUNDLE_TYPE_VAR_UNK`), así que si el manifiesto sólo trajera la clave
con `-nsis`, la comprobación funcionaría en el instalador y fallaría en
desarrollo. Con `windows-x86_64` funcionan los dos.

Y una trampa de orden que decide el diseño de este fichero: `get_urls` se llama
**ANTES** de comparar versiones (`:536` frente a `:538`). Un manifiesto sin la
clave de esta plataforma no produce «ya estás al día»: produce
`Err(TargetsNotFound)`. Por eso aquí la plataforma no es opcional.

`signature` es el CONTENIDO ENTERO del `.sig`, tal cual, no una ruta.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# semver estricto: lo que acepta `semver::Version::from_str` tras quitar la `v`.
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

PLATFORM = "windows-x86_64"


def build(version: str, url: str, signature: str, notes: str, pub_date: str) -> dict:
    v = version.lstrip("v")
    if not SEMVER.match(v):
        raise SystemExit(
            f"version '{version}' no es semver completo. El plugin la parsea con "
            f"semver::Version y '0.2' o 'v0.2' fallan; usa '0.2.0'."
        )
    if not url.startswith("https://"):
        raise SystemExit(f"la URL de descarga tiene que ser https: {url}")
    if not signature.strip():
        raise SystemExit(
            "la firma está vacía: el `.sig` no se generó. Sin "
            "TAURI_SIGNING_PRIVATE_KEY el bundler avisa "
            "(«A public key has been found, but no private key»)."
        )
    manifest = {
        "version": v,
        "platforms": {PLATFORM: {"url": url, "signature": signature.strip()}},
    }
    if notes:
        manifest["notes"] = notes
    if pub_date:
        # RFC3339 estricto; el plugin rechaza el manifiesto ENTERO si no lo es.
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$", pub_date):
            raise SystemExit(f"pub_date '{pub_date}' no es RFC3339 estricto")
        manifest["pub_date"] = pub_date
    return manifest


def validate(manifest: dict) -> list[str]:
    """Las mismas reglas, aplicadas a un manifiesto ya escrito.

    Es lo que corre el gate: si el generador se desincroniza del contrato del
    crate, esto lo dice en vez de descubrirlo un usuario con un aviso roto.
    """
    problemas: list[str] = []
    v = str(manifest.get("version", ""))
    if not v:
        problemas.append("falta `version`, que es el único campo obligatorio")
    elif not SEMVER.match(v.lstrip("v")):
        problemas.append(f"`version` = '{v}' no es semver completo")
    plats = manifest.get("platforms")
    if not isinstance(plats, dict) or not plats:
        problemas.append("falta `platforms`")
    elif PLATFORM not in plats:
        problemas.append(
            f"`platforms` no trae '{PLATFORM}' (trae {sorted(plats)}); "
            f"get_urls corre antes de comparar versiones, así que esto no da "
            f"«al día» sino TargetsNotFound"
        )
    else:
        p = plats[PLATFORM]
        if not str(p.get("url", "")).startswith("https://"):
            problemas.append(f"`{PLATFORM}.url` no es https")
        if not str(p.get("signature", "")).strip():
            problemas.append(f"`{PLATFORM}.signature` vacía")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", help="versión publicada, p. ej. 0.3.0")
    ap.add_argument("--url", help="URL https del instalador NSIS")
    ap.add_argument("--signature-file", type=Path, help="el .sig producido por el bundler")
    ap.add_argument("--notes", default="")
    ap.add_argument("--pub-date", default="", help="RFC3339 estricto, o vacío")
    ap.add_argument("--out", type=Path, help="dónde escribir latest.json")
    ap.add_argument("--validate", type=Path, help="valida un latest.json existente y sale")
    args = ap.parse_args()

    if args.validate:
        # `utf-8-sig`, no `utf-8`: en Windows es facilísimo producir el fichero
        # con BOM (`Set-Content -Encoding utf8` de PowerShell 5.1 lo pone), y
        # `json.loads` revienta con un traceback en la primera columna. Medido:
        # los tres controles negativos del gate estaban pasando **por ese
        # traceback**, no por el diagnóstico — un exit 1 es un exit 1.
        manifest = json.loads(args.validate.read_text(encoding="utf-8-sig"))
        problemas = validate(manifest)
        for p in problemas:
            print(f"  X {p}")
        if problemas:
            return 1
        print(f"  OK {args.validate} cumple el contrato del plugin")
        return 0

    faltan = [n for n, v in
              (("--version", args.version), ("--url", args.url),
               ("--signature-file", args.signature_file), ("--out", args.out)) if not v]
    if faltan:
        ap.error("faltan " + ", ".join(faltan))

    if not args.signature_file.exists():
        raise SystemExit(
            f"no existe {args.signature_file}. El bundler sólo emite el .sig si "
            f"`bundle.createUpdaterArtifacts` es true Y hay clave de firma."
        )
    manifest = build(
        args.version,
        args.url,
        args.signature_file.read_text(encoding="utf-8"),
        args.notes,
        args.pub_date,
    )
    problemas = validate(manifest)
    if problemas:  # cinturón y tirantes: nunca publicar un manifiesto inválido
        for p in problemas:
            print(f"  X {p}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  OK {args.out} -> version {manifest['version']}, plataforma {PLATFORM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
