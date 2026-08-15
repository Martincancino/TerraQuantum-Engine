# Datos de prueba para el flujo 3D (isosuperficies F4)

3 CSV de un **mismo cuerpo** (esfera densa y magnética enterrada), generados por
física analítica para que la inversión recupere un cuerpo compacto y las
isosuperficies del visor 3D se vean claras.

## Archivos
- `demo_gravimetria.csv` — 441 estaciones, anomalía de Bouguer (mGal). Pico ~1.05 mGal.
- `demo_magnetometria.csv` — 441 estaciones, TMI (nT). Rango ~[−64, +206] nT.
- `demo_sondajes.csv` — 4 pozos verticales; 3 cortan la magnetita, 1 (DDH-04) es control negativo.

Todas las coordenadas son **locales** (Este/Norte en metros, 0–2000). Superficie plana a 1000 m.

## El cuerpo (verdad conocida)
- Centro horizontal (Este, Norte) = **(1000, 1000) m**.
- Profundidad al centro = **300 m**; radio = **150 m** → el cuerpo va de **~150 a ~450 m** de profundidad.
- Densidad del cuerpo **3.70** g/cc (fondo 2.70; contraste +1.0). Susceptibilidad **0.15** SI.

## Qué deberías ver en el 3D
- Un **cuerpo compacto** centrado bajo la estación (1000, 1000), entre ~150 y ~450 m de profundidad.
- Al activar **"Isosuperficies (mallas suaves)"**: superficies suaves (no cubos)
  encerrando ese cuerpo, en amarillo (exceso de densidad), **alineadas** con los vóxeles.
- Los sondajes DDH-01/02/03 deberían **atravesar** el cuerpo; DDH-04 queda afuera.

## Regenerar
`python generar_demo.py` (usa numpy). El escenario está documentado en el script.
