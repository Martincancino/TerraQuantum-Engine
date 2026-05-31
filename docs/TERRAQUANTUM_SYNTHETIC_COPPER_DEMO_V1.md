# TerraQuantum Synthetic Copper Demo v1

Este documento describe el dataset sintético de demostración **v1**, diseñado exclusivamente para propósitos conceptuales y de prueba del flujo de planificación minera en TerraQuantum.

## 1. Qué es este dataset
Es un dataset de gravimetría **completamente sintético** generado analíticamente. Contiene observaciones de gravedad superficial simuladas sobre un cuerpo de densidad anómala, con ruido gaussiano agregado para imitar condiciones instrumentales realistas. 

El propósito de este dataset es proporcionar una entrada lo suficientemente rica para que el motor de inversión de TerraQuantum (perfil `industrial_demo_v1`) genere un modelo 3D de **20.480 vóxeles** (32x20x32), lo que a su vez permite probar el algoritmo de optimización Lerchs-Grossmann (LG) y el planificador FMS con un nivel de resolución conceptual creíble, superando las limitaciones del anterior modelo mínimo de 64 vóxeles.

## 2. Qué NO es este dataset
> [!WARNING]
> **Aviso de Integridad Geológica**
> - **NO contiene datos reales privados:** Ninguna observación proviene de levantamientos geofísicos reales de operaciones mineras.
> - **NO representa mineral confirmado:** El modelo 3D generado a partir de este dataset es producto de una inversión matemática sobre un modelo sintético. No implica el descubrimiento, cuantificación o confirmación de recursos minerales reales en ninguna coordenada.
> - **NO representa la operación real de Candelaria ni de ninguna otra mina específica.**

## 3. Fuentes públicas de inspiración
El diseño conceptual del cuerpo gravimétrico se inspira de manera muy flexible y simplificada en descripciones públicas genéricas de grandes yacimientos cupríferos (como el rango operativo de rajos tipo Candelaria en Chile), tomando los siguientes parámetros de orden de magnitud:
- Escala del dominio: cientos de metros de profundidad y extensión lateral.
- Contraste de densidad esperado en pórfidos/IOCG: ~0.4 a 0.6 t/m³.

El perfil frontend asociado es **`industrial_demo_v1`**, diseñado para invertir una malla gruesa/conceptual pero defendible como demo tecnológica.

## 4. Parámetros Técnicos del Dataset

### Grilla de Observación
- **Número de estaciones:** 1089 (malla 33x33)
- **Espaciamiento (spacing):** 25 metros
- **Dominio espacial:** X [0 a 800m], Y [0m, superficie], Z [0 a 800m]
- **Unidad:** mGal (Miligales)
- **Ruido instrumental:** Añadido ruido gaussiano reproducible (σ = 0.02 mGal)

### Cuerpo Sintético (Generador)
El "ground truth" sintético se modeló usando una resolución de vóxeles de 12.5m (64x40x64) para evitar el "inverse crime" (donde la inversión utiliza exactamente la misma discretización que la generación de datos).
- **Geometría:** Elipsoide suavizado (halo gaussiano)
- **Centroide:** (X=420m, Y=230m de profundidad, Z=390m)
- **Radios:** Rx=180m, Ry=140m, Rz=170m
- **Contraste máximo:** 0.55 t/m³

### Método de cálculo forward
El CSV se genera con **forward directo por vóxeles no nulos** (`direct_chunked_nonzero_voxels`). Esto significa que:
- **No se construye el kernel CSR completo** durante la generación. El kernel CSR sí lo usa la inversión después, pero el generador no lo necesita.
- Se calcula `gz` sensor por sensor (en chunks de 64) usando solo los vóxeles donde el contraste de densidad supera el cutoff de **0.05 t/m³**. El número exacto de vóxeles activos se imprime al ejecutar el script.
- La convención de signo replica exactamente la de `GravimetryForward` (exploration/gravimetry.py): `dy = y_vox - sy` (vóxel menos sensor). En TerraQuantum, **y positivo = profundidad hacia abajo**, por lo que un contraste positivo bajo un sensor de superficie produce g positiva.
- Esto evita matrices densas gigantes en memoria y mantiene la reproducibilidad exacta.
- La fórmula física es idéntica: `G * V * 1000 * Σ(ρ_j * Δy_ij / r_ij³)`.

## 5. Cómo regenerar el dataset
El script es 100% reproducible y determinista debido al uso de una semilla fija (`SEED = 20260509`).

Desde la raíz del backend, ejecute:
```bash
python scripts/demo/generate_tq_synthetic_copper_demo_v1.py
```
Esto sobrescribirá el archivo CSV en:
`scripts/demo_data/tq_synthetic_copper_demo_v1_bouguer_mgal.csv`

## 6. Instrucciones de uso en TerraQuantum UI
1. Navegue a la vista **Figura 3D**.
2. Cargue el archivo `tq_synthetic_copper_demo_v1_bouguer_mgal.csv`.
3. Seleccione el **Modo Estricto** si lo desea (el archivo cumple todos los requisitos de integridad).
4. Haga clic en "Validar CSV".
5. Seleccione el perfil **"Demo industrial v1"** en la sección de inversión.
6. Haga clic en "Invertir y cargar modelo 3D".

## 7. Resultado Esperado
- El CSV pasará la validación estrictamente.
- El sistema detectará `gravity_type == "synthetic_demo"`.
- Se generará un modelo 3D con un nivel de discretización mayor (20.480 bloques).
- El paso a **Diseño Mina** producirá un rajo conceptual con tiempos de cómputo demostrables, a diferencia de los modelos cúbicos instantáneos anteriores.
