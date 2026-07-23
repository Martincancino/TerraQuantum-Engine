"""F7 — Emisión OFFLINE de licencias TerraQuantum (Ed25519).

Esta herramienta la corre SOLO el emisor (Martín) en su máquina. La clave
privada nunca sale de aquí ni entra al repo.

1) Generar el par de claves (una vez):

       python scripts/mint_license.py genkey --out-private tq_private.hex

   Imprime la clave PÚBLICA (hex). Pégala en el despliegue como
   TQ_LICENSE_PUBLIC_KEY_HEX=<hex> (env) o en la config del instalador. Guarda
   `tq_private.hex` en un lugar seguro y FUERA del repo.

2) Firmar una licencia para un cliente:

       python scripts/mint_license.py sign \
           --private-key-file tq_private.hex \
           --licensee "Consultora Geofísica SpA" \
           --tier pro --days 365

   Imprime el token `tqlic1.…`. El cliente lo pega en la app (Activar licencia)
   o se coloca como TQ_LICENSE / archivo license.key.

Tiers válidos: local (default sin licencia, sin límite), free (tope de vóxeles
+ marca de agua), pro (sin límite). Ver core/config.TQ_TIER_LIMITS.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Permitir ejecutar como `python scripts/mint_license.py` desde la raíz backend.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import license_service  # noqa: E402


def _cmd_genkey(args: argparse.Namespace) -> int:
    priv_hex, pub_hex = license_service.generate_keypair()
    if args.out_private:
        out = Path(args.out_private)
        out.write_text(priv_hex + "\n", encoding="utf-8")
        print(f"[OK] Clave privada guardada en: {out.resolve()}")
        print("     GUÁRDALA EN SECRETO. No la subas al repo.")
    else:
        print("CLAVE PRIVADA (guárdala en secreto):")
        print(priv_hex)
    print()
    print("CLAVE PÚBLICA (despliégala como TQ_LICENSE_PUBLIC_KEY_HEX):")
    print(pub_hex)
    return 0


def _cmd_sign(args: argparse.Namespace) -> int:
    if args.private_key_file:
        priv_hex = Path(args.private_key_file).read_text(encoding="utf-8").strip()
    elif args.private_key:
        priv_hex = args.private_key.strip()
    else:
        print("ERROR: usa --private-key-file o --private-key", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    expires = None if args.days <= 0 else (now + timedelta(days=args.days)).isoformat()

    payload = {
        "product": license_service.__dict__.get("PRODUCT", "terraquantum"),
        "licensee": args.licensee,
        "tier": args.tier,
        "issued_at": now.isoformat(),
        "expires_at": expires,
    }
    # El producto canónico vive en config; lo fijamos explícito para no depender
    # de importar toda la config aquí.
    payload["product"] = "terraquantum"

    token = license_service.sign_license(payload, priv_hex)
    # Sanidad: re-verifica con la pública derivada antes de entregar.
    pub_hex = license_service.public_key_for(priv_hex)
    check = license_service.verify_license(token, pub_hex, product="terraquantum")
    if not check.valid:
        print(f"ERROR interno: la licencia firmada no verifica: {check.reason}", file=sys.stderr)
        return 1

    print(f"[OK] Licencia para '{args.licensee}' tier={args.tier} "
          f"expira={'perpetua' if expires is None else expires}")
    print()
    print(token)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Emisión offline de licencias TerraQuantum (Ed25519).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("genkey", help="Genera un par de claves Ed25519.")
    p_gen.add_argument("--out-private", help="Ruta donde guardar la clave privada hex.")
    p_gen.set_defaults(func=_cmd_genkey)

    p_sign = sub.add_parser("sign", help="Firma una licencia para un cliente.")
    p_sign.add_argument("--private-key-file", help="Archivo con la clave privada hex.")
    p_sign.add_argument("--private-key", help="Clave privada hex en línea (alternativa).")
    p_sign.add_argument("--licensee", required=True, help="Nombre del cliente.")
    p_sign.add_argument("--tier", default="pro", choices=["local", "free", "pro"])
    p_sign.add_argument("--days", type=int, default=365,
                        help="Días de validez (<=0 = perpetua).")
    p_sign.set_defaults(func=_cmd_sign)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
