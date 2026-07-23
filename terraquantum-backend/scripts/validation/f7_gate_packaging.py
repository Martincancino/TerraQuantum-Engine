"""F7 — Gate del empaque local-first + licencias.

Verifica, sin instalar nada ni tocar la red, que las garantías de F7 se cumplen:

  1) Directorio de datos PORTABLE (TERRAQUANTUM_DATA_DIR mueve todo lo de usuario).
  2) Licenciamiento Ed25519 offline: firma/verifica/activa; rechaza vencida,
     firma alterada y otro producto; sin licencia = local libre (nunca bloquea).
  3) Tiers: free limita vóxeles; local/pro sin límite.
  4) Diagnóstico: bundle SOLO de metadatos, sin datos de survey ni secretos.
  5) Honestidad offline: camino dorado offline; ninguna feature de red es requisito.
  6) Plan B: launcher de un clic + doc de empaque presentes.

Uso:
    python scripts/validation/f7_gate_packaging.py

Salida: cada check con [PASS]/[FAIL] y un veredicto final. Código de salida 0 = PASS.
"""
import importlib
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

_checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _checks.append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))


# ── 1) Directorio de datos portable ───────────────────────────────────────────

def gate_data_dir() -> None:
    print("\n[1] Directorio de datos portable")
    tmp = Path(os.environ.get("TEMP", "/tmp")) / "tq_f7_gate_data"
    os.environ["TERRAQUANTUM_DATA_DIR"] = str(tmp)
    try:
        from core import config as cfg
        importlib.reload(cfg)
        check("TERRAQUANTUM_DATA_DIR redirige DATA_DIR", cfg.DATA_DIR == tmp, str(cfg.DATA_DIR))
        check("proyectos siguen a los datos", cfg.PROJECTS_DIR == tmp / "projects")
        check("licencia sigue a los datos", cfg.TQ_LICENSE_FILE == tmp / "license.key")
        check("api keys siguen a los datos", cfg.TQ_API_KEYS_DB == tmp / "api_keys.db")
        check("assets de instalación NO se mueven", cfg.MODELS_DIR == cfg.BASE_DIR / "public" / "models")
    finally:
        os.environ.pop("TERRAQUANTUM_DATA_DIR", None)
        from core import config as cfg
        importlib.reload(cfg)
        check("default vuelve a <repo>/data sin env var", cfg.DATA_DIR == cfg.BASE_DIR / "data")


# ── 2 y 3) Licenciamiento + tiers ──────────────────────────────────────────────

def gate_license() -> None:
    print("\n[2] Licenciamiento Ed25519 offline")
    from core import license_service as ls

    priv, pub = ls.generate_keypair()
    now = datetime.now(timezone.utc)

    def payload(tier="pro", days=30, product="terraquantum"):
        exp = None if days is None else (now + timedelta(days=days)).isoformat()
        return {"product": product, "licensee": "Gate", "tier": tier,
                "issued_at": now.isoformat(), "expires_at": exp}

    tok_pro = ls.sign_license(payload("pro"), priv)
    check("licencia válida verifica (pro)", ls.verify_license(tok_pro, pub, product="terraquantum").valid)
    check("perpetua verifica", ls.verify_license(ls.sign_license(payload("pro", days=None), priv), pub, product="terraquantum").valid)

    st_exp = ls.verify_license(ls.sign_license(payload(days=-1), priv), pub, product="terraquantum")
    check("vencida rechazada", (not st_exp.valid) and st_exp.expired)

    tampered = tok_pro[:-4] + ("AAAA" if not tok_pro.endswith("AAAA") else "BBBB")
    check("firma alterada rechazada", not ls.verify_license(tampered, pub, product="terraquantum").valid)

    st_wp = ls.verify_license(ls.sign_license(payload(product="otro"), priv), pub, product="terraquantum")
    check("otro producto rechazado", not st_wp.valid)

    check("sin token = local libre", ls.verify_license("", pub, product="terraquantum").tier == ls.LOCAL_TIER)
    check("sin emisor = local libre", ls.verify_license(tok_pro, "", product="terraquantum").tier == ls.LOCAL_TIER)

    print("\n[3] Tiers y presupuesto de vóxeles")
    import core.config as config
    orig_tok = config.TQ_LICENSE_TOKEN
    orig_pub = config.TQ_LICENSE_PUBLIC_KEY_HEX
    try:
        config.TQ_LICENSE_TOKEN = ""
        config.TQ_LICENSE_PUBLIC_KEY_HEX = ""
        check("local: sin límite de vóxeles", ls.check_voxel_budget(1_000_000)["allowed"])

        config.TQ_LICENSE_TOKEN = ls.sign_license(payload("free"), priv)
        config.TQ_LICENSE_PUBLIC_KEY_HEX = pub
        maxv = config.TQ_TIER_LIMITS["free"]["max_voxels"]
        check("free: permite hasta el tope", ls.check_voxel_budget(maxv)["allowed"])
        check("free: bloquea sobre el tope", not ls.check_voxel_budget(maxv + 1)["allowed"])
        check("free: activa marca de agua", config.TQ_TIER_LIMITS["free"]["watermark"] is True)
    finally:
        config.TQ_LICENSE_TOKEN = orig_tok
        config.TQ_LICENSE_PUBLIC_KEY_HEX = orig_pub


