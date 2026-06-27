# ADR — Fase 6 (Render God-Tier): backend gráfico y ruta de implementación

- **Estado:** Aceptado (decisión inicial de la fase)
- **Fecha:** 2026-06-25
- **Ámbito:** Solo frontend (`terraquantum-web`). No toca física ni backend.
- **Relacionado:** roadmap God-Tier Fase 6; consume las salidas de Fase 5
  (volumen co-registrado densidad/susc/σ y SVDAG categórico).

## Contexto

El roadmap God-Tier define la Fase 6 como "Render God-Tier" con cuatro metas
ambiciosas, escritas pensando en un motor nativo:

1. **Decidir WebGPU vs núcleo nativo Vulkan** (Three.js limita mesh-shaders/RT).
2. **Mesh-shaders + meshlets** para sondajes (1M+ segmentos).
3. **NanoVDB HDDA ray-marching** de isosuperficies + volumen σ.
4. **RTAO** (hardware ray tracing) para oclusión del subsuelo, con refit de
   BLAS solo de lo visible.

Estado real del renderer hoy (verificado en código, no asumido):

- `componentes/Scene3D.tsx` (~1950 líneas) = **Three.js r0.183 + React-Three-Fiber
  v9 sobre WebGL2**. Vóxeles por `InstancedMesh`, `OrbitControls`, sin WebGPU,
  sin NanoVDB.
- Reglas del proyecto (CLAUDE.md): no instalar dependencias sin permiso, no
  refactors globales, confirmar antes de tocar archivos grandes, frontend NO
  calcula física.

Las metas 1–4 en su forma literal (Vulkan nativo, NanoVDB, mesh-shaders de
hardware, RTAO) **no son alcanzables dentro de esta app** sin reescribir el
núcleo de render y añadir dependencias grandes. Forzarlas sería deshonesto con
el patrón God-Tier del proyecto (slices pequeños, opt-in, default = histórico).

## Decisión

### 1. Backend gráfico: **WebGPU como objetivo, WebGL2 como piso garantizado**

Se **descarta un núcleo nativo Vulkan**. Razones:

- TerraQuantum se entrega como app web (Next.js). Un núcleo Vulkan implicaría
  WASM+WebGPU o un binario nativo aparte: cambia el modelo de despliegue entero,
  no es un "slice de fase".
- WebGPU ya cubre el 90% del valor: compute shaders (culling, construcción de
  estructuras), storage buffers grandes, texturas 3D. Es el estándar al que
  converge la web.
- Three.js r0.183 **ya incluye** un `WebGPURenderer` experimental (`three/webgpu`
  + TSL). Eso permite una migración **incremental** del mismo grafo de escena,
  sin tirar Scene3D a la basura.

Por lo tanto: **adoptar WebGPU de forma progresiva sobre Three.js, con WebGL2
como respaldo siempre presente.** Cada ruta God-Tier se activa solo si el probe
de capacidad lo permite, y degrada al renderer instanciado actual si no.

### 2. Las metas, traducidas a lo que ESTE stack puede entregar

| Meta literal del roadmap | Traducción ejecutable aquí | Gate de capacidad |
|---|---|---|
| Núcleo Vulkan | **Descartado.** WebGPU progresivo sobre Three.js | `webgpu.adapterOk` |
| Mesh-shaders + meshlets (sondajes) | LOD instanciado en CPU (WebGL2) → culling por **compute** (WebGPU) | `gates.computeCulling` |
| NanoVDB HDDA ray-marching | Raymarch del volumen σ/densidad vía `Data3DTexture` (WebGL2) → `texture_3d` storage (WebGPU). NanoVDB literal queda fuera (pyopenvdb ni siquiera está instalado en backend) | `gates.volumeRaymarch` |
| RTAO (hardware RT) | SSAO/oclusión por screen-space hoy; RT real diferido a que WebGPU exponga ray queries de forma estable | (diferido) |

### 3. Cómo se decide en runtime

Se añade `lib/render/gpuCapabilities.ts` (este commit): un probe **puro,
SSR-safe, sin React ni Three.js** que detecta WebGPU (adaptador real, no solo
`navigator.gpu`) y WebGL2 (texturas 3D, filtrado float lineal, render targets
float), y deriva los *gates* de Fase 6. Es la mitad legible-por-máquina de este
ADR. Ninguna ruta de render posterior debe asumir capacidad: debe leer
`report.gates.*`.

## Consecuencias

**Positivas**

- La fase arranca con una decisión clara y un contrato de capacidad, sin haber
  tocado Scene3D ni añadido dependencias.
- Cada slice siguiente (raymarch, LOD de sondajes) es opt-in y auto-degradante:
  cero regresión para usuarios en GPUs modestas o sin WebGPU.
- La migración a WebGPU puede ser incremental sobre el mismo grafo R3F.

**Negativas / honestas**

- **No** habrá NanoVDB, mesh-shaders de hardware ni RTAO "de verdad" en el corto
  plazo: son sobre-objetivos para una app web. Se documentan como diferidos, no
  como hechos.
- WebGPU aún no está universalmente disponible (Safari/algunos drivers): por eso
  WebGL2 es piso obligatorio, no opcional.
- El `WebGPURenderer` de Three.js es experimental en r0.183; adoptarlo como
  default requeriría validación amplia. Por ahora es objetivo, no default.

## Plan de slices (orden sugerido, cada uno opt-in)

