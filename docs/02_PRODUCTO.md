# TerraQuantum — DEFINICIÓN DE PRODUCTO (F0)

| Campo | Valor |
|---|---|
| Fecha | 2026-07-02 |
| Estado | ✅ APROBADO por Martín (2026-07-02) — gate F0 cerrado |
| Fuentes | `docs/00_INVESTIGACION_MERCADO.md` + `docs/01_PLAN_MAESTRO.md` + límites físicos medidos |

Este documento responde, para siempre y en una página por sección: **para quién es, qué hace, qué promete y qué NO es**. Toda decisión de desarrollo se contrasta contra esto.

---

## 1. Qué es

**TerraQuantum es el software de inversión geofísica 3D que siempre funciona y siempre dice la verdad.** Convierte datos de gravimetría, magnetometría y sondajes — en el estado en que estén — en un modelo 3D claro para decidir dónde perforar, con la confiabilidad de cada parte del modelo dicha explícitamente.

**En una frase de venta:** *"El modelo 3D más fiel que tus datos permiten — y te dice, celda por celda, cuánto confiar en él."*

## 2. Para quién

- **Usuario primario: el consultor geofísico independiente de LatAm.** Ya paga US$156/día por Leapfrog cuando lo necesita; es experto (poco soporte); usa la herramienta muchas veces al año; y le vende los resultados a las mineras — es decir, **vende TerraQuantum por nosotros**.
- **Cliente final: la junior / pequeña minera / consultora chica** — recibe el resultado a través del consultor, o directamente vía el **servicio productizado** (nosotros operamos el software y entregamos la inversión hecha, US$2–4k/proyecto).
- **Quién NO es el usuario:** la junior sin geofísico comprando software DIY (no compra software, compra respuestas — medido en la investigación de mercado); la major con presupuesto Seequent.

## 3. El camino dorado (la única ruta que tiene que ser perfecta)

> *"Me entregan cualquier CSV de gravimetría/magnetometría/sondajes → lo preparo y el software calcula todo lo que un gabinete calcularía (correcciones, mapas de realce, QA/QC, profundidades de Euler) → invierto con progreso visible → veo un 3D claro con isosuperficies, cortes y sondajes → descargo imágenes, gráficos y un reporte honesto → se lo explico a mi cliente con el copiloto."*

Todo lo que está en este camino es prioridad 1. Todo lo que no está, es negociable.

## 4. Definición de "robusto" (medible, no adjetivo)

1. **Ningún input produce crash ni basura silenciosa.** Todo archivo termina en: resultado válido, o pregunta clara, o error en español del catálogo con acción sugerida. Jamás un 500 pelado, jamás un número corrupto sin aviso.
2. **Ninguna operación deja al usuario sin feedback más de 5 segundos.** Las largas muestran progreso real por etapas y se pueden cancelar.
3. **Los diagnósticos nunca se contradicen.** Veredicto, targets, χ², resolución en profundidad y visor cuentan la misma historia. Cero NaN visibles, cero "—" sin explicación.
4. **Los datos del cliente jamás salen de su máquina sin su acción explícita** (LOCAL-FIRST; el copiloto usa la API key del propio usuario).

## 5. La promesa honesta (y su escalera)

TerraQuantum **no promete "ver la realidad"** — nadie puede (la no-unicidad de campos potenciales es física, no una limitación nuestra). Promete el **proceso que se le acerca**:

| El cliente aporta | El modelo gana |
|---|---|
| Solo gravimetría | Footprint horizontal confiable (50–200 m validado); profundidad = rango honesto |
| + magnetometría | Discriminación del tipo de cuerpo |
| + sondajes con litología | Anclaje geológico |
| + densidades/susceptibilidades MEDIDAS + petrofísica + geología mapeada | Modelo genuinamente acotado — "representativo" es defendible |
| + primer pozo perforado (bucle re-invertir) | Calibración contra la realidad en la zona perforada |
| + ensayos de sondajes (geoestadística F11-G) | Leyes entre pozos con incertidumbre |

La UI pide estos datos explicando qué gana el modelo con cada uno. La incertidumbre siempre se muestra (B1/B2/B3, DOI en el visor): **es el diferenciador y el escudo legal, no una debilidad.**

## 6. Qué NO es (anti-scope, protege el foco)

- **NO estima recursos ni reservas** (JORC/NI 43-101 los firma una Persona Calificada; TQ es *decision support* con disclaimers — prohibido el lenguaje reserve/resource/grade/NPV en salidas del software y del copiloto).
- **NO promete profundidad exacta con potenciales solos** (límite medido: la resuelven el pozo, el downhole EM o físicas EM/MT — Nivel 3-4 del plan).
- **NO interpola ley/densidad entre pozos con gravedad** (eso es geoestadística sobre ensayos — módulo futuro F11-G, con framing de interpolación).
- **NO compite con Leapfrog en modelado geológico** ni con Oasis en procesamiento exhaustivo: compite en robustez + claridad + honestidad + precio + español.
- **NO es una plataforma cloud multi-tenant** (la nube es demo pública; el producto vive en la máquina del cliente).

## 7. Hardware y entorno mínimos ("computador normal", decidido con mediciones)

| Requisito | Mínimo | Recomendado |
|---|---|---|
| SO | Windows 10 x64 | Windows 11 |
| RAM | 8 GB | 16 GB |
| CPU | 4 núcleos | 8+ núcleos (inversiones son CPU-bound) |
| GPU | Integrada (WebGL2) | Dedicada (activa modo WebGPU "presentación") |
| Disco | 2 GB libres | 10 GB (proyectos) |
| Internet | Solo para: instalar, actualizar, copiloto, DEM/satelital online | — |

Presupuestos de rendimiento sobre el mínimo (se testean en F8): ingesta 10k filas <5 s; inversión 30k vóxeles <3 min; render 100k celdas ≥30 fps. Mallas grandes (>50k vóxeles) advierten el tiempo estimado ANTES de correr.

## 8. Idioma y tono

- **UI y errores: español primero** (el nicho es LatAm; es parte del foso). Inglés = fase post-lanzamiento si el mercado lo pide.
- Tono de los mensajes: profesional, directo, sin drama y sin jerga innecesaria; cada error dice **qué pasó y qué hacer**.

## 9. Modelo de negocio (resumen operativo; detalle en 00_INVESTIGACION_MERCADO)

1. **Consultores**: US$50–150/mes o US$300–800/proyecto. 2. **Juniors**: solo por-proyecto US$500–1.500. 3. **Servicio productizado** (desde F5): inversión hecha por nosotros, US$2–4k/proyecto — financia el desarrollo y genera casos. 4. **Tier gratis**: malla limitada + marca de agua = canal de marketing. Ancla de precio del mercado: US$156/día (Seequent Consultants Daily).

## 10. Los 4 datasets canónicos (contra los que se valida todo, siempre)

1. **Esfera sintética** (verdad exacta) — sanidad del motor y de F2B.
2. **DO-27 kimberlita** (53.7 m horizontal validado) — benchmark externo.
3. **Raglan Ni-Cu** (dato de campo crudo, 212 m) — robustez con datos reales.
4. **Laguna del Maule** (CSV crudo español, χ²=0.92) — el camino dorado completo con la peor ingesta realista.
