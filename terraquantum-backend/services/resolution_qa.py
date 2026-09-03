"""FASE 26 — El examen de resolución que SÍ se puede aprobar, y que SÍ varía.

Por qué existe
==============
`validation/HALLAZGO_2026-08-06_techo_medium.md` midió que el QA de resolución de
producción (`_run_checkerboard_qa_fast`) devuelve **el mismo número siempre**
(`pearson_r = 0,1162` idéntico a cuatro decimales) y `FAIL` en el 100 % de las
corridas, y que el veredicto worst-of lo usa de tope duro ⇒ `HIGH` es inalcanzable
por construcción. El hallazgo culpaba a la longitud de onda del tablero. Al
re-medirlo contra el código (2026-09-03, 15 regímenes de `validation/regimes.py`)
resultó que la longitud de onda era **una de tres** causas independientes, y no la
mayor:

1. **Longitud de onda.** `build_checkerboard_model` alterna el signo CELDA A CELDA:
   en una malla de 125 m eso es un patrón de 250 m, por debajo del límite físico de
   un campo potencial. MEDIDO: agrandar el bloque a 4 celdas sube `pearson_r` de
   0,116 a 0,247 — sigue muy lejos del umbral de PASS de 0,60. **Cambiar sólo la
   longitud de onda no arregla nada.**

2. **Puntúa profundidades que ningún survey gravimétrico resuelve.** El Pearson se
   calcula sobre la malla ENTERA, incluidas las capas profundas donde la
   recuperación es ~0 para cualquier survey. MEDIDO, mismo kernel y misma λ: el
   mismo tablero puntuado sólo dentro de la banda 0–250 m con bloques de 750 m da
   **r = 0,70** (aprueba) mientras el examen de hoy da 0,116. El examen no medía
   este survey: medía el promedio entre lo resoluble y lo que nunca lo será.

3. **Examina un solver distinto del que produjo el modelo.** El QA invierte con
   `lsqr(damp=λ)` sobre el kernel Core: sin padding, sin bounds, sin depth-weighting,
   sin suavidad. MEDIDO sobre `baseline` (17 semillas): ese solver, con EL MISMO dato
   observado, devuelve PR-AUC ≈ 0,040 y el centroide a ~90 m donde producción devuelve
   PR-AUC 1,000 y el centroide a 466 m. Aunque el examen aprobara, no describiría al
   modelo que el usuario está mirando.

Qué mide este módulo
====================
Un **perfil de resolución**: para cada banda de profundidad y cada tamaño de bloque
lateral L de una escalera declarada, se sintetiza un tablero LATERAL (alterna en x,z;
constante dentro de la banda; cero fuera), se propaga con el MISMO kernel, se le suma
ruido al **σ declarado**, y se puntúa la correlación del **mapa en planta** (contraste
integrado en profundidad) contra el patrón verdadero.

De ahí sale, por banda, la **longitud de resolución**: el bloque más pequeño de la
escalera que se recupera con r ≥ 0,60. Es un número en METROS que el usuario puede
comparar con el tamaño del cuerpo que busca, en vez de un `FAIL` sin escala.

Tres decisiones, cada una MEDIDA (75 corridas del brazo estricto, 15 regímenes):

* **Mapa en planta, no celda a celda.** Aísla la resolución LATERAL —la que manda el
  targeting— de la ambigüedad de PROFUNDIDAD, que la gravedad-sola no resuelve y que
  contaminaba el número (dirección 3 del plan).
* **Escalado a la amplitud de SEÑAL, no al RMS observado.**
  `rms_signal = sqrt(max(rms_obs² − σ², 0))`. Sin esta corrección un survey ruidoso se
  auto-aprueba: MEDIDO, `noise_0.15` sacaba r = 0,790 con PR-AUC real de 0,010; con la
  corrección baja a 0,661.
* **Se puntúa el DOMINIO completo, no sólo la huella del survey.** Restringir la nota a
  las columnas con estaciones encima premia al survey que cubre menos: MEDIDO,
  `span_800m` pasaba de 0,104 (dominio) a 0,643 (huella) con un PR-AUC real de 0,026.
  El usuario pidió un modelo del dominio; un survey que cubre un tercio no lo resuelve.

Lo que este módulo NO hace
==========================
* **No levanta el techo a `HIGH`.** Es la Fase 30, y está condicionada a ésta por
  escrito. Ver `_verdict_ceiling` en `geophysics_service.py`.
* **No discrimina entre realizaciones de ruido dentro de un mismo régimen.** El examen
  usa σ, no la muestra concreta, así que para un mismo survey devuelve lo mismo con
  cualquier semilla — igual que el examen viejo. Esa mitad del hallazgo (1 de cada 3
  realizaciones desvía el blanco ~170 m) NO la cierra este módulo; ver el registro de
  la fase.
"""

