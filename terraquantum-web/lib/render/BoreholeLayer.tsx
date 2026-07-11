"use client";

/**
 * Capa de SONDAJES del backend — Fase F4.4 (contexto geológico en el 3D).
 *
 * Dibuja los intervalos de sondaje (GET /borehole/view) como cilindros verticales
 * en el MISMO grupo centrado que los vóxeles/isosuperficies → caen donde está el
 * cuerpo. Contrato de desacople (igual que IsosurfaceMeshLayer): recibe los datos
 * ya parseados y en coordenadas del visor; el frontend NO calcula física ni
 * coordenadas. El color (por litología, o por densidad si no hay) es visualización.
 */

import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { sampleDensityViridis } from "../terraQuantumGeology";

export interface BoreholeInterval {
  cx: number;
  cz: number;
  cy_top: number;
  cy_bot: number;
  depth_from_m: number;
  depth_to_m: number;
  density_t_m3: number | null;
  susceptibility_si: number | null;
  lithology: string | null;
  signed_contrast: number | null;
}

export interface BoreholeCollar {
  cx: number;
  cz: number;
  cy_top: number;
}

export interface BoreholeViewData {
  intervals: BoreholeInterval[];
  collars: BoreholeCollar[];
  n_intervals: number;
  n_holes: number;
  colormap: string;
  background: number | null;
  scale: number | null;
  warnings: string[];
  error: string | null;
}

export interface BoreholeLayerProps {
  data: BoreholeViewData | null;
  visible?: boolean;
  clippingPlanes?: THREE.Plane[] | null;
  /** Radio del cilindro en metros (grosor del sondaje). Default 12. */
  radius?: number;
}

// Paleta de litologías (ES/EN). Asignar color a un nombre de roca es visualización
// estándar de sondajes, no física.
const LITHO_COLORS: Record<string, [number, number, number]> = {
  magnetita: [0.70, 0.13, 0.17], magnetite: [0.70, 0.13, 0.17],
  andesita: [0.55, 0.57, 0.61], andesite: [0.55, 0.57, 0.61],
  granito: [0.85, 0.55, 0.72], granite: [0.85, 0.55, 0.72],
  basalto: [0.24, 0.24, 0.26], basalt: [0.24, 0.24, 0.26],
  sulfuro: [0.79, 0.63, 0.15], sulfide: [0.79, 0.63, 0.15],
  sulfuro_masivo: [0.79, 0.63, 0.15],
  caliza: [0.75, 0.86, 0.93], limestone: [0.75, 0.86, 0.93],
  diorita: [0.45, 0.52, 0.45], diorite: [0.45, 0.52, 0.45],
  toba: [0.80, 0.74, 0.55], tuff: [0.80, 0.74, 0.55],
};

function hashHueColor(name: string): [number, number, number] {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const hue = (h % 360) / 360;
  const c = new THREE.Color();
  c.setHSL(hue, 0.5, 0.6);
  return [c.r, c.g, c.b];
}

function colorForInterval(iv: BoreholeInterval): [number, number, number] {
  if (iv.lithology) {
    const key = iv.lithology.trim().toLowerCase();
    return LITHO_COLORS[key] ?? hashHueColor(key);
  }
  if (iv.signed_contrast !== null && Number.isFinite(iv.signed_contrast)) {
    // Mismo mapeo que la isosuperficie/vóxeles: u = 0.5 + 0.5·contraste.
    return sampleDensityViridis(0.5 + 0.5 * iv.signed_contrast);
  }
  return [0.6, 0.6, 0.6];
}

export default function BoreholeLayer({
  data,
  visible = false,
  clippingPlanes = null,
  radius = 12,
}: BoreholeLayerProps) {
  const mesh = useMemo<THREE.InstancedMesh | null>(() => {
    if (!visible || !data || !data.intervals || data.intervals.length === 0) return null;

    const planes = clippingPlanes && clippingPlanes.length > 0 ? clippingPlanes : undefined;
    const geometry = new THREE.CylinderGeometry(radius, radius, 1, 12);
    const material = new THREE.MeshStandardMaterial({
      roughness: 0.55,
      metalness: 0.15,
      side: THREE.DoubleSide,
      clippingPlanes: planes,
    });
    const im = new THREE.InstancedMesh(geometry, material, data.intervals.length);
    const dummy = new THREE.Object3D();
    const col = new THREE.Color();

    data.intervals.forEach((iv, i) => {
      const height = Math.max(Math.abs(iv.cy_top - iv.cy_bot), 1);
      const midY = (iv.cy_top + iv.cy_bot) / 2;
      dummy.position.set(iv.cx, midY, iv.cz);
      dummy.scale.set(1, height, 1); // el cilindro base tiene altura 1 en Y
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      im.setMatrixAt(i, dummy.matrix);
      const [r, g, b] = colorForInterval(iv);
      col.setRGB(r, g, b);
      im.setColorAt(i, col);
    });
    im.instanceMatrix.needsUpdate = true;
    if (im.instanceColor) im.instanceColor.needsUpdate = true;
    im.renderOrder = 3; // por encima de la nube fantasma
    im.frustumCulled = false; // evita que se descarte por el bounding por defecto
    return im;
  }, [data, visible, radius, clippingPlanes]);

  // Liberar GPU al cambiar/desmontar.
  useEffect(() => {
    return () => {
      if (mesh) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
        mesh.dispose();
      }
    };
  }, [mesh]);

  if (!mesh) return null;
  return <primitive object={mesh} />;
}
