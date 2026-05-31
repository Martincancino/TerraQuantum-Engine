"use client";

import { useMemo } from "react";
import {
  EffectComposer,
  N8AO,
  Bloom,
  SMAA,
  Vignette,
} from "@react-three/postprocessing";
import { useAppStore } from "../../store/useAppStore";

/**
 * Postprocessing cinemático del viewport (Fase C).
 *
 * - N8AO: ambient occlusion en espacio de pantalla (oscurece las uniones entre
 *   vóxeles → percepción de volumen y profundidad). El paquete n8ao soporta el
 *   logarithmicDepthBuffer activo en el <Canvas>.
 * - Bloom: glow sutil sobre los vóxeles más brillantes (lectura "volumétrica").
 * - SMAA: antialiasing (el <Canvas> corre con antialias:false a propósito).
 * - Vignette: encuadre cinemático muy leve.
 *
 * Es puramente visual: no altera el modelo físico ni la inversión del backend.
 * Se monta solo cuando postprocessingEnabled está activo; al desmontarse,
 * R3F vuelve al render directo.
 */
export default function PostFX() {
  const enabled = useAppStore((s) => s.postprocessingEnabled);
  const cellSize = useAppStore((s) => s.model?.cellSize);

  // Radio de AO en unidades de mundo, escalado al tamaño de celda del modelo.
  const aoRadius = useMemo(() => Math.max((cellSize || 10) * 2.5, 6), [cellSize]);

  if (!enabled) return null;

  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      <N8AO
        aoRadius={aoRadius}
        distanceFalloff={aoRadius * 0.4}
        intensity={2.1}
        quality="medium"
        halfRes
      />
      <Bloom
        mipmapBlur
        intensity={0.5}
        luminanceThreshold={0.62}
        luminanceSmoothing={0.22}
      />
      <SMAA />
      <Vignette eskil={false} offset={0.32} darkness={0.55} />
    </EffectComposer>
  );
}