from __future__ import annotations

import time

import numpy as np

# ── Escalera de tamaños de bloque, en CELDAS ────────────────────────────────
# Se prueban en orden creciente; se descartan los que no dejen al menos 2 bloques
# por lado en el núcleo (un tablero de 1 bloque no es un tablero).
BLOCK_LADDER_CELLS = (1, 2, 3, 4, 6)

# Umbral de aprobado. Se CONSERVA el 0,60 histórico a propósito: la dirección 2 del
# plan («recalibrar el umbral») se cumple haciendo el examen respondible, no bajando
# la vara. MEDIDO: con el examen nuevo un survey sano lo pasa (baseline, banda
# 0–250 m, L = 750 m → r = 0,79) y uno degradado no (worst_ldm_like → 0,03).
PASS_PEARSON_R = 0.60

# Realizaciones de ruido por celda de la escalera. La mediana de 3 estabiliza el
# número sin que el coste importe (MEDIDO: 8 ms por solve LSQR en malla 18×14×18).
N_NOISE_REALIZATIONS = 3

# Número de bandas de profundidad del perfil. Las 4 primeras son finas y la última
# se lleva el resto: la resolución cae rápido cerca de la superficie y ya es plana
# (nula) en el fondo, así que gastar bandas ahí no informa.
N_BANDS = 5

# Cuando NINGÚN bloque de la escalera aprueba en una banda, la longitud de resolución
# no es infinita ni cero: es «mayor que el bloque más grande probado». Se publica como
# None y, para poder ordenar y correlacionar, se censura en este múltiplo del máximo.
CENSORED_MULTIPLIER = 1.5

_LSQR_ITER_LIM = 150


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.size < 2 or a.std() < 1e-15 or b.std() < 1e-15:
        return 0.0
    r = float(np.corrcoef(a, b)[0, 1])
    return r if np.isfinite(r) else 0.0


def _bands(ny: int, n_bands: int = N_BANDS):
    """Bandas de profundidad en índices de celda: `n_bands - 1` finas + el resto.

    Las bandas finas cubren la MITAD SUPERIOR del dominio, que es donde la resolución
    de un survey gravimétrico realmente cambia; la última se lleva la mitad inferior,
    donde ya es uniformemente nula y gastar bandas no informa. En la malla del barrido
    (ny = 14) eso da (0-2, 2-4, 4-6, 6-8, 8-14) celdas.
    """
    if ny <= n_bands:
        return [(i, i + 1) for i in range(ny)]
    thin = max(1, int(round(ny / (2.0 * (n_bands - 1)))))
    out = []
    y = 0
    for _ in range(n_bands - 1):
        if y + thin >= ny:
            break
        out.append((y, y + thin))
        y += thin
    out.append((y, ny))
    return out


