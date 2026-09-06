# PRE-REGISTRO — Fase 30 · el techo a `HIGH`

**Fecha: 2026-09-06.** Escrito ANTES de correr el conjunto de confirmación, y no se toca
después. Existe porque la regla que sigue se eligió **mirando datos** (las 75 corridas de
confirmación de la Fase 26, que aquí pasan a ser el conjunto de **selección**), y medir el
gate sobre esos mismos datos sería contarse la victoria dos veces — el mismo vicio que la
Fase 26 evitó partiendo el barrido en dos.

## 1. Lo que se midió antes de decidir (conjunto de SELECCIÓN, n = 75)

Fuente: `exp_resolution_confirm.json` de la Fase 26 (15 regímenes × 5 semillas 900011…900515).

| pregunta | respuesta medida |
|---|---|
| corridas cuyo ÚNICO limitante es `high_hold_pending_fase30` | **0 de 75** |
| corridas MEDIUM también capadas por `priority_class` | **44 de 44** |
| ⇒ veredictos que cambia quitar SOLO el hold (lo que pide el plan) | **0 de 75** |
| corridas donde `priority_class` decide en SOLITARIO | **0 de 75** |
| veredictos que cambia quitar hold + `priority_class` | 38 pasan a HIGH |
| de esas 38, SOBRECONFIADAS (error > 200 m) | **0** — máx. 180,0 m |
| corridas que serían SOBRECONFIADAS si HIGH se soltara sin criterio | **3** (978,4 · 636,8 · 542,1 m) |
| ¿quién caza esas 3 sin ayuda del hold ni de `priority_class`? | `survey_confidence` + `model_reliability`, ambas en MEDIUM |

## 2. La regla, PRE-REGISTRADA

`HIGH` deja de estar retenido, y para sellarse exige evidencia POSITIVA. Tres cambios en
`build_reconciled_verdict`:

1. **Se quita** `levels.append(("MEDIUM", "high_hold_pending_fase30"))`.
2. **`priority_class` deja de topear** y pasa a publicarse como señal informativa
   (`priority_class_role`), igual que la Fase 26 hizo con el tablero. Motivo **semántico**,
   no numérico: mide el ATRACTIVO del blanco, no la CONFIABILIDAD del modelo — y ya está
   derivado de la calidad (la favorabilidad multiplica por `quality_gate` y
   `uncertainty_gate`), así que en el worst-of contaba la calidad dos veces e inyectaba
   una dimensión que no es la del veredicto.
3. **Sello de `HIGH` (`high_seal`)** — cap a MEDIUM salvo que se cumplan las DOS:
   * `resolution_qa.shallowest_band_resolution_m` **<** `max_block_tested_m`
     (resolver sólo el peldaño más grueso de la escalera es el SUELO del examen, no
     resolución que aguante un sello);
   * `best_target.floor_mass_excess` **≤ 0,5**
     (el número que la Fase 26 midió y el plan mandó traer: como umbral para DEGRADAR a
     LOW deja sólo un 12 % de margen al peor caso sano, pero para NEGAR el nivel superior
     es exactamente el uso correcto).
   Ausencia de cualquiera de los dos datos ⇒ **no** se sella (la ausencia nunca concede).

**Efecto en el conjunto de selección:** 24 de 75 en HIGH, error horizontal máximo **94,5 m**
(sin el sello serían 38 con máximo 180,0 m; el sello dobla el margen contra la línea de los
200 m).

## 3. El gate, declarado antes de correrlo

Conjunto de **CONFIRMACIÓN**: ≥ 150 corridas, semillas frescas sin solape con
(20260805, 11, 202, 3003, 40004) ni (900011…900515). Criterios, los tres a la vez:

* **G1 — honestidad:** cuadrante SOBRECONFIADO (error horizontal > 200 m **y** veredicto
  HIGH) = **0**.
* **G2 — el 0 no es un techo:** `HIGH` alcanzable, ≥ 20 % de las corridas en HIGH. Sin
  esto G1 se cumple sin medir nada, que es exactamente lo que pasa hoy.
* **G3 — no se degrada lo ya cerrado:** ninguna corrida con `resolves_anywhere = False`
  sale por encima de LOW, y ninguna con `is_floor_smear = True` sale por encima de LOW.

Si G1 falla, la regla NO se publica: se vuelve al hold y se declara medido.

## 4. Lo que este pre-registro NO promete

* No arregla `favorability`: se midió que `anomaly_intensity` da **0,0** a la mejor corrida
  del barrido (`depth_250m`, PR-AUC 1,000, error 11,3 m) y **1,0** a la peor
  (`worst_ldm_like`, PR-AUC 0,002, error 1186 m), y que `structural_gradient` (0,045–0,066)
  y `msx_support` (0,067–0,083) son casi constantes. Se anota como defecto NUEVO; tocarlo
  aquí sería cambiar dos cosas a la vez y no poder atribuir el resultado.
* No toca el frontend (regla del proyecto).
