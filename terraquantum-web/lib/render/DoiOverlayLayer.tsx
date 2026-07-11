"use client";

/**
 * Overlay del horizonte DOI — Fase F4.5 (incertidumbre VISIBLE).
 *
 * Bajo el horizonte de sensibilidad el dato deja de restringir el modelo: lo que
 * se ve ahí es null-space, no información. Esta capa dibuja (1) un plano sutil
 * en el horizonte y (2) un velo oscuro semi-transparente desde ahí hasta el
 * fondo del modelo. Todo viene del backend (GET /v2/doi-overlay, convención B2);
 * el frontend NO calcula física — solo dibuja el plano/velo donde se le indica.
 */

import { useEffect, useMemo } from "react";
import * as THREE from "three";

export interface DoiOverlayData {
  cy_horizon: number | null;
  depth_m: number | null;
  method: string | null;
  cells_below_fraction: number | null;
  extent: {
    cx_min: number;
    cx_max: number;
    cz_min: number;
    cz_max: number;
    cy_min: number;
    cy_max: number;
  } | null;
  warnings: string[];
  error: string | null;
}

export interface DoiOverlayLayerProps {
  data: DoiOverlayData | null;
  visible?: boolean;
}

export default function DoiOverlayLayer({ data, visible = false }: DoiOverlayLayerProps) {
  const built = useMemo<THREE.Group | null>(() => {
    if (!visible || !data || data.error || data.cy_horizon === null || !data.extent) {
      return null;
    }
    const { cx_min, cx_max, cz_min, cz_max, cy_min } = data.extent;
    const horizon = data.cy_horizon;
    const width = cx_max - cx_min;
    const depth = cz_max - cz_min;
    const veilHeight = horizon - cy_min;
    if (width <= 0 || depth <= 0 || veilHeight <= 0) return null;

    const group = new THREE.Group();
    const centerX = (cx_min + cx_max) / 2;
    const centerZ = (cz_min + cz_max) / 2;

    // 1) Plano del horizonte: línea de advertencia sutil (ámbar translúcido).
    const planeGeom = new THREE.PlaneGeometry(width, depth);
    const planeMat = new THREE.MeshBasicMaterial({
      color: 0xd9a441,
      transparent: true,
      opacity: 0.18,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const plane = new THREE.Mesh(planeGeom, planeMat);
    plane.rotation.x = -Math.PI / 2; // horizontal
    plane.position.set(centerX, horizon, centerZ);
    plane.renderOrder = 1;
    group.add(plane);

    // 2) Velo bajo el horizonte: caja oscura muy tenue = "aquí el dato no ve".
    const veilGeom = new THREE.BoxGeometry(width, veilHeight, depth);
    const veilMat = new THREE.MeshBasicMaterial({
      color: 0x0a0a0f,
      transparent: true,
      opacity: 0.32,
      depthWrite: false,
    });
    const veil = new THREE.Mesh(veilGeom, veilMat);
    veil.position.set(centerX, cy_min + veilHeight / 2, centerZ);
    veil.renderOrder = 1;
    group.add(veil);

    return group;
  }, [data, visible]);

  // Liberar GPU al cambiar/desmontar.
  useEffect(() => {
    return () => {
      if (built) {
        built.traverse((obj) => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry.dispose();
            (obj.material as THREE.Material).dispose();
          }
        });
      }
    };
  }, [built]);

  if (!built) return null;
  return <primitive object={built} />;
}
