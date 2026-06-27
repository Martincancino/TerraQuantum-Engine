/**
 * Volume texture builder — Fase 6 (Render God-Tier) slice 2.
 *
 * Pure data transform (no React, no store): turns the SAME in-memory voxel cells
 * that Scene3D already renders as instanced meshes into a `THREE.Data3DTexture`
 * suitable for ray-marching. Frontend-only: it reads cells already in the app —
 * NOTHING is fetched from the backend, no physics is computed here.
 *
 * This is the realistic stand-in for "NanoVDB HDDA ray-marching" called out in
 * [[godtier_roadmap_fases_0_8]] Fase 6: a dense Data3DTexture marched in a
 * fragment shader (WebGL2), gated by capability (see gpuCapabilities.ts).
 *
 * Texture layout (UNORM8 RGBA, x-fastest):
 *   index = (ix + nx*(iy + ny*iz)) * 4
 *   .r = value normalised to [0,1] over [valueRange] (8-bit)
 *   .a = occupancy mask: 255 if a real active cell occupies the voxel, else 0
 * UNORM8 is chosen over float on purpose: it is ALWAYS linear-filterable in
 * WebGL2 (no OES_texture_float_linear needed) and quarters the memory. 8-bit is
 * ample for visualisation; the precise numbers stay in the parquet/voxel model.
 *
 * How to verify manually (browser console, no test runner):
 *   import { buildVolumeTexture } from '@/lib/render/buildVolumeTexture';
 *   const cells = [{x:0,y:0,z:0,v:1},{x:10,y:0,z:0,v:0}];
 *   const g = buildVolumeTexture(cells, c=>c.x, c=>c.y, c=>c.z, c=>c.v);
 *   console.assert(g && g.dims[0] === 2 && g.filledCount === 2);
 */

import * as THREE from 'three';

export type VolumeCell = Record<string, unknown>;

export interface VolumeGrid {
  /** Dense RGBA UNORM8 3D texture, ready to bind (needsUpdate already set). */
  texture: THREE.Data3DTexture;
  /** Lattice resolution [nx, ny, nz]. */
  dims: [number, number, number];
  /** Per-axis cell size in world units [dx, dy, dz]. */
  cellSize: [number, number, number];
  /**
   * World-space size of the volume box [sx, sy, sz] = dims * cellSize.
   * Build a centered BoxGeometry of this size and march it in geometry-local
   * space (see VolumeRaymarchLayer) so any parent transform stays correct.
   */
  worldSize: [number, number, number];
  /** World-space center of the volume (cell-center min..max midpoint). */
  center: [number, number, number];
  /** [min, max] of the raw values used for normalisation. */
  valueRange: [number, number];
  /** Number of voxels that received a real active cell. */
  filledCount: number;
}

export interface BuildVolumeOptions {
  /**
   * Hard cap on total voxels (nx*ny*nz). Above this, returns null instead of
   * allocating — the caller must degrade (e.g. keep the instanced renderer).
   * NOT a silent truncation: null is an explicit "too big to raymarch".
   * Default 2,000,000 (≈8 MB UNORM8 RGBA).
   */
  maxVoxels?: number;
  /**
   * Optional fixed normalisation range. When omitted, the data min/max is used.
   * Pass a stable range to keep colors consistent across frames/layers.
   */
  valueRange?: [number, number];
  /** Treat a cell as inactive (skipped) when this returns false. Default: all active. */
  isActive?: (cell: VolumeCell) => boolean;
}

const DEFAULT_MAX_VOXELS = 2_000_000;

/** Minimum positive gap between sorted unique values, or `fallback` if < 2 values. */
function minGap(values: number[], fallback: number): number {
  if (values.length < 2) return fallback;
  const sorted = [...values].sort((a, b) => a - b);
  let m = Infinity;
  for (let i = 1; i < sorted.length; i++) {
    const d = sorted[i] - sorted[i - 1];
    if (d > 1e-6 && d < m) m = d;
  }
  return m < Infinity ? m : fallback;
}

