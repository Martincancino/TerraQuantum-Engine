# -*- coding: utf-8 -*-
"""GATE F8 — Tormenta de pruebas: validación TRANSVERSAL del producto entero.

Corre bajo demanda (NO en cada commit) las cuatro patas de F8 y emite un
veredicto medido + reporte JSON:

  1. MATRIZ E2E  {física} × {suciedad} × {tamaño} × {geo/Helmert} × {DEM} por el
     flujo real (enrich → load síncrono); cada combo ∈ {modelo_3d, error_catalogado}.
  2. SOAK        N inversiones consecutivas → RSS estable, historial SQLite íntegro.
  3. BUDGETS     ingesta 10k filas <5 s; inversión ~30k vóxeles <3 min (números del plan).
  4. FUZZ        subprocess pytest del fuzzer dep-free (nunca un 5xx pelado).

Uso (desde terraquantum-backend):
    python scripts/validation/f8_gate_storm.py            # subconjunto de cobertura (~20 combos)
    TQ_F8_FULL=1 python scripts/validation/f8_gate_storm.py   # barrido cartesiano completo (cientos)

Env: TQ_F8_SOAK_N (default 50), TQ_F8_INGEST_BUDGET_S (5), TQ_F8_INVERT_BUDGET_S (180),
     TQ_F8_INVERT_GRID (31 ≈ 30k vóxeles), TQ_F8_SKIP_FUZZ=1.

La CI/suite rápida vive en tests/test_f8_*.py; este script es el gate pesado.
"""
import gc
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

import tests.f8_storm_lib as L  # noqa: E402


def _hr(title: str) -> None:
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


# ─────────────────────────────────────────────────────────────────────────────
# 1. MATRIZ E2E
# ─────────────────────────────────────────────────────────────────────────────
def run_matrix(client) -> dict:
    full = os.environ.get("TQ_F8_FULL") == "1"
    combos = L.full_matrix() if full else L.covering_subset()
    sizes = L.SIZES_FULL if full else L.SIZES_FAST
    limit = int(os.environ.get("TQ_F8_MATRIX_LIMIT", "0"))  # 0 = sin límite; >0 = smoke
    if limit > 0:
        combos = combos[:limit]
    _hr(f"1/4 · MATRIZ E2E ({'COMPLETA' if full else 'cobertura'}) — {len(combos)} combos")

    counts: dict = {}
    bugs = []
    t0 = time.monotonic()
    for idx, c in enumerate(combos, 1):
        o = L.drive_e2e(client, c, side=sizes[c.size], grid=6)
        counts[o.outcome] = counts.get(o.outcome, 0) + 1
        tag = "OK " if o.ok else "BUG"
        if not o.ok:
            bugs.append({"combo": c.label(), "outcome": o.outcome, "stage": o.stage,
                         "http": o.http_status, "code": o.code, "detail": o.detail[:300]})
            print(f"  [{idx:>3}/{len(combos)}] {tag} {o.outcome:18s} :: {c.label()}")
            print(f"            -> {o.detail[:160]}")
        elif idx % 25 == 0 or not full:
            print(f"  [{idx:>3}/{len(combos)}] {tag} {o.outcome:18s} {str(o.code)[:26]:26s} :: {c.label()}")
    dt = time.monotonic() - t0

    passed = len(bugs) == 0
    print(f"\n  Resultado: {sum(counts.values()) - len(bugs)}/{sum(counts.values())} sin bug "
          f"· {dt:.0f}s · desglose={counts}")
    if bugs:
        print(f"  ❌ {len(bugs)} combos con BUG (crash/5xx/basura). Ver reporte.")
    return {"section": "matrix", "passed": passed, "n": len(combos),
            "counts": counts, "bugs": bugs, "seconds": round(dt, 1), "full": full}