def signal_rms_and_sigma(g_observed, noise_floor_solver: float,
                         noise_pct_solver: float, sigma_is_declared: bool):
    """σ del dato y amplitud de SEÑAL (no de señal+ruido), con su procedencia.

    Devuelve (sigma, rms_signal, meta). `sigma_is_declared` distingue el σ real
    (noise_floor_mgal o tabla de gravímetro) del sentinel v1 `0.02/0.02`, que NO
    está en m/s² y no puede usarse como escala absoluta.
    """
    g = np.asarray(g_observed, dtype=np.float64).ravel()
    rms_tot = float(np.sqrt(np.mean((g - np.mean(g)) ** 2)))
    if sigma_is_declared:
        # σ DECLARADO: se respeta tal cual, incluso si supera al dato. Topearlo a una
        # fracción del RMS observado sería mentir en la dirección peligrosa: un survey
        # cuyo ruido declarado se come la anomalía TIENE que suspender el examen, no
        # aprobarlo con una σ recortada a medida.
        sigma = float(max(noise_floor_solver,
                          float(noise_pct_solver) * float(np.median(np.abs(g)))))
        source = "declared"
    else:
        # Sentinel v1: `noise_floor_solver` vale 0.02 pero NO son m/s² — es el
        # disparador de la σ adaptiva interna del solver. Aquí se traduce a la
        # única lectura defendible: un 2 % del RMS observado, y se DECLARA. En este
        # camino σ es una FRACCIÓN del dato por construcción, así que no puede
        # tragárselo.
        sigma = float(max(noise_pct_solver, 0.02)) * max(rms_tot, 1e-30)
        source = "estimated_2pct_of_rms_sentinel"
    sigma = float(max(sigma, 1e-30))
    rms_signal = float(np.sqrt(max(rms_tot ** 2 - sigma ** 2, 0.0)))
    meta = {
        "sigma": sigma,
        "sigma_source": source,
        "rms_observed": rms_tot,
        "rms_signal": rms_signal,
        "snr_signal": (rms_signal / sigma) if sigma > 0 else float("inf"),
        # Si esto es True, el σ declarado se come la anomalía: el examen se corre con
        # un piso simbólico y va a suspender. Es el resultado correcto, no un error.
        "sigma_exceeds_signal": bool(rms_signal <= 0.0),
    }
    return sigma, max(rms_signal, 0.1 * sigma), meta


