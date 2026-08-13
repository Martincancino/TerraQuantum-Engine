"""
Determinismo del framework — se ejecuta en segundos, sin invertir.

P6: sin reproducibilidad, ninguna comparación entre versiones significa nada.
Estos chequeos son la línea de defensa barata; el smoke completo es la cara.

    python -m validation.test_determinism
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

import numpy as np

from .catalog import C001_CLEAN, W001
from .contract import Campaign, Provenance
from .generate import generate_gravity, selfcheck_against_analytic
from .truth import Mesh, truth_products


def main() -> int:
    ok = True

    # 1. El oráculo coincide con la forma cerrada
    err = selfcheck_against_analytic()
    p = err <= 1e-6
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] oráculo vs fórmula cerrada: {err:.3e}")

    # 2. El hash del mundo es estable entre construcciones
    h1 = W001.provenance.content_hash
    h2 = W001.freeze().provenance.content_hash
    p = h1 == h2 and len(h1) == 32
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] hash del mundo estable: {h1[:16]}...")

    # 3. Misma semilla -> observaciones idénticas bit a bit
    a = generate_gravity(W001, C001_CLEAN)
    b = generate_gravity(W001, C001_CLEAN)
    p = all(np.array_equal(u, v) for u, v in zip(a, b))
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] misma semilla -> observaciones idénticas "
          f"({a[3].size} estaciones)")

    # 4. Semilla distinta -> observaciones distintas (el ruido de verdad se aplica)
    other = Campaign(**{**C001_CLEAN.__dict__,
                        "provenance": Provenance(seed=999,
                                                 generator_version="catalog/1")})
    c = generate_gravity(W001, other)
    p = not np.array_equal(a[3], c[3])
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] semilla distinta -> observaciones distintas")

    # 5. La verdad es pura: mismo (mundo, malla) -> mismos derivados
    mesh = Mesh(nx=40, ny=20, nz=40, block_m=50.0)
    t1, t2 = truth_products(W001, mesh), truth_products(W001, mesh)
    p = (np.array_equal(t1.contrast_t_m3, t2.contrast_t_m3)
         and t1.centroids_m == t2.centroids_m)
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] truth_products es pura "
          f"({int(t1.body_mask.sum())} celdas de cuerpo)")

    # 6. La verdad NO depende de la resolución de la malla (P1: es paramétrica)
    fine = truth_products(W001, Mesh(nx=80, ny=40, nz=80, block_m=25.0))
    p = fine.centroids_m == t1.centroids_m and fine.volumes_m3 == t1.volumes_m3
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] verdad invariante a la malla "
          f"(centroide y volumen analíticos)")

    # 7. Un método inadmisible queda excluido del gate por construcción (P4)
    from .contract import GenerationMethod as G
    p = (not G.INVERSE_CRIME.admissible_in_gate
         and G.THIRD_PARTY.admissible_in_gate)
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] INVERSE_CRIME excluido del gate por contrato")

    # 8. Un umbral sin justificación no se puede construir (P3)
    from .contract import Threshold
    try:
        Threshold(metric="x", op="<=", value=1.0, justification="   ",
                  measured_on="", measured_value=0.0)
        p = False
    except ValueError:
        p = True
    ok &= p
    print(f"[{'OK ' if p else 'FAIL'}] umbral sin justificación es rechazado")

    print("\n" + ("TODO OK" if ok else "HAY FALLOS"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
