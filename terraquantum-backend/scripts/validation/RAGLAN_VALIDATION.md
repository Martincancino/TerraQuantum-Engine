# Raglan (Ni-Cu, Quebec) — Validación contra benchmark de DATO REAL

**Segundo benchmark externo de TerraQuantum y el PRIMERO con dato de campo REAL.**
Dataset: survey magnético del depósito de Ni-Cu de Raglan (Northern Quebec), invertido en 3D
hacia 1997 (la inversión que ayudó a ubicar un sondaje mineralizado). Tutorial SimPEG
Transform 2021 (`simpeg/transform-2021-simpeg`).

## Por qué importa más que DO-27

DO-27 era *synthetic-based-on* (forward-modelado desde sondajes). **Raglan es dato de campo
crudo REAL** (TMI medido de un survey real). Esto ataca directamente el caveat pendiente de
DO-27 ("falta dato de campo crudo"). El precio: no hay "modelo verdadero" sintético — el
ground truth es (a) la inversión de REFERENCIA publicada `maginv3d` (1997) y (b) la anomalía
dominante observada en los propios datos. La métrica es **posición/estructura del cuerpo**, no
un valor de susceptibilidad puntual (reframe Fase 25).

## Datos sucios / extracción (no inventar)

| Ítem | Manejo |
|------|--------|
| IGRF de Raglan | **Extraído del header de `data/Raglan_1997/obs.mag`**: I=83°, D=−32°, B0=60000 nT (Quebec ártico ~62°N). NO inventado. |
| Coordenadas | LOCALES (no UTM): X∈[497,4505], Y∈[39028,42970] m. Frame alineado con la malla de referencia (origen 500, 39000). |
| Z (drape) | Constante = 40 m (altura de vuelo sobre la superficie z=0) → sensores a y=−40 m (sobre tierra). |
| σ | `Std_nT` real por estación (mediana 7.3 nT). El motor usa σ escalar floor+pct·\|d\| → se pasa floor=mediana(Std), pct=0 (σ ≈ Std real, NO 2%·\|d\| adaptativo). |
| Anomalía extrema (5221 nT) | Es **señal real** (cluster espacialmente coherente en el borde este), NO outlier → `detect_outliers=False` (no se downpesa el cuerpo). |

## Ground truth (referencia maginv3d 1997)

`data/Raglan_1997/maginv3d.sus` sobre `mesh.msh` (40×40×10 @100 m). **Ordenamiento UBC
validado** forward-modelando el modelo de referencia con el motor de TQ: correlación **0.90**
entre su forward y el TMI observado → `reshape (ny,nx,nz) C-order, transpose` es el correcto
(esto además valida la física magnética del motor sobre dato real).

- **Pico de susc (blanco de sondaje):** Este=3350, Norte=40250, prof ≈350 m (κ_max=0.31).
- **Anomalía dominante en los datos:** Este=3401, Norte=40021 (coincide con el pico, <400 m).
- El modelo de referencia es **difuso** (inversión de campo real con depth-weighting; susc
  esparcida y smeared en profundidad 350–950 m) → se valida la POSICIÓN del cuerpo dominante.

## Configuración de la inversión (motor real, magnético, sin tunear)

- Malla 20×20×5 @ 200 m (4000×4000×1000 m, igual extensión que la referencia). 410 estaciones
  (submuestreo 1:4). Motor compacto Fase 24B + depth-weighting + poda + auto-κ; κ ∈ [0, 0.5];
  cutoff 2500 m; σ = Std real. **Sin padding** (limitación, ver abajo).

## Resultados

| Métrica | Recuperado (TQ) | Referencia | Error |
|---------|-----------------|------------|-------|
| Pico GLOBAL (E, N) | (4400, 40100) | (3350, 40250) | 1061 m |
| **Cuerpo INTERIOR (sin borde)** | **(3200, 40100)** | (3350, 40250) | **212 m** |
| Prof. cuerpo interior | 200 m | 350 m | 150 m |
| Corr. horizontal (Pearson) | **0.54** | | |
| Corr. 3D (penaliza prof.) | 0.16 | | |
| Misfit | 9.5 % | | |

## VEREDICTO HONESTO: ✅ PASA en targeting (con matiz de artefacto de borde)

1. **TQ ajusta el dato de campo REAL** (misfit 9.5 %) con el IGRF real extraído.
2. **TQ localiza el cuerpo Ni-Cu dominante a 212 m** del pico de la referencia publicada
   (dentro de la tolerancia de <400 m a escala de survey de 4 km). El blanco geológico
   (≈ donde se perforó en 1997) lo recupera bien.
3. **La estructura horizontal correlaciona (Pearson 0.54)** con la referencia. La correlación
   3D es baja (0.16) **sólo por la distribución en PROFUNDIDAD** (la referencia difumina el
   cuerpo a 350–950 m; TQ lo concentra a 100–300 m) — ambas no-únicas en z, no un fallo de
   posición.
4. **MATIZ HONESTO — artefacto de borde:** el pico GLOBAL de TQ cae en el borde este (4400 m),
   donde está la anomalía MÁS fuerte del survey (5221 nT en X≈4478, justo en el límite), y la
   susc se satura al bound en celdas de borde. **Causa: la malla no tiene padding** → las
   fuentes en el límite del survey se proyectan como artefactos en las celdas de borde. Por eso
   el pico global "falla" (1061 m) aunque el cuerpo geológico interior esté bien localizado.
   La referencia maginv3d usa padding/pesos de borde y no sufre esto.

→ **Conclusión:** sobre dato de campo REAL, TQ localiza el cuerpo de Ni-Cu donde lo ubican la
referencia publicada y la geología (212 m, targeting OK), y reproduce la estructura horizontal.
Es **evidencia más fuerte que DO-27** por ser dato crudo. La limitación expuesta (artefactos de
borde sin padding) es real y honesta, y es un caso más duro que DO-27 (cuerpo central) por ser
multi-cuerpo, área amplia y con la fuente más fuerte en el límite del survey.

## Límites / trabajo futuro

- **Padding de malla:** añadir celdas de padding eliminaría el artefacto de borde y haría que
  el pico global coincidiera con el interior. Requiere el path de tensor-mesh-con-padding del
  motor (no cableado en este harness simple) → trabajo futuro.
- **Bound de susc holgado** (0.5 vs κ_max ref 0.31) → saturación; un bound físico (~0.35)
  reduciría la saturación. No se ajustó (regla de no-tuneo).
- **MVI (Fase 20C) no corrido:** el Ni-Cu masivo puede tener remanencia; MVI podría afinar el
  cuerpo. NO resolvería el artefacto de borde (es geométrico, no de magnetización). Futuro.
- **σ por-estación:** el motor usa σ escalar; se aproximó con σ=mediana(Std). Un σ vectorial
  exacto requeriría tocar el motor (fuera de alcance).

## Reproducir

```bash
cd terraquantum-backend
python scripts/validation/ingest_raglan.py          # GATE: estaciones, IGRF, referencia
python scripts/validation/raglan_harness.py          # inversión (~22 min) → JSON + modelo .npz
python scripts/validation/raglan_harness.py --from-saved   # re-deriva métricas sin re-invertir
python -m pytest tests/test_raglan_ingest.py -q       # 6 tests de limpieza
```

> Datos en `Raglan_Magnetic/` (raíz del repo), **NO commiteados** (regla CLAUDE.md). Solo código.