# ─────────────────────────────────────────────────────────────────────────────
# 2. SOAK
# ─────────────────────────────────────────────────────────────────────────────
def run_soak(client) -> dict:
    import tracemalloc

    import psutil

    n = int(os.environ.get("TQ_F8_SOAK_N", "50"))
    mb_per_iter = float(os.environ.get("TQ_F8_SOAK_MB_PER_ITER", "4.0"))
    _hr(f"2/4 · SOAK — {n} inversiones consecutivas en el mismo proceso")

    proc = psutil.Process()
    gc.collect()
    tracemalloc.start()
    rss = []
    ok_runs = 0
    t0 = time.monotonic()
    for i in range(n):
        o = L.drive_e2e(client, L.Combo("grav", "clean", "small", "latlon", False),
                        side=L.SIZES_FAST["small"], grid=6,
                        project_id=f"f8_soak_{i}", run_id="soak")
        if o.outcome == "valid_3d_model":
            ok_runs += 1
        gc.collect()
        rss.append(proc.memory_info().rss / 1e6)
        if (i + 1) % 10 == 0:
            print(f"  iter {i+1:>3}/{n} · RSS={rss[-1]:.0f}MB · válidas={ok_runs}")
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    dt = time.monotonic() - t0

    k = max(1, n // 3)
    base = sum(rss[:k]) / k
    tail = sum(rss[-k:]) / k
    growth = (tail - base) / max(1, n - k)

    # Historial íntegro tras la ráfaga.
    L.reset_rate_limit()
    rh = client.get("/v2/history/runs")
    history_ok = rh.status_code == 200

    passed = growth < mb_per_iter and ok_runs >= n // 2 and history_ok
    print(f"\n  RSS +{growth:.2f} MB/iter (base={base:.0f} tail={tail:.0f}, umbral {mb_per_iter})"
          f" · tracemalloc peak={peak/1e6:.0f}MB · válidas={ok_runs}/{n} · historial={'OK' if history_ok else 'FALLO'}"
          f" · {dt:.0f}s")
    if not passed:
        print("  ❌ posible fuga de memoria o historial roto.")
    return {"section": "soak", "passed": passed, "n": n, "ok_runs": ok_runs,
            "rss_growth_mb_per_iter": round(growth, 3), "tracemalloc_peak_mb": round(peak / 1e6, 1),
            "history_ok": history_ok, "seconds": round(dt, 1)}


# ─────────────────────────────────────────────────────────────────────────────
# 3. BUDGETS (números del plan)
# ─────────────────────────────────────────────────────────────────────────────
def run_budgets(client) -> dict:
    ingest_budget = float(os.environ.get("TQ_F8_INGEST_BUDGET_S", "5"))
    invert_budget = float(os.environ.get("TQ_F8_INVERT_BUDGET_S", "180"))
    grid = int(os.environ.get("TQ_F8_INVERT_GRID", "31"))  # 31³ = 29 791 ≈ 30k
    _hr("3/4 · BUDGETS — ingesta 10k <5s · inversión ~30k vóxeles <3min")

    # Ingesta 10k filas.
    import math
    lines = ["lat,lon,elev_m,bouguer_anomaly,unit,gravity_type"]
    side = int(math.ceil(10_000 ** 0.5))
    count = 0
    for i in range(side):
        for j in range(side):
            if count >= 10_000:
                break
            lines.append(f"{-27.0 - i*0.0005:.4f},{-69.0 + j*0.0005:.4f},"
                         f"{1000.0 + i + j:.1f},{3.0 + ((i*j) % 7)*0.5:.3f},mGal,bouguer_anomaly")
            count += 1
    body = ("\n".join(lines) + "\n").encode("utf-8")
    L.reset_rate_limit()
    t0 = time.monotonic()
    r = client.post("/v2/gravity-import/enrich-package",
                    files={"gravity_file": ("perf10k.csv", body, "text/csv")},
                    params={"enable_dem": "false"})
    ingest_s = time.monotonic() - t0
    ingest_ok = r.status_code == 200 and ingest_s < ingest_budget
    print(f"  ingesta 10k filas = {ingest_s:.2f}s (presupuesto {ingest_budget}s) "
          f"[{'OK' if ingest_ok else 'FALLO'}]")

    # Inversión ~30k vóxeles.
    combo = L.Combo("grav", "clean", "medium", "latlon", False)
    t0 = time.monotonic()
    o = L.drive_e2e(client, combo, side=L.SIZES_FULL["medium"], grid=grid,
                    project_id="f8_budget_invert", run_id="perf")
    invert_s = time.monotonic() - t0
    invert_ok = o.ok and invert_s < invert_budget
    print(f"  inversión {grid**3} vóxeles = {invert_s:.1f}s (presupuesto {invert_budget}s) "
          f"[{'OK' if invert_ok else 'FALLO'}] outcome={o.outcome}")

    print("  render 100k celdas >30fps → DIFERIDO (Playwright / iteración UI E2E)")
    passed = ingest_ok and invert_ok
    return {"section": "budgets", "passed": passed,
            "ingest_seconds": round(ingest_s, 2), "ingest_budget": ingest_budget, "ingest_ok": ingest_ok,
            "invert_seconds": round(invert_s, 1), "invert_voxels": grid ** 3,
            "invert_budget": invert_budget, "invert_ok": invert_ok,
            "render_fps": "deferred_playwright"}


# ─────────────────────────────────────────────────────────────────────────────
# 4. FUZZ (subprocess pytest del fuzzer dep-free)
# ─────────────────────────────────────────────────────────────────────────────
def run_fuzz() -> dict:
    _hr("4/4 · FUZZ — pytest del fuzzer de API (nunca un 5xx pelado)")
    if os.environ.get("TQ_F8_SKIP_FUZZ") == "1":
        print("  (saltado por TQ_F8_SKIP_FUZZ=1)")
        return {"section": "fuzz", "passed": True, "skipped": True}
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_f8_api_fuzz.py", "-p", "no:cacheprovider"],
        cwd=str(BACKEND), capture_output=True, text=True, timeout=1200,
    )
    dt = time.monotonic() - t0
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    for ln in tail:
        print("  " + ln)
    passed = proc.returncode == 0
    if not passed:
        print(f"  ❌ fuzzer falló (rc={proc.returncode}). stderr:\n{(proc.stderr or '')[-800:]}")
    return {"section": "fuzz", "passed": passed, "returncode": proc.returncode,
            "seconds": round(dt, 1), "summary": tail[-1] if tail else ""}


def main() -> int:
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    print("GATE F8 — Tormenta de pruebas (validación transversal)")
    sections = [run_matrix(client), run_soak(client), run_budgets(client), run_fuzz()]

    _hr("VEREDICTO F8")
    n_ok = sum(1 for s in sections if s["passed"])
    for s in sections:
        print(f"  [{'PASS' if s['passed'] else 'FALLO'}] {s['section']}")
    verdict = "PASS" if n_ok == len(sections) else "FALLO"
    print(f"\nGATE F8: {verdict}  ({n_ok}/{len(sections)} secciones)")

    report = {"gate": "F8", "verdict": verdict, "sections": sections}
    out = BACKEND / "scripts" / "validation" / "f8_gate_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reporte → {out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
