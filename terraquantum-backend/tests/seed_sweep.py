"""FASE 26 (dirección 5) — una semilla no es una muestra.

Por qué existe
--------------
Los benchmarks científicos del repositorio afirmaban «el centroide se recupera a
±150 m» sobre **una sola realización de ruido** (`default_rng(seed=42)` en los tres).
El barrido de validación midió que esa afirmación no se sostiene con una muestra de
uno: en el régimen donde el producto declara su fortaleza, **1 de cada 3 realizaciones
de ruido** —mismo mundo, mismo survey, misma λ— desplaza el blanco ~170 m en vez de
~19 m (`validation/HALLAZGO_2026-08-06_techo_medium.md`, 24 semillas frescas, IC 95 %
18–53 %). Un benchmark de una semilla puede estar midiendo la moda buena, la mala, o
la suerte; y peor: puede pasar de verde a rojo al tocar cualquier cosa que reordene el
ruido, sin que nada haya empeorado.

Qué cambia
----------
El estadístico de aceptación pasa a ser la **mediana sobre N semillas declaradas**, y
el mensaje de fallo publica **todas** las semillas. Así:

  * un benchmark verde afirma algo sobre la distribución, no sobre una tirada;
  * la dispersión queda a la vista aunque el test pase — que es el hallazgo de verdad;
  * romper la física mueve la mediana, no una cola, así que el gate sigue defendiendo.

`TQ_BENCH_SEEDS` sube el número de semillas sin tocar código (CI nocturna, auditorías).
El coste es lineal: cada semilla es una inversión más sobre el MISMO kernel, que se
construye una sola vez.
"""

from __future__ import annotations

import os
import statistics

# Secuencia DECLARADA, no cazada para producir un resultado. La primera es la 42
# histórica, para que el número que estos benchmarks publicaban siga siendo
# comparable y se vea dónde caía dentro de la distribución.
BENCH_SEEDS = (42, 20260805, 11, 202, 3003, 40004, 700001, 700138)

DEFAULT_N = 5


def bench_seeds(n: int | None = None) -> tuple[int, ...]:
    """Semillas a barrer. `TQ_BENCH_SEEDS` manda si está definida."""
    if n is None:
        try:
            n = int(os.getenv("TQ_BENCH_SEEDS", "") or DEFAULT_N)
        except ValueError:
            n = DEFAULT_N
    n = max(1, min(int(n), len(BENCH_SEEDS)))
    return BENCH_SEEDS[:n]


def median_of(values) -> float:
    v = [float(x) for x in values if x is not None and x == x]
    if not v:
        return float("nan")
    return float(statistics.median(v))


def spread_report(seeds, values, unit: str = "") -> str:
    """Todas las semillas, en el mensaje de fallo. Sin esto, un rojo de mediana no
    dice si falló todo o si hay una cola: es la mitad de la información."""
    pares = [(s, v) for s, v in zip(seeds, values) if v is not None and v == v]
    if not pares:
        return "sin valores finitos en ninguna semilla"
    vals = [v for _s, v in pares]
    det = " | ".join(f"s{s}={v:.1f}{unit}" for s, v in pares)
    return (f"mediana={median_of(vals):.1f}{unit}  "
            f"rango=[{min(vals):.1f}, {max(vals):.1f}]{unit}  n={len(vals)}\n"
            f"    por semilla: {det}")
