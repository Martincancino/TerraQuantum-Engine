"use client";

import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useAppStore } from "../store/useAppStore";

/**
 * MagnetizationVectors — FASE 20C (frontend, iteración 2).
 *
 * Campo de FLECHAS 3D de la magnetización recuperada por la inversión vectorial (MVI).
 * Cada glifo (cono) se ubica en su vóxel, se orienta por la dirección invertida
 * (inc/dec) y se escala por la amplitud |M| (susceptibility_si). Overlay independiente
 * del viewMode; se monta en el MISMO grupo de coordenadas que los vóxeles, por lo que
 * el eje de mundo coincide (x=Norte, y=prof, z=Este) y la dirección f̂ mapea directo.
 *
 * Frontend PURO: sólo dibuja valores invertidos por el backend, no calcula física. La
 * reconstrucción de f̂ desde (inc,dec) y el quaternion de orientación son geometría de
 * presentación. Capado a MAX_ARROWS por amplitud para no degradar el render.
 */

type Props = {
  elevationEnabled: boolean;
  refElev: number;
  clippingPlanes?: THREE.Plane[];
};

// Tope de glifos: en modelos densos sólo se dibujan los de mayor |M| (los relevantes
// para targeting). Evita decenas de miles de conos.
const MAX_ARROWS = 2500;
const UP = new THREE.Vector3(0, 1, 0);

function cellNum(cell: Record<string, unknown>, keys: string[], fb = 0): number {
  for (const k of keys) {
    const v = Number(cell[k]);
    if (Number.isFinite(v)) return v;
  }
  return fb;
}

export default function MagnetizationVectors({
  elevationEnabled,
  refElev,
  clippingPlanes,
}: Props) {
  const model = useAppStore((s) => s.model);
  const showMviVectors = useAppStore((s) => s.showMviVectors);
  const voxelScale = useAppStore((s) => s.voxelScale);

  // ── Selección y datos de los glifos (memo sobre modelo/elevación) ──────────
  const arrows = useMemo(() => {
    const cells = model?.cells as Array<Record<string, unknown>> | undefined;
    if (!cells || cells.length === 0) return null;

    type Item = { x: number; y: number; z: number; inc: number; dec: number; a: number };
    const items: Item[] = [];
    let maxAmp = 0;
    for (const c of cells) {
      const inc = Number(c["magnetization_inc_deg"]);
      const dec = Number(c["magnetization_dec_deg"]);
      if (!Number.isFinite(inc) || !Number.isFinite(dec)) continue; // sólo celdas MVI
      const ampRaw = Number(c["susceptibility_si"]);
      const a = Number.isFinite(ampRaw) ? Math.max(0, ampRaw) : 0;
      const x = cellNum(c, ["x", "cx"]);
      const elev = Number(c["voxel_elevation_masl"]);
      const y = elevationEnabled && Number.isFinite(elev) ? elev - refElev : cellNum(c, ["y", "cy"]);
      const z = cellNum(c, ["z", "cz"]);
      items.push({ x, y, z, inc, dec, a });
      if (a > maxAmp) maxAmp = a;
    }
    if (items.length === 0) return null;

    items.sort((p, q) => q.a - p.a); // mayor amplitud primero
    return {
      kept: items.slice(0, MAX_ARROWS),
      maxAmp: maxAmp > 0 ? maxAmp : 1,
      cellSize: model?.cellSize || 10,
    };
  }, [model, elevationEnabled, refElev]);

  const meshRef = useRef<THREE.InstancedMesh>(null);
  const count = arrows ? arrows.kept.length : 0;

  // ── Escribir las matrices de instancia (posición + orientación + escala) ───
  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || !arrows || !showMviVectors) return;

    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const pos = new THREE.Vector3();
    const dir = new THREE.Vector3();
    const scl = new THREE.Vector3();
    const cs = arrows.cellSize * voxelScale;

    for (let i = 0; i < arrows.kept.length; i++) {
      const it = arrows.kept[i];
      const I = (it.inc * Math.PI) / 180;
      const D = (it.dec * Math.PI) / 180;
      // f̂ = (cosI·cosD, sinI, cosI·sinD) — mismos ejes que la malla de vóxeles.
      dir.set(Math.cos(I) * Math.cos(D), Math.sin(I), Math.cos(I) * Math.sin(D));
      if (dir.lengthSq() < 1e-9) dir.set(0, 1, 0);
      dir.normalize();
      q.setFromUnitVectors(UP, dir);

      // Largo ∝ √(|M|/|M|max): raíz comprime el rango para que los cuerpos débiles
      // sigan visibles. Ancho fijo. Glifo centrado en el vóxel.
      const ampNorm = Math.sqrt(Math.min(1, it.a / arrows.maxAmp));
      const len = cs * (0.6 + 1.6 * ampNorm);
      const wid = cs * 0.16;
      pos.set(it.x, it.y, it.z);
      scl.set(wid, len, wid);
      m.compose(pos, q, scl);
      mesh.setMatrixAt(i, m);
    }
    mesh.count = arrows.kept.length;
    mesh.instanceMatrix.needsUpdate = true;
  }, [arrows, voxelScale, showMviVectors]);

  if (!showMviVectors || count === 0) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, count] as unknown as [THREE.BufferGeometry, THREE.Material, number]}
      frustumCulled={false}
      renderOrder={3}
    >
      {/* Cono unitario (radio 1, alto 1) con ápice en +Y → orientado por el quaternion. */}
      <coneGeometry args={[1, 1, 10]} />
      <meshStandardMaterial
        color="#e879f9"
        emissive="#a21caf"
        emissiveIntensity={0.55}
        metalness={0.1}
        roughness={0.5}
        toneMapped={false}
        clippingPlanes={clippingPlanes}
      />
    </instancedMesh>
  );
}
