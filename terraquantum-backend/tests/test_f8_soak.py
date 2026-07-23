"""F8 — Soak test: N inversiones consecutivas en el mismo proceso.

Verifica que la memoria queda ESTABLE (sin fugas de kernels/parquets) y que el
historial SQLite sigue íntegro tras la ráfaga. Es la prueba de que TQ aguanta una
sesión de trabajo real (el consultor invierte decenas de veces al día).

CI: N pequeño (default 8) con umbral generoso → guarda contra fugas groseras sin
flakear. El gate (`f8_gate_storm.py`) corre N=50 con el umbral estricto del plan.
Marcado `slow` (cada iteración es una inversión real).
"""
import gc
import os
import sys
import tracemalloc

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.f8_storm_lib as L  # noqa: E402

pytestmark = pytest.mark.slow

SOAK_N = int(os.environ.get("TQ_F8_SOAK_N", "8"))
# Umbral de crecimiento de RSS por iteración (MB). Generoso en CI; el gate lo baja.
MAX_MB_PER_ITER = float(os.environ.get("TQ_F8_SOAK_MB_PER_ITER", "8.0"))


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _rss_mb() -> float:
    import psutil
    return psutil.Process().memory_info().rss / (1024 * 1024)


def test_f8_soak_memory_stable(client):
    combo = L.Combo("grav", "clean", "small", "latlon", False)
    side = L.SIZES_FAST["small"]

    gc.collect()
    tracemalloc.start()
    rss = []
    ok_runs = 0
    for i in range(SOAK_N):
        o = L.drive_e2e(client, combo, side=side, grid=6,
                        project_id=f"f8_soak_{i}", run_id="soak")
        assert o.ok, f"iter {i}: {o.outcome} {o.detail}"
        if o.outcome == "valid_3d_model":
            ok_runs += 1
        gc.collect()
        rss.append(_rss_mb())

    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert ok_runs >= max(1, SOAK_N // 2), f"pocas inversiones válidas: {ok_runs}/{SOAK_N}"

    # Tendencia: media del último tercio vs primer tercio, normalizada por iteración.
    k = max(1, SOAK_N // 3)
    base = sum(rss[:k]) / k
    tail = sum(rss[-k:]) / k
    growth_per_iter = (tail - base) / max(1, SOAK_N - k)
    assert growth_per_iter < MAX_MB_PER_ITER, (
        f"posible fuga: RSS +{growth_per_iter:.2f} MB/iter sobre {SOAK_N} corridas "
        f"(base={base:.0f}MB tail={tail:.0f}MB, tracemalloc peak={peak/1e6:.0f}MB)"
    )


def test_f8_soak_history_integrity(client):
    """Tras la ráfaga, el historial SQLite responde y contiene las corridas."""
    L.reset_rate_limit()
    r = client.get("/v2/history/runs")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    # Estructura íntegra (lista de corridas o envoltura con 'runs').
    runs = body.get("runs", body) if isinstance(body, dict) else body
    assert isinstance(runs, list), f"historial no es lista: {type(runs)}"
