"use client";

import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import { useAppStore } from "../../store/useAppStore";

/**
 * F5 — Puente invisible montado dentro de <Canvas> que registra en el store
 * una función de captura PNG de alta resolución: sube temporalmente el
 * pixelRatio del renderer, fuerza UN frame, lee los píxeles ya renderizados
 * (toDataURL) y restaura el estado — no calcula física, solo compone la
 * imagen que el propio Three.js ya dibuja.
 */
export default function CanvasExportBridge() {
  const { gl, scene, camera } = useThree();
  const setCapturePngSnapshot = useAppStore((s) => s.setCapturePngSnapshot);

  useEffect(() => {
    const capture = (targetWidthPx: number): string => {
      const prevRatio = gl.getPixelRatio();
      const size = gl.getSize(new THREE.Vector2());
      const currentWidthPx = Math.max(1, size.width * prevRatio);
      const scale = Math.max(1, Math.min(4, targetWidthPx / currentWidthPx));
      try {
        gl.setPixelRatio(prevRatio * scale);
        gl.render(scene, camera);
        return gl.domElement.toDataURL("image/png");
      } finally {
        gl.setPixelRatio(prevRatio);
        gl.render(scene, camera);
      }
    };
    setCapturePngSnapshot(capture);
    return () => setCapturePngSnapshot(null);
  }, [gl, scene, camera, setCapturePngSnapshot]);

  return null;
}
