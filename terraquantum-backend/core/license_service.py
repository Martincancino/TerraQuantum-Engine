"""F7 — Licenciamiento local-first (Ed25519, offline, sin servidor de activación).

Una licencia de TerraQuantum es un token compacto y firmado que el backend
verifica EN LA MÁQUINA del cliente, sin llamar a ningún servidor. Contiene qué
producto, para quién, qué tier y hasta cuándo; su firma Ed25519 impide que se
altere. La clave PRIVADA (que firma) vive solo en la máquina del emisor (Martín)
y jamás entra al repo; la clave PÚBLICA (que verifica) se distribuye con la app.

Formato del token (una sola línea, apto para pegar en un archivo o env var):

    tqlic1.<b64url(payload_json)>.<b64url(firma_ed25519)>

`payload_json` = objeto JSON con al menos: product, licensee, tier, issued_at,
expires_at (ISO-8601 UTC, o null = perpetua). La firma se calcula sobre los
BYTES EXACTOS del segmento `<b64url(payload_json)>` (sin ambigüedad de
canonicalización).

Regla dura del producto (principio local-first): SIN emisor configurado o SIN
licencia válida, el backend corre en modo **local libre** (`tier="local"`, sin
límites) — la instalación propia NUNCA se castiga. Los tiers con límites
(p.ej. `free`) solo aplican cuando una licencia los declara. Todas las funciones
de estado son a prueba de fallos: ante cualquier error devuelven un estado
válido, jamás lanzan hacia el caller (el licenciamiento no puede tumbar el
arranque ni el camino dorado).

Sin dependencias nuevas: `cryptography` ya está en requirements.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core.logging import get_logger

_log = get_logger(__name__)

TOKEN_PREFIX = "tqlic1"
LOCAL_TIER = "local"


# ── Codificación base64url sin relleno (compacta, segura para env/archivo) ────

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


# ── Claves ────────────────────────────────────────────────────────────────────

def generate_keypair() -> tuple[str, str]:
    """Genera un par Ed25519. Devuelve (private_hex, public_hex).

    El emisor guarda `private_hex` en secreto (firma licencias) y publica
    `public_hex` (va en la app / env TQ_LICENSE_PUBLIC_KEY_HEX).
    """
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes_raw().hex()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    return priv_hex, pub_hex


def public_key_for(private_hex: str) -> str:
    """Deriva la clave pública hex desde la privada hex."""
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    return priv.public_key().public_bytes_raw().hex()


# ── Firmar (offline, lado emisor) ──────────────────────────────────────────────

def sign_license(payload: Dict[str, Any], private_key_hex: str) -> str:
    """Firma un payload de licencia y devuelve el token `tqlic1.…`.

    Uso: `scripts/mint_license.py`. Requiere la clave privada del emisor.
    """
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
    payload_seg = _b64e(payload_json)
    sig = priv.sign(payload_seg.encode("ascii"))
    return f"{TOKEN_PREFIX}.{payload_seg}.{_b64e(sig)}"


# ── Verificar (lado cliente, offline) ──────────────────────────────────────────

@dataclass
class LicenseStatus:
    valid: bool
    tier: str = LOCAL_TIER
    reason: str = ""
    licensee: Optional[str] = None
    product: Optional[str] = None
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    expired: bool = False
    source: str = "none"            # "env" | "file" | "none"
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "tier": self.tier,
            "reason": self.reason,
            "licensee": self.licensee,
            "product": self.product,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "expired": self.expired,
            "source": self.source,
        }


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def verify_license(
    token: str,
    public_key_hex: str,
    *,
    product: str,
    now: Optional[datetime] = None,
    source: str = "none",
) -> LicenseStatus:
    """Verifica firma, producto y expiración. NUNCA lanza: siempre devuelve un
    LicenseStatus (inválido → tier local, con la razón en español)."""
    now = now or datetime.now(timezone.utc)

    if not token or not token.strip():
        return LicenseStatus(valid=False, reason="Sin licencia (modo local libre).", source=source)
    if not public_key_hex or not public_key_hex.strip():
        return LicenseStatus(valid=False, reason="Sin emisor configurado (modo local libre).", source=source)

    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return LicenseStatus(valid=False, reason="Formato de licencia no reconocido.", source=source)

    _, payload_seg, sig_seg = parts

    # Firma.
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex.strip()))
        pub.verify(_b64d(sig_seg), payload_seg.encode("ascii"))
    except InvalidSignature:
        return LicenseStatus(valid=False, reason="Firma de licencia inválida (no emitida por el proveedor).", source=source)
    except Exception as exc:  # noqa: BLE001 — clave/segmento corrupto
        return LicenseStatus(valid=False, reason=f"Licencia ilegible: {exc}", source=source)

    # Payload.
    try:
        payload = json.loads(_b64d(payload_seg).decode("utf-8"))
        assert isinstance(payload, dict)
    except Exception:  # noqa: BLE001
        return LicenseStatus(valid=False, reason="Contenido de licencia corrupto.", source=source)

    lic_product = str(payload.get("product", ""))
    tier = str(payload.get("tier") or LOCAL_TIER)
    licensee = payload.get("licensee")
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")

    # Producto.
    if lic_product != product:
        return LicenseStatus(
            valid=False, reason=f"Licencia de otro producto ('{lic_product}').",
            product=lic_product, tier=LOCAL_TIER, source=source, payload=payload,
        )

    # Expiración (null = perpetua).
    exp_dt = _parse_iso(expires_at)
    if exp_dt is not None and now > exp_dt:
        return LicenseStatus(
            valid=False, tier=LOCAL_TIER, expired=True,
            reason=f"Licencia vencida el {expires_at}. Renueva para reactivar tu tier.",
            licensee=licensee, product=lic_product, issued_at=issued_at,
            expires_at=expires_at, source=source, payload=payload,
        )

    return LicenseStatus(
        valid=True, tier=tier, reason="Licencia válida.",
        licensee=licensee, product=lic_product, issued_at=issued_at,
        expires_at=expires_at, source=source, payload=payload,
    )


# ── Estado activo (producción, resuelve config) ────────────────────────────────

def read_active_token() -> tuple[str, str]:
    """Devuelve (token, source). Prioridad: env TQ_LICENSE → archivo de licencia."""
    from core import config

    if config.TQ_LICENSE_TOKEN and config.TQ_LICENSE_TOKEN.strip():
        return config.TQ_LICENSE_TOKEN.strip(), "env"
    try:
        path: Path = config.TQ_LICENSE_FILE
        if path.exists():
            txt = path.read_text(encoding="utf-8").strip()
            if txt:
                return txt, "file"
    except Exception as exc:  # noqa: BLE001
        _log.warning("license_file_read_failed", error=str(exc))
    return "", "none"


def get_license_status() -> Dict[str, Any]:
    """Estado de licencia listo para JSON, con límites del tier. A prueba de
    fallos: cualquier problema degrada a modo local libre."""
    from core import config

    try:
        token, source = read_active_token()
        status = verify_license(
            token,
            config.TQ_LICENSE_PUBLIC_KEY_HEX,
            product=config.TQ_LICENSE_PRODUCT,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("license_status_failed", error=str(exc))
        status = LicenseStatus(valid=False, reason="No se pudo evaluar la licencia; modo local libre.")

    effective_tier = status.tier if status.valid else LOCAL_TIER
    out = status.to_dict()
    out["effective_tier"] = effective_tier
    out["limits"] = tier_limits(effective_tier)
    out["mode"] = "licensed" if status.valid else "local_free"
    return out


def tier_limits(tier: str) -> Dict[str, Any]:
    from core import config

    return dict(config.TQ_TIER_LIMITS.get(tier, config.TQ_TIER_LIMITS[LOCAL_TIER]))


def activate_license(token: str) -> Dict[str, Any]:
    """Verifica el token y, si es válido, lo persiste en el archivo de licencia
    del directorio de datos. Devuelve el estado resultante. Nunca lanza."""
    from core import config

    status = verify_license(
        token or "",
        config.TQ_LICENSE_PUBLIC_KEY_HEX,
        product=config.TQ_LICENSE_PRODUCT,
        source="file",
    )
    result = status.to_dict()
    result["effective_tier"] = status.tier if status.valid else LOCAL_TIER
    result["limits"] = tier_limits(result["effective_tier"])
    if not status.valid:
        result["activated"] = False
        return result
    try:
        path: Path = config.TQ_LICENSE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token.strip() + "\n", encoding="utf-8")
        result["activated"] = True
    except Exception as exc:  # noqa: BLE001
        _log.warning("license_activate_write_failed", error=str(exc))
        result["activated"] = False
        result["reason"] = f"Licencia válida pero no se pudo guardar: {exc}"
    return result


def check_voxel_budget(n_voxels: int) -> Dict[str, Any]:
    """¿El tier activo permite una corrida de `n_voxels`? Nunca lanza.

    Modo local/pro: siempre permitido. Tier free: limitado con mensaje honesto.
    Devuelve `allowed` + `max_voxels` + `reason`.
    """
    status = get_license_status()
    limits = status.get("limits", {})
    max_vox = limits.get("max_voxels")
    if max_vox is None or n_voxels <= max_vox:
        return {"allowed": True, "tier": status.get("effective_tier"),
                "max_voxels": max_vox, "n_voxels": n_voxels, "reason": ""}
    return {
        "allowed": False,
        "tier": status.get("effective_tier"),
        "max_voxels": max_vox,
        "n_voxels": n_voxels,
        "reason": (
            f"El tier '{status.get('effective_tier')}' permite hasta {max_vox:,} "
            f"vóxeles; esta corrida pide {n_voxels:,}. Reduce la resolución o "
            "activa una licencia sin límite."
        ),
    }
