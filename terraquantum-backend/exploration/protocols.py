# -*- coding: utf-8 -*-
"""FASE 8 — la frontera entre *orquestar una corrida* y *hacer la física*.

Por qué existe este archivo
---------------------------
La auditoría (§10, Fase 8, «Cambios arquitectónicos») pide introducir la frontera
*orquestación de corrida* ↔ *física de inversión* y declarar `ForwardOperator` y
`Solver` como **protocolos**, «aunque hoy tengan una sola implementación: es lo
que permitirá la segunda física sin otro monolito».

Hoy no hay UNA implementación: hay **cuatro solvers** con la misma forma y
ninguna firma común escrita en ninguna parte —

  * `GravimetryInversion.solve_inversion_lsqr`        (grilla regular)
  * `MagnetometryInversion.solve_magnetic_inversion_lsqr`
  * `solve_inversion_treemesh`                        (Octree; la Fase 4 descubrió
    que ahí el depth weighting está VIVO, al revés que en la grilla regular)
  * `solve_mvi_inversion_lsqr` / `solve_amplitude_inversion_lsqr`

Que se parezcan sin declararlo es exactamente cómo se llegó a H-9 (192 ventanas
duplicadas entre los dos motores) y a que la Fase 4 midiera **dos funcionales de
regularización distintos** creyendo que había uno. Escribir la forma no cambia
nada en ejecución: cambia qué es un error evidente al añadir la tercera física.

Qué NO es esto
--------------
No es una clase base ni un `ABC`: nadie hereda, nada se registra, no hay coste en
tiempo de ejecución. Son `typing.Protocol` **estructurales** — sirven para anotar
y para que un lector sepa qué se le exige a un operador nuevo. Convertirlos en
herencia obligatoria sería un refactor de comportamiento, y esta fase tiene la
byte-identidad como criterio duro.

Las firmas describen el CONTRATO OBSERVADO (lo que los cuatro motores ya hacen),
no un contrato deseado: si aquí dijera algo que el código no cumple, sería
documentación que miente, que es el problema que estas fases vienen arreglando.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ForwardOperator(Protocol):
    """Lo que la orquestación necesita de una física para predecir el dato.

    Un operador forward convierte un modelo por celda (contraste de densidad en
    t/m³, susceptibilidad en SI…) en el dato que mediría cada estación. La
    orquestación NO necesita saber si por dentro hay un prisma, un dipolo o una
    masa puntual: sólo necesita el kernel disperso y poder aplicarlo.
    """

    def _build_sparse_kernel(
        self,
        x_c: np.ndarray,
        y_c: np.ndarray,
        z_c: np.ndarray,
        sensor_coords: np.ndarray,
    ):
        """Matriz dispersa (n_sensores × n_celdas) con caché por geometría.

        El guion bajo es histórico y se conserva a propósito: `geophysics_service`
        lo llama por ese nombre para reconstruir el forward del solver en los
        diagnósticos R-01 y R-06 (cache HIT sobre la misma geometría). Renombrarlo
        sería un cambio de comportamiento en el camino crítico.
        """
        ...


@runtime_checkable
class Solver(Protocol):
    """Lo que la orquestación necesita de un solver de inversión.

    Los cuatro solvers del repositorio ya devuelven la misma tupla de cuatro
    elementos, todos de longitud `total_voxels` y con `NaN` en las celdas de aire.
    Escribirlo aquí es lo que convierte esa coincidencia en un contrato.

    `solver_meta` es la vía por la que el solver declara lo que PASÓ (frente a lo
    que se pidió): `solver_path`, `bounded_solver_used`, `lsqr_istop`,
    `regularization_functional`… La Fase 5 midió que publicar lo pedido en vez de
    lo ocurrido produjo un reporte falso durante meses, y la Fase 7 añadió el
    criterio de parada. Por eso el diccionario es parte del contrato y no un
    extra opcional.
    """

    def solve(
        self,
        d_observed: np.ndarray,
        *,
        solver_meta: Optional[dict] = None,
    ) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
        """`(modelo, score_relativo, misfit_percent, sensibilidad_normalizada)`.

        * `modelo` — la propiedad recuperada por celda, en unidades físicas.
        * `score_relativo` — ranking [0,1] derivado del residual proyectado. **No
          es una probabilidad**; el nombre `probability` que viaja al frontend es
          legado y así está documentado en ambos motores.
        * `misfit_percent` — ‖d−Gm‖/‖d‖ × 100, o `NaN` con dato degenerado (nunca
          0.0, que fingiría ajuste perfecto).
        * `sensibilidad_normalizada` — proxy de cobertura por celda.
        """
        ...


#: Nombres que un solver DEBE escribir en `solver_meta` para que la corrida sea
#: auditable. No se valida en ejecución (eso sería comportamiento nuevo); es la
#: lista contra la que se revisa una física nueva, y la que usan los gates.
CLAVES_SOLVER_META_MINIMAS = (
    "chi2_final",          # ajuste contra el sigma con el que se invirtió
    "acond",               # condicionamiento estimado
    "solver_path",         # QUÉ solver corrió (Fase 5: no lo que se pidió)
    "n_active",            # tamaño real del problema resuelto
    "lambda_effective",    # λ tras el escalado por n_active
)