1. **(hecho — slice 1)** ADR + `gpuCapabilities.ts` probe. Scene3D intacto.
2. **(building blocks hechos — slice 2)** Raymarch volumétrico σ/densidad en
   WebGL2: `lib/render/buildVolumeTexture.ts` (pure, cells→`Data3DTexture` UNORM8,
   cap honesto de vóxeles) + `lib/render/VolumeRaymarchLayer.tsx` (componente R3F
   autocontenido, march en espacio LOCAL, gated por `gates.volumeRaymarch`,
   default `visible=false`). **Aún NO cableado en Scene3D** (eso es slice 2b:
   toggle en el store + montar el layer como hermano del InstancedMesh + QA de
   alineación visual). No toca física: lee las MISMAS celdas que ya tiene el
   frontend.
   2b. **(hecho)** Cableado: `volumeRenderMode` off/fog/iso en el store + montaje
   en Scene3D + panel «Render Volumétrico». **Alineación arreglada**: el raymarch
   se OCULTA en modo elevación (el retículo regular no puede alinear con la Y
   deformada por vóxel) + hint en el panel. Sin elevación alinea por construcción.
3. **(engine hecho — slice 3)** LOD instanciado + frustum culling para sondajes
   (1M+ segmentos): `lib/render/segmentLOD.ts` (puro: cull por esfera + budget
   nearest-first + radial-LOD por conteo) + `lib/render/InstancedSegmentsLayer.tsx`
   (InstancedMesh de cilindros, culling throttled por frame, oculta por matriz
   cero) + adapter puro `boreholeSamplesToSegments` (BoreholeSample→Segment con
   contrato `toScene` explícito). **NO cableado a la escena**: el survey de
   sondajes se descarta tras la prep (PreparacionView guarda solo intervals) y
   sus coords UTM/local NO tienen transform al frame re-centrado del modelo. El
   adapter deja el motor a UN paso (suministrar `toScene` + QA visual de
   ubicación); no se inventa ese transform para no colocar geometría mal.
4. **(IMPLEMENTADO — slice 4)** Culling por compute WebGPU. **Corrección del ADR
   previo**: NO requiere cambiar el `WebGPURenderer` de Three. El culling es una
   *computación*, no render → se crea un device WebGPU STANDALONE vía
   `navigator.gpu` y el resultado (máscara de visibilidad) alimenta el render
   WebGL2 existente. Híbrido legítimo, sin tocar el renderer.
   `lib/render/webgpuCull.ts` = pipeline de compute WGSL real (frustum-cull de
   esferas) + `packSegmentSpheres`/`extractFrustumPlanes` en segmentLOD.ts = el
   par A/B de la versión CPU (slice 3). `@webgpu/types` ya está (vía three), 0 dep
   nueva. Caveat honesto: el HOST compila y bundlea; el WGSL y la ejecución GPU
   los compila/corre el navegador en runtime — NO verificado aquí (sin device
   WebGPU). Readback async ⇒ ~1 frame de latencia (esperado en GPU culling).
   **Cableado A/B (en `InstancedSegmentsLayer`)**: prop `useGpuCulling` (default
   false). Cuando ON y hay device: cada frame throttled lanza un cull NO bloqueante
   y aplica la última máscara resuelta (double-buffer, ref `maskRef`/`inFlightRef`);
   cae a CPU (slice 3) si no hay WebGPU o hasta que resuelva la 1.ª máscara. El
   budget del path GPU trunca en orden de índice (no nearest-first; eso pediría un
   2.º compute/sort). `onLOD` reporta `mode: 'cpu'|'gpu'`. Sigue SIN montar en la
   escena (no hay geometría de sondajes); el A/B vive dentro del layer.
   RTAO por HARDWARE (no confundir con el compute de arriba) sigue siendo un MURO
   EXTERNO duro: WebGPU NO expone `ray_query` en ningún navegador estable hoy (es
   propuesta futura). No es un hedge sobre "Three experimental" — es que el
   navegador no tiene la capacidad. No se finge; el stand-in screen-space (slice
   5) es el sustituto correcto.
5. **(stand-in hecho + RT diferido — slice 5)** AO de subsuelo:
   `lib/render/SubsurfaceAOEffect.tsx` = N8AO screen-space vía
   `@react-three/postprocessing` (YA instalado, sin dep nueva), opt-in default
   OFF, montado en la raíz de Scene3D + toggle en el panel. Es el stand-in
   honesto de "RTAO oclusión subsuelo". **RTAO por hardware sigue DIFERIDO**:
   WebGL2 no expone ray tracing; se reabrirá con ray queries WebGPU estables.
   Caveat: usa `logarithmicDepthBuffer` → radius/falloff puede requerir ajuste;
   QA visual pendiente. **Escala arreglada**: usa `screenSpaceRadius` (radio en
   píxeles) → invariante a la escala de escena (decenas..miles de unidades), sin
   tuning por modelo. Residual honesto: log-depth puede dar inexactitud menor en
   ángulos rasantes (mitigado, no eliminado).

## Cómo verificar este commit

```ts
import { probeGpuCapabilities, summarizeGpuReport } from '@/lib/render/gpuCapabilities';
probeGpuCapabilities().then(r => console.log(summarizeGpuReport(r)));
```

No debe lanzar excepción en SSR (sin `window`/`document`) ni en navegadores sin
WebGPU; en ese caso reporta `backend: 'webgl2'` o `'none'` con su razón.