/**
 * Builds a dense 3D texture from voxel cells. Returns null when there is no data
 * or when the lattice would exceed `maxVoxels` (caller degrades gracefully).
 * Never throws on ordinary input.
 */
export function buildVolumeTexture(
  cells: ReadonlyArray<VolumeCell>,
  getX: (cell: VolumeCell) => number,
  getY: (cell: VolumeCell) => number,
  getZ: (cell: VolumeCell) => number,
  getValue: (cell: VolumeCell) => number,
  options: BuildVolumeOptions = {}
): VolumeGrid | null {
  if (!cells || cells.length === 0) return null;

  const maxVoxels = options.maxVoxels ?? DEFAULT_MAX_VOXELS;
  const isActive = options.isActive;

  // ── Pass 1: collect coordinate axes and value extent over active cells ──────
  const xs: number[] = [];
  const ys: number[] = [];
  const zs: number[] = [];
  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;
  let minZ = Infinity, maxZ = -Infinity;
  let vMin = Infinity, vMax = -Infinity;

  const active: VolumeCell[] = [];
  for (const cell of cells) {
    if (isActive && !isActive(cell)) continue;
    const x = getX(cell);
    const y = getY(cell);
    const z = getZ(cell);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    const v = getValue(cell);
    if (!Number.isFinite(v)) continue;

    active.push(cell);
    xs.push(x); ys.push(y); zs.push(z);
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    if (v < vMin) vMin = v; if (v > vMax) vMax = v;
  }
  if (active.length === 0) return null;

  const fb = 10;
  const dx = minGap(xs, fb);
  const dy = minGap(ys, fb);
  const dz = minGap(zs, fb);

  // Lattice from RANGE/spacing (not unique-count): robust to sparse active cells
  // that leave whole rows empty.
  const nx = Math.max(1, Math.round((maxX - minX) / dx) + 1);
  const ny = Math.max(1, Math.round((maxY - minY) / dy) + 1);
  const nz = Math.max(1, Math.round((maxZ - minZ) / dz) + 1);

  const total = nx * ny * nz;
  if (total > maxVoxels) return null;

  const [rangeMin, rangeMax] = options.valueRange ?? [vMin, vMax];
  const span = rangeMax - rangeMin;
  const norm = (v: number): number =>
    span > 1e-12 ? Math.min(1, Math.max(0, (v - rangeMin) / span)) : 0.5;

  // ── Pass 2: scatter into the dense RGBA buffer ──────────────────────────────
  const data = new Uint8Array(total * 4); // zero-filled → mask 0 (air) everywhere
  let filledCount = 0;
  for (const cell of active) {
    const ix = Math.min(nx - 1, Math.max(0, Math.round((getX(cell) - minX) / dx)));
    const iy = Math.min(ny - 1, Math.max(0, Math.round((getY(cell) - minY) / dy)));
    const iz = Math.min(nz - 1, Math.max(0, Math.round((getZ(cell) - minZ) / dz)));
    const base = (ix + nx * (iy + ny * iz)) * 4;
    if (data[base + 3] === 0) filledCount++;
    data[base] = Math.round(norm(getValue(cell)) * 255);
    data[base + 3] = 255; // occupancy mask
  }

  const texture = new THREE.Data3DTexture(data, nx, ny, nz);
  texture.format = THREE.RGBAFormat;
  texture.type = THREE.UnsignedByteType;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.wrapR = THREE.ClampToEdgeWrapping;
  texture.unpackAlignment = 1;
  texture.needsUpdate = true;

  return {
    texture,
    dims: [nx, ny, nz],
    cellSize: [dx, dy, dz],
    worldSize: [nx * dx, ny * dy, nz * dz],
    center: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2],
    valueRange: [rangeMin, rangeMax],
    filledCount,
  };
}
