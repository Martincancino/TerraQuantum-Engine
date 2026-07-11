"use client";

/**
 * Cara del corte PINTADA — Fase F4.3 ("cortar la tierra y ver el mineral").
 *
 * Recibe el raster 2D de contraste del backend (GET /v2/section: base64 Float32,
 * NaN = celda no persistida) y lo pinta como textura Viridis sobre un plano
 * colocado EXACTAMENTE en la capa snapeada, en el mismo espacio visual que
 * vóxeles/isosuperficies. Contrato de desacople: el frontend NO calcula física —
 * el contraste viene del backend; mapearlo a color es visualización (idéntico
 * Viridis del resto del visor).
 *
 * Los vértices del plano se colocan directamente según el eje (sin rotaciones):
 *   axis "x" → plano en cx=snap; u=cz, v=cy
 *   axis "y" → plano en cy=snap; u=cx, v=cz
 *   axis "z" → plano en cz=snap; u=cx, v=cy
 */

import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { sampleDensityViridis } from "../terraQuantumGeology";

export interface SectionData {
  axis: "x" | "y" | "z" | null;
  field: string | null;
  position_snapped: number | null;
  u0: number | null;
  v0: number | null;
  du: number | null;
  dv: number | null;
  nu: number;
  nv: number;
  n_cells: number;
  values_b64: string;
  background: number | null;
  scale: number | null;
  colormap: string;
  warnings: string[];
  error: string | null;
}

export interface SectionPaintLayerProps {
  data: SectionData | null;
  visible?: boolean;
}

function b64ToFloat32(b64: string): Float32Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

/** Coloca (u, v, s) del raster en (x, y, z) del visor según el eje. */
function place(axis: "x" | "y" | "z", u: number, v: number, s: number): [number, number, number] {
  if (axis === "x") return [s, v, u];
  if (axis === "y") return [u, s, v];
  return [u, v, s];
}

export default function SectionPaintLayer({ data, visible = false }: SectionPaintLayerProps) {
  const built = useMemo<{ mesh: THREE.Mesh; texture: THREE.DataTexture } | null>(() => {
    if (
      !visible || !data || data.error || data.axis === null ||
      data.position_snapped === null || data.u0 === null || data.v0 === null ||
      data.du === null || data.dv === null || data.nu < 2 || data.nv < 2 ||
      !data.values_b64
    ) {
      return null;
    }

    const values = b64ToFloat32(data.values_b64);
    if (values.length !== data.nu * data.nv) return null;

    // Textura RGBA: contraste → Viridis (u = 0.5 + 0.5·c, mismo mapeo del visor).
    // NaN (celda no persistida = fondo podado por el solver) → color de fondo
    // (u=0.5) con alpha reducido, para cara sólida pero distinguible del dato.
    const rgba = new Uint8Array(data.nu * data.nv * 4);
    for (let i = 0; i < values.length; i++) {
      const c = values[i];
      const isData = Number.isFinite(c);
      const t = isData ? Math.max(0, Math.min(1, 0.5 + 0.5 * c)) : 0.5;
      const [r, g, b] = sampleDensityViridis(t);
      rgba[i * 4] = Math.round(r * 255);
      rgba[i * 4 + 1] = Math.round(g * 255);
      rgba[i * 4 + 2] = Math.round(b * 255);
      rgba[i * 4 + 3] = isData ? 235 : 150;
    }
    const texture = new THREE.DataTexture(rgba, data.nu, data.nv, THREE.RGBAFormat);
    texture.needsUpdate = true;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearFilter;
    texture.colorSpace = THREE.SRGBColorSpace;

    // Extent del plano: centros de celda ± media celda.
    const uMin = data.u0 - data.du / 2;
    const uMax = data.u0 + (data.nu - 1) * data.du + data.du / 2;
    const vMin = data.v0 - data.dv / 2;
    const vMax = data.v0 + (data.nv - 1) * data.dv + data.dv / 2;
    const s = data.position_snapped;
    const axis = data.axis;

    const corners = [
      place(axis, uMin, vMin, s),
      place(axis, uMax, vMin, s),
      place(axis, uMax, vMax, s),
      place(axis, uMin, vMax, s),
    ];
    const positions = new Float32Array(corners.flat());
    // uv.x sigue u (columnas del raster), uv.y sigue v (filas; texel [0,0] = v0).
    const uvs = new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]);
    const indices = new Uint16Array([0, 1, 2, 0, 2, 3]);

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();

    // Sin clippingPlanes a propósito: esta cara ES el corte — el half-space que
    // oculta el material no debe recortar su propia cara pintada.
    const material = new THREE.MeshBasicMaterial({
      map: texture,
      side: THREE.DoubleSide,
      transparent: true,
      depthWrite: true,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.renderOrder = 2;
    return { mesh, texture };
  }, [data, visible]);

  // Liberar GPU al cambiar/desmontar.
  useEffect(() => {
    return () => {
      if (built) {
        built.mesh.geometry.dispose();
        (built.mesh.material as THREE.Material).dispose();
        built.texture.dispose();
      }
    };
  }, [built]);

  if (!built) return null;
  return <primitive object={built.mesh} />;
}