# ── 4) Diagnóstico sin datos ────────────────────────────────────────────────────

def gate_diagnostics() -> None:
    print("\n[4] Exportar diagnóstico (sin datos de survey ni secretos)")
    import core.config as config
    from core import diagnostics_buffer
    from services import diagnostics_service as ds

    sentinel = "GATE_SECRET_c0ffee"
    config.TQ_MASTER_KEY = sentinel
    diagnostics_buffer.clear()
    diagnostics_buffer.record_error("/geophysics-invert", "ValueError", "boom")

    tmp = Path(os.environ.get("TEMP", "/tmp"))
    z = ds.build_diagnostic_zip(dest_dir=tmp)
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        blob = " ".join(zf.read(n).decode("utf-8", "ignore") for n in names)

    expected = {"README.txt", "system.json", "packages.txt", "config.json",
                "connectivity.json", "license.json", "recent_errors.json"}
    check("bundle = solo metadatos fijos", names == expected, str(sorted(names)))
    data_exts = (".parquet", ".csv", ".db", ".npy", ".npz", ".glb", ".vtu", ".vtr", ".tqpkg")
    check("cero archivos de datos en el ZIP", not any(n.lower().endswith(data_exts) for n in names))
    check("no filtra el secreto sembrado", sentinel not in blob)
    check("captura el último error (path+tipo+traceback)", "valueerror" in blob.lower())


# ── 5) Honestidad offline ───────────────────────────────────────────────────────

def gate_offline() -> None:
    print("\n[5] Honestidad offline")
    from services.connectivity_service import connectivity_summary
    s = connectivity_summary()
    check("camino dorado offline", s["golden_path_offline"] is True)
    check("no toca la red por defecto", s["probed"] is False)
    reqs = [f for f in s["online_features"] if f["requires_internet"] and f["required_for_golden_path"]]
    check("ninguna feature de red es requisito del camino dorado", len(reqs) == 0)
    igrf = next(f for f in s["online_features"] if f["key"] == "igrf")
    check("IGRF offline y requerido", (not igrf["requires_internet"]) and igrf["required_for_golden_path"])


# ── 6) Plan B ────────────────────────────────────────────────────────────────────

def gate_planb() -> None:
    print("\n[6] Plan B: launcher + documentación")
    launcher = REPO_ROOT / "run_terraquantum_desktop.ps1"
    doc = REPO_ROOT / "docs" / "04_EMPAQUE_LOCAL_FIRST.md"
    minter = BACKEND_ROOT / "scripts" / "mint_license.py"
    check("launcher de un clic presente", launcher.exists(), str(launcher.name))
    check("doc de empaque presente", doc.exists(), str(doc.name))
    check("CLI de emisión de licencias presente", minter.exists(), str(minter.name))
    if launcher.exists():
        txt = launcher.read_text(encoding="utf-8", errors="ignore")
        check("launcher fija TERRAQUANTUM_DATA_DIR a %APPDATA%", "TERRAQUANTUM_DATA_DIR" in txt and "APPDATA" in txt)
        check("launcher no toca los .bat existentes", "start-terraquantum.bat" not in txt.replace("NO reemplaza a start-terraquantum.bat", ""))


def main() -> int:
    print("=" * 64)
    print("  GATE F7 — Empaque local-first + licencias")
    print("=" * 64)

    gate_data_dir()
    gate_license()
    gate_diagnostics()
    gate_offline()
    gate_planb()

    passed = sum(1 for _, ok, _ in _checks if ok)
    total = len(_checks)
    print("\n" + "=" * 64)
    verdict = "PASS" if passed == total else "FAIL"
    print(f"  VEREDICTO F7: {verdict}  ({passed}/{total} checks)")
    print("=" * 64)
    if passed != total:
        print("\nChecks fallidos:")
        for name, ok, detail in _checks:
            if not ok:
                print(f"  - {name}" + (f" ({detail})" if detail else ""))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
