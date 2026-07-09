"use client";

/**
 * Capa de ISOSUPERFICIES del backend — Fase F4.2 (Render 3D clase mundial).
 *
 * Renderiza las mallas suaves (marching cubes + Taubin) que calcula el backend en
 * GET /v2/isosurface, como reemplazo del "confeti de cubos".  Contrato de desacople
 * (igual que VolumeRaymarchLayer):
 *   - NO importa el store ni ningún cliente de backend: recibe los datos ya
 *     parseados como prop.  El caller (Scene3D) los toma del store.
 *   - Renderiza NADA si no hay datos o `visible` es false → no puede regresar el
 *     render actual (default off).
 *   - Las mallas ya vienen en el espacio visual de Three.js (centrado + flip-Y,
 *     idéntico al transporte Arrow), así que se superponen pixel-a-pixel con los
 *     vóxeles al montarse bajo el MISMO grupo padre.  El frontend NO calcula física:
 *     el color por vértice usa el contraste con signo que envía el backend y el
 *     MISMO Viridis divergente que los vóxeles.
 */

import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { sampleDensityViridis } from "../terraQuantumGeology";

export interface IsosurfaceLevel {
  fraction: number;
  level_value: number;
  n_vertices: number;
  n_faces: number;
  enclosed_volume_m3: number;
  signed_contrast_range: [number, number];
  positions_b64: string;
  normals_b64: string;
  signed_contrast_b64: string;
  indices_b64: string;
}

export interface IsosurfaceData {
  field: string;
  colormap: string;
  background: number | null;
  scale: number | null;
  peak_contrast: number | null;
  weak_anomaly: boolean;
  cell_size: { x: number; y: number; z: number } | null;
  center_m: { x: number; y: number; z: number } | null;
  grid_dims: { nx: number; ny: number; nz: number } | null;
  levels: IsosurfaceLevel[];
  n_levels: number;
  warnings: string[];
  error: string | null;
  source_path?: string | null;
}

export interface IsosurfaceMeshLayerProps {
  /** Datos ya parseados de /v2/isosurface (o null → no renderiza nada). */
  data: IsosurfaceData | null;
  /** Master on/off. Default false. */
  visible?: boolean;
  /** Planos de corte compartidos con la escena (cross-sections cortan la malla). */
  clippingPlanes?: THREE.Plane[] | null;
  /** Multiplicador global de opacidad [0,1]. Default 1. */
  opacity?: number;
}

// base64 (little-endian) → typed array del navegador.
function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function b64ToFloat32(b64: string): Float32Array {
  const bytes = b64ToBytes(b64);
  return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

function b64ToUint32(b64: string): Uint32Array {
  const bytes = b64ToBytes(b64);
  return new Uint32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

/** Opacidad por nivel: el núcleo (fracción alta) más opaco; el manto translúcido. */
function opacityForFraction(fraction: number): number {
  // 0.5 → ~0.55 (translúcido) ; 0.9 → ~0.87 (casi opaco).
  return Math.max(0.35, Math.min(0.92, 0.2 + 0.75 * fraction));
}

interface BuiltGeometry {
  geometry: THREE.BufferGeometry;
  fraction: number;
  key: string;
}

interface BuiltLevel {
  geometry: THREE.BufferGeometry;
  material: THREE.Material;
  renderOrder: number;
  key: string;
}

export default function IsosurfaceMeshLayer({
  data,
  visible = false,
  clippingPlanes = null,
  opacity = 1,
}: IsosurfaceMeshLayerProps) {
  // Geometrías: decode base64 + color por vértice. Dependen SOLO de data/visible,
  // el trabajo PESADO, para no re-decodificar al arrastrar un corte o cambiar opacidad.
  const geometries = useMemo<BuiltGeometry[]>(() => {
    if (!visible || !data || !data.levels || data.levels.length === 0) return [];

    // Núcleo (fracción alta) primero para escribir profundidad antes del manto.
    const levels = [...data.levels].sort((a, b) => b.fraction - a.fraction);

    return levels.map((lvl) => {
      const positions = b64ToFloat32(lvl.positions_b64);
      const normals = b64ToFloat32(lvl.normals_b64);
      const signed = b64ToFloat32(lvl.signed_contrast_b64);
      const indices = b64ToUint32(lvl.indices_b64);

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
      geometry.setIndex(new THREE.BufferAttribute(indices, 1));

      // Color por vértice: u = 0.5 + 0.5·contraste (mismo mapeo que el visor de
      // vóxeles). `signed` ya es (v − fondo) / escala que envía el backend.
      const colors = new Float32Array(signed.length * 3);
      for (let v = 0; v < signed.length; v++) {
        const u = 0.5 + 0.5 * signed[v];
        const [r, g, b] = sampleDensityViridis(u);
        colors[v * 3] = r;
        colors[v * 3 + 1] = g;
        colors[v * 3 + 2] = b;
      }
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      return { geometry, fraction: lvl.fraction, key: `iso-${lvl.fraction}` };
    });
  }, [data, visible]);

  // Liberar geometrías (VRAM) al cambiar/desmontar (sin fugas).
  useEffect(() => {
    return () => {
      for (const g of geometries) g.geometry.dispose();
    };
  }, [geometries]);

  // Materiales: baratos de recrear; se rehacen al cambiar planos de corte u opacidad
  // sin tocar la geometría. Reciben los planos en el constructor (sin mutar memos).
  const built = useMemo<BuiltLevel[]>(() => {
    const planes = clippingPlanes && clippingPlanes.length > 0 ? clippingPlanes : null;
    return geometries.map((g, i) => {
      const levelOpacity = Math.max(
        0.05,
        Math.min(1, opacityForFraction(g.fraction) * opacity)
      );
      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.5,
        metalness: 0.1,
        side: THREE.DoubleSide, // mallas abiertas en el borde muestran interior
        transparent: levelOpacity < 0.999,
        opacity: levelOpacity,
        depthWrite: levelOpacity >= 0.85, // núcleo opaco escribe profundidad
        clippingPlanes: planes,
      });
      return {
        geometry: g.geometry,
        material,
        renderOrder: i, // núcleo (i=0) antes que el manto translúcido
        key: g.key,
      };
    });
  }, [geometries, clippingPlanes, opacity]);

  // Liberar materiales al recrearse/desmontar (la geometría la libera su propio effect).
  useEffect(() => {
    return () => {
      for (const b of built) b.material.dispose();
    };
  }, [built]);

  if (built.length === 0) return null;

  return (
    <group>
      {built.map((b) => (
        <mesh
          key={b.key}
          geometry={b.geometry}
          material={b.material}
          renderOrder={b.renderOrder}
        />
      ))}
    </group>
  );
}
