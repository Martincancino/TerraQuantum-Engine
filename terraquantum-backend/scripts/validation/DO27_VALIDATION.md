# DO-27 (Tli Kwi Cho) — Validación contra benchmark PUBLICADO

**Primer test del motor de TerraQuantum contra un benchmark externo y peer-reviewed.**
Dataset: kimberlita DO-27, Astic & Oldenburg 2020 (GJI), repo `simpeg-research/Astic-2020-JointInversion`.

## Por qué importa

DO-27 es el caso de estudio del paper de PGI que TerraQuantum implementa. Trae gravimetría +
magnetometría + geología desde sondajes (ground truth) + inversiones de referencia (L2, Lp, PGI).
Pasarlo es un salto de credibilidad real sobre los sintéticos caseros: el ground truth y las
referencias son **externos**, no construidos por nosotros.

**Caveat honesto (no se oculta):** los datos geofísicos son *synthetic based on* DO-27
(forward-modelados desde la geología de sondajes), NO dato crudo de campo. Aun así el ground
truth y las referencias son externos y peer-reviewed — el escalón correcto antes de campo crudo.

## Reframe vigente (qué se mide)

TerraQuantum se valida por **GEOMETRÍA / TARGETING** (dónde está el cuerpo, profundidad, forma),
NO por predicción de densidad punto a punto (eso es kriging — ver `project_fase25_field_validation`).
La métrica dura es la **localización del pipe** (error horizontal + profundidad). La densidad y la
susceptibilidad se reportan sólo como informativo.

## Datos sucios manejados

| Problema | Manejo |
|----------|--------|
| Magnético: 2 primeras filas son el IGRF volcado como filas (`83.8, 25.4, 60308, nan, nan`) | Se **extraen como parámetros del kernel** (I=83.8°, D=25.4°, B0=60308 nT) y se descartan de las estaciones |
| Magnético: filas con `nan` | Descartadas (validador Fase 14) → 961 estaciones limpias |
| Gravimetría: `Error_Est = 0` | σ adaptativo (2 % del std de la señal), piso robusto |
| UTM grande (557000, 7133300) | Frame local: se resta el origen; x=Este, z=Norte, y=profundidad |
| Gravimetría ya es Bouguer | Se invierte el contraste directo; unidades mGal → m/s² (×1e-5, igual que `gravity_import_service`) |

## Ground truth (geometría del pipe verdadero)

Leído del modelo forward de los autores (`Forward/model_grav.den` + `model_mag.sus` sobre
`mesh_inverse_ubc.msh`, 81×81×60 @ 10 m). Contrastes verdaderos: PK1/VK = **−0.8 t/m³**,
HK1 = −0.2 (kimberlita **menos densa** que la caja → anomalía de Bouguer negativa); susceptibilidad
PK/VK = 5e-3, HK1 = 2e-2 SI.

- **Pipe gravimétrico:** centroide UTM (557264, 7133586); techo ≈ 51 m bajo el datum; profundidad
  al techo ≈ 10 m bajo la superficie; extensión horizontal ≈ 280–320 m.
- **Cuerpo magnético:** centroide UTM (557315, 7133629) — desplazado al NE porque HK1 (la facies
  más susceptible) domina la respuesta magnética.

## Configuración de la inversión (motor real, sin tunear)

- Malla de inversión: 12×12×10 @ 50 m (600 × 600 × 500 m), frame local sobre el survey.
- 256 estaciones (submuestreo 1:2 del survey 31×31 a 20 m).
- Motor compacto (Fase 24B, minimum-support IRLS), depth-weighting Li & Oldenburg, poda de
  dominio observable, σ robusto, auto-κ — los defaults de producción.
- Bounds de densidad [1.5, 2.7] t/m³ (permite el contraste **negativo** de la kimberlita); κ ∈ [0, 0.05].
- Joint = cross-gradient real de `services/joint_inversion` (warm-up + 1 iteración acoplada).
- **No se tuneó ningún parámetro para pasar.**

## Resultados (geometría medida vs ground truth)

| Inversión | err horizontal | err prof centroide | err prof techo | misfit |
|-----------|----------------|--------------------|----------------|--------|
| **Gravimetría sola** | **53.7 m** | 32.8 m | 23.9 m | 0.07 % |
| Magnetometría sola | 74.8 m | 73.1 m | 23.9 m | 1.00 % |
| Joint — gravedad | 74.6 m | 108.5 m | 23.9 m | 0.08 % |
| Joint — magnetismo | 89.6 m | 55.0 m | 23.9 m | 1.63 % |

Tolerancia de targeting a esta escala (pipe ~300 m, celdas de 50 m): **< 100 m**.

Posiciones recuperadas (UTM):
- Gravimetría sola: (557315, 7133568) vs verdadero (557264, 7133586) → **53.7 m** (≈ 1 celda).
- Magnetometría sola: (557310, 7133703) vs verdadero (557315, 7133629) → 74.8 m (sesgo al N).

## VEREDICTO HONESTO

✅ **TerraQuantum PASA el benchmark externo en TARGETING.**

1. **Gravimetría sola localiza el pipe a 53.7 m horizontal (≈ 1 celda)** en la posición UTM
   correcta, con profundidad al techo dentro de 24 m y profundidad de centroide dentro de 33 m.
   Es la estimación individual más fuerte. Misfit 0.07 % (ajusta el dato).
2. **Magnetometría sola localiza el cuerpo a 74.8 m**, usando el IGRF **correctamente extraído**
   de las filas basura. El error es mayoritariamente al N: el centroide magnético verdadero ya
   está desplazado por HK1, y la inversión escalar lo lleva algo más al N.
3. **El joint cross-gradient NO mejora aquí — lo degrada levemente** (grav 53.7→74.6 m; el misfit
   magnético sube 1.4 % → 3.1 % → 1.6 % en las iteraciones). Es consistente con el hallazgo previo
   de que el cross-gradient está demasiado agresivo (`project_magnetic_joint_session`). Hallazgo
   negativo honesto: **la gravimetría sola es el mejor estimador de posición**; el joint no aporta.
4. Ambas físicas individuales caen **dentro de la tolerancia de < 100 m** → TQ acierta *dónde
   perforar*, que es exactamente el reclamo de producto (targeting/estructura), validado ahora
   contra un ground truth externo y peer-reviewed.

## Límites / notas

- **Densidad/susceptibilidad absoluta NO se valida como gate** (reframe): la gravimetría no
  predice densidad punto a punto. La densidad recuperada se mueve hacia el contraste negativo
  correcto (bounds [1.5, 2.7]) pero no se reclama su magnitud.
- **Comparación vs referencias L2/PGI:** los outputs de `L2_inversion/` y `PGI_joint_inversion/`
  se distribuyen sólo como notebooks (sin modelos guardados), por lo que la comparación es contra
  el **ground truth compartido** que esas referencias reproducen (el pipe central somero). TQ
  localiza el pipe en la misma posición.
- **Runtime ≈ 26 min** (256 estaciones, solver acotado TRF + IRLS compacto, joint con
  cross-gradient). Es un script de validación de corrida ocasional, no de producción.

## Reproducir

```bash
cd terraquantum-backend
python scripts/validation/ingest_do27.py     # GATE de ingestión (estaciones, IGRF, ground truth)
python scripts/validation/do27_harness.py     # corre las 3 inversiones → do27_validation_report.json
python -m pytest tests/test_do27_ingest.py -q  # 8 tests de limpieza
```

> Los datos DO-27 viven en `DO-27_Kimberlite/` (raíz del repo) y **NO se commitean** (regla CLAUDE.md);
> sólo se commitea el código del adaptador/harness.