def run_resolution_profile_qa(
    kernel_core,
    ix, iy, iz,
    nx: int, ny: int, nz: int,
    block_size: float,
    lambda_mag: float,
    g_observed,
    noise_floor_solver: float,
    noise_pct_solver: float,
    sigma_is_declared: bool,
    seed: int = 20260903,
) -> dict:
    """Perfil de resolución lateral por banda de profundidad. Determinista.

    `ix/iy/iz` son los índices de celda del NÚCLEO en el mismo orden que las columnas
    de `kernel_core` (el kernel de diagnóstico Core, no el padded del solver).
    """
    from scipy.sparse.linalg import lsqr as _lsqr

    t0 = time.perf_counter()
    ixi = np.asarray(ix, dtype=np.int64)
    iyi = np.asarray(iy, dtype=np.int64)
    izi = np.asarray(iz, dtype=np.int64)

    sigma, rms_use, sigma_meta = signal_rms_and_sigma(
        g_observed, noise_floor_solver, noise_pct_solver, sigma_is_declared)

    ladder = [c for c in BLOCK_LADDER_CELLS if 2 * c <= min(nx, nz)]
    if not ladder:
        ladder = [1]

    # Índice de columna (ix,iz) por celda, para el mapa en planta.
    col_key = ixi * (int(izi.max()) + 1) + izi
    uniq, col_of = np.unique(col_key, return_inverse=True)
    n_col = int(uniq.size)

    def plan_map(v):
        m = np.zeros(n_col, dtype=np.float64)
        np.add.at(m, col_of, v)
        return m

    rng = np.random.default_rng(seed)
    max_L = float(max(ladder) * block_size)
    bands_out = []
    for (a, b) in _bands(int(ny)):
        in_band = (iyi >= a) & (iyi < b)
        scores = []
        for cpb in ladder:
            sign = np.where(((ixi // cpb + izi // cpb) % 2) == 0, 1.0, -1.0)
            true = np.where(in_band, sign, 0.0)
            g_syn = kernel_core @ true
            rms = float(np.sqrt(np.mean(g_syn ** 2)))
            if not np.isfinite(rms) or rms <= 0:
                scores.append({"block_size_m": float(cpb * block_size),
                               "pearson_r": None})
                continue
            k = rms_use / rms
            true_map = plan_map(true * k)
            g_syn = g_syn * k
            rs = []
            for _ in range(N_NOISE_REALIZATIONS):
                est = _lsqr(kernel_core,
                            g_syn + rng.normal(scale=sigma, size=g_syn.shape),
                            damp=float(lambda_mag), iter_lim=_LSQR_ITER_LIM,
                            show=False)[0]
                rs.append(_pearson(true_map, plan_map(est)))
            scores.append({"block_size_m": float(cpb * block_size),
                           "pearson_r": round(float(np.median(rs)), 4)})

        passing = [s["block_size_m"] for s in scores
                   if s["pearson_r"] is not None and s["pearson_r"] >= PASS_PEARSON_R]
        res_len = min(passing) if passing else None
        bands_out.append({
            "y_from_m": float(a * block_size),
            "y_to_m": float(b * block_size),
            "depth_mid_m": float((a + b) * 0.5 * block_size),
            "resolution_length_m": res_len,
            "resolves": res_len is not None,
            "scores": scores,
        })

    deepest = max([bb["y_to_m"] for bb in bands_out if bb["resolves"]] or [0.0])
    all_r = [s["pearson_r"] for bb in bands_out for s in bb["scores"]
             if s["pearson_r"] is not None]

    # ── Los dos escalares ────────────────────────────────────────────────────
    # `resolvability_index`: media de TODO el examen (todas las bandas × todos los
    # peldaños). Se elige por no tener NINGÚN parámetro ajustado al resultado — ni
    # banda ni peldaño elegidos a posteriori. MEDIDO sobre 75 corridas / 15 regímenes
    # del brazo estricto: Spearman contra PR-AUC = +0,853 (ρ = +0,922 sobre las 15
    # medianas por régimen), frente a +0,073 de `chi2_red` y +0,275 del tablero viejo.
    # Variantes ajustadas (una banda concreta, un peldaño concreto) llegaban a +0,89-0,92;
    # se DESCARTAN a propósito: la ganancia es pequeña y el coste es un parámetro
    # elegido mirando la respuesta.
    index = float(np.mean(all_r)) if all_r else float("nan")
    top = bands_out[0] if bands_out else None
    return {
        "computed": True,
        "method": "banded_lateral_checkerboard_plan_map_resolution_profile",
        "pass_pearson_r": PASS_PEARSON_R,
        "block_ladder_m": [float(c * block_size) for c in ladder],
        "max_block_tested_m": max_L,
        "censored_resolution_length_m": round(CENSORED_MULTIPLIER * max_L, 1),
        "n_noise_realizations": N_NOISE_REALIZATIONS,
        "deepest_resolved_m": float(deepest),
        "resolves_anywhere": bool(deepest > 0.0),
        "resolvability_index": (round(index, 4) if index == index else None),
        "shallowest_band_resolution_m": (top.get("resolution_length_m") if top else None),
        "bands": bands_out,
        "sigma_used": sigma_meta,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "note": (
            "Longitud de resolución = bloque lateral más pequeño de la escalera que "
            "este survey recupera con r >= "
            f"{PASS_PEARSON_R:.2f} en esa banda de profundidad, con el σ declarado. "
            "null = ni el bloque más grande probado se resuelve ahí. El examen NO usa "
            "el dato observado como patrón (sintetiza el suyo), pero SÍ usa su amplitud "
            "de señal y su σ, y depende de la geometría del survey, de la malla y de λ. "
            "Es resolución LATERAL: la gravedad-sola no resuelve la profundidad."
        ),
    }


def resolution_at_depth(profile: dict, depth_m) -> dict:
    """Lee el perfil a la profundidad de un blanco. Nunca levanta excepción."""
    out = {"available": False, "depth_m": None, "resolution_length_m": None,
           "resolves": None, "band": None}
    try:
        bands = (profile or {}).get("bands") or []
        if not bands or depth_m is None:
            return out
        d = float(depth_m)
        if not np.isfinite(d):
            return out
        band = None
        for bb in bands:
            if bb["y_from_m"] <= d < bb["y_to_m"]:
                band = bb
                break
        if band is None:
            band = bands[-1] if d >= bands[-1]["y_to_m"] else bands[0]
        out.update({
            "available": True,
            "depth_m": d,
            "resolution_length_m": band.get("resolution_length_m"),
            "resolves": bool(band.get("resolves")),
            "band": [band["y_from_m"], band["y_to_m"]],
        })
        return out
    except Exception:
        return out


def resolution_length_for_ranking(profile: dict, depth_m) -> float:
    """El escalar que se correlaciona: metros, censurado cuando nada aprueba."""
    at = resolution_at_depth(profile, depth_m)
    if not at["available"]:
        return float("nan")
    v = at["resolution_length_m"]
    if v is None:
        try:
            return float(profile.get("censored_resolution_length_m"))
        except (TypeError, ValueError):
            return float("nan")
    return float(v)
