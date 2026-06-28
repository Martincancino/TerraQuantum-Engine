/**
 * Reactive update graph — Fase 8.2 (Live Update local) frontend slice.
 *
 * Pure data structure (no React, no store, no physics): the "grafo reactivo
 * dato→celda→superficie→render" of [[godtier_roadmap_fases_0_8]] Fase 8.2. When a
 * backend Live Update (Woodbury rank-k / sub-octree, exploration/gravimetry.py &
 * magnetometry.py) returns a LOCALIZED change — a handful of voxels near a new
 * datum/borehole — this graph answers the only question the render pipeline needs
 * to stay under the <2s "sin reproceso" budget: which downstream artifacts must
 * rebuild, and which can be left untouched?
 *
 * It models the pipeline at CHUNK granularity (data→cell→chunk→{surface,render}):
 * changed voxels map to the fixed-size chunks that contain them, so only those
 * chunks' surface meshes / texture regions refresh — O(changed cells), not
 * O(all cells). The index convention matches buildVolumeTexture EXACTLY:
 *
 *     linear voxel index = ix + nx*(iy + ny*iz)        (ix fastest)
 *
 * Frontend-only: it decides WHAT to refresh; it never computes the new values
 * (that is the backend's Live Update). No backend call is made here, no physics.
 */
import * as THREE from "three";

export interface LatticeDims {
  nx: number;
  ny: number;
  nz: number;
}

export interface DirtyChunk {
  /** Linear chunk id = cx + cnx*(cy + cny*cz). */
  chunkId: number;
  /** Chunk coordinate in the chunk lattice. */
  chunkCoord: [number, number, number];
  /** Linear voxel indices (buildVolumeTexture order) inside this chunk that changed. */
  voxelIndices: number[];
}

const DEFAULT_CHUNK_SIZE = 8;

/** Integer >= 1 guard (lattice/chunk dimensions must be positive integers). */
function asPositiveInt(value: number, label: string): number {
  if (!Number.isFinite(value) || value < 1) {
    throw new Error(`reactiveUpdateGraph: ${label} debe ser un entero >= 1, recibido ${value}.`);
  }
  return Math.floor(value);
}

export class ReactiveUpdateGraph {
  readonly dims: LatticeDims;
  readonly chunkSize: number;
  /** Resolution of the chunk lattice [cnx, cny, cnz] (ceil of dims / chunkSize). */
  readonly chunkDims: [number, number, number];
  readonly totalVoxels: number;

  /** chunkId → set of linear voxel indices marked dirty (deduplicated). */
  private readonly dirty: Map<number, Set<number>> = new Map();

  constructor(dims: LatticeDims, chunkSize: number = DEFAULT_CHUNK_SIZE) {
    const nx = asPositiveInt(dims.nx, "nx");
    const ny = asPositiveInt(dims.ny, "ny");
    const nz = asPositiveInt(dims.nz, "nz");
    this.dims = { nx, ny, nz };
    this.chunkSize = asPositiveInt(chunkSize, "chunkSize");
    this.chunkDims = [
      Math.ceil(nx / this.chunkSize),
      Math.ceil(ny / this.chunkSize),
      Math.ceil(nz / this.chunkSize),
    ];
    this.totalVoxels = nx * ny * nz;
  }

  /** Linear voxel index for (ix, iy, iz), matching buildVolumeTexture. */
  voxelIndex(ix: number, iy: number, iz: number): number {
    const { nx, ny } = this.dims;
    return ix + nx * (iy + ny * iz);
  }

  /** Decode a linear voxel index back to [ix, iy, iz]. */
  voxelCoord(index: number): [number, number, number] {
    const { nx, ny } = this.dims;
    const layer = nx * ny;
    const iz = Math.floor(index / layer);
    const rem = index - iz * layer;
    const iy = Math.floor(rem / nx);
    const ix = rem - iy * nx;
    return [ix, iy, iz];
  }

  /** Chunk id containing voxel coordinate (ix, iy, iz). */
  chunkIdOf(ix: number, iy: number, iz: number): number {
    const cs = this.chunkSize;
    const [cnx, cny] = this.chunkDims;
    const cx = Math.floor(ix / cs);
    const cy = Math.floor(iy / cs);
    const cz = Math.floor(iz / cs);
    return cx + cnx * (cy + cny * cz);
  }

  private inBounds(ix: number, iy: number, iz: number): boolean {
    const { nx, ny, nz } = this.dims;
    return ix >= 0 && ix < nx && iy >= 0 && iy < ny && iz >= 0 && iz < nz;
  }

  /** Mark one voxel dirty by coordinate. Out-of-range coords are ignored. */
  markVoxelDirty(ix: number, iy: number, iz: number): void {
    if (!this.inBounds(ix, iy, iz)) return;
    this.addDirty(this.chunkIdOf(ix, iy, iz), this.voxelIndex(ix, iy, iz));
  }

  /**
   * Mark voxels dirty by LINEAR index (the form a Live Update payload carries:
   * the changed cell positions in buildVolumeTexture order). Out-of-range indices
   * are ignored (defensive — a stale payload never corrupts the graph).
   */
  markVoxelsDirty(linearIndices: Iterable<number>): void {
    for (const raw of linearIndices) {
      const index = Math.floor(raw);
      if (index < 0 || index >= this.totalVoxels) continue;
      const [ix, iy, iz] = this.voxelCoord(index);
      this.addDirty(this.chunkIdOf(ix, iy, iz), index);
    }
  }

  /**
   * Mark an inclusive voxel-coordinate bounding box dirty — the natural output of
   * a sub-octree re-solve (region_center + radius → a local box of changed cells).
   * The box is clamped to the lattice; an empty/inverted box marks nothing.
   */
  markRegionDirty(min: [number, number, number], max: [number, number, number]): void {
    const { nx, ny, nz } = this.dims;
    const x0 = Math.max(0, Math.floor(min[0]));
    const y0 = Math.max(0, Math.floor(min[1]));
    const z0 = Math.max(0, Math.floor(min[2]));
    const x1 = Math.min(nx - 1, Math.floor(max[0]));
    const y1 = Math.min(ny - 1, Math.floor(max[1]));
    const z1 = Math.min(nz - 1, Math.floor(max[2]));
    for (let iz = z0; iz <= z1; iz++) {
      for (let iy = y0; iy <= y1; iy++) {
        for (let ix = x0; ix <= x1; ix++) {
          this.addDirty(this.chunkIdOf(ix, iy, iz), this.voxelIndex(ix, iy, iz));
        }
      }
    }
  }

  private addDirty(chunkId: number, voxelIndex: number): void {
    let set = this.dirty.get(chunkId);
    if (!set) {
      set = new Set<number>();
      this.dirty.set(chunkId, set);
    }
    set.add(voxelIndex);
  }

  hasDirty(): boolean {
    return this.dirty.size > 0;
  }

  /** Number of chunks currently pending a refresh. */
  dirtyChunkCount(): number {
    return this.dirty.size;
  }

  /**
   * Return the MINIMAL set of chunks needing a downstream refresh (surface mesh
   * patch + texture region re-upload), each with its changed voxel indices, then
   * clear the dirty state. Chunks with no changes never appear — that is the whole
   * point: the renderer touches only what moved. Deterministic (sorted by id).
   */
  flushDirtyChunks(): DirtyChunk[] {
    const [cnx, cny] = this.chunkDims;
    const out: DirtyChunk[] = [];
    for (const [chunkId, set] of this.dirty) {
      const layer = cnx * cny;
      const cz = Math.floor(chunkId / layer);
      const rem = chunkId - cz * layer;
      const cy = Math.floor(rem / cnx);
      const cx = rem - cy * cnx;
      out.push({
        chunkId,
        chunkCoord: [cx, cy, cz],
        voxelIndices: Array.from(set).sort((a, b) => a - b),
      });
    }
    out.sort((a, b) => a.chunkId - b.chunkId);
    this.dirty.clear();
    return out;
  }

  /** Drop all pending dirty state without emitting (e.g. on a full rebuild). */
  clear(): void {
    this.dirty.clear();
  }
}

/** A single voxel value update from a Live Update payload (linear index + raw value). */
export interface VoxelTexel {
  index: number;
  value: number;
}

/**
 * Apply an INCREMENTAL patch to an existing RGBA UNORM8 Data3DTexture built by
 * buildVolumeTexture — the render-stage "sin reproceso" of Fase 8.2. Instead of
 * rebuilding the whole texture, it overwrites only the changed voxels in place,
 * using the SAME encoding as buildVolumeTexture (.r = normalised value, .a = 255
 * occupancy) and the same `valueRange` so colours stay consistent across frames.
 *
 * Out-of-range indices are skipped. Returns the number of texels written; sets
 * texture.needsUpdate only when at least one was (no-op patches stay free).
 */
export function applyVolumeTexturePatch(
  texture: THREE.Data3DTexture,
  patch: ReadonlyArray<VoxelTexel>,
  valueRange: [number, number]
): number {
  if (!texture || patch.length === 0) return 0;
  const image = texture.image as { data: ArrayLike<number>; width: number; height: number; depth: number };
  const data = image.data as Uint8Array;
  const texelCount = data.length >> 2; // RGBA → 4 bytes per voxel
  const [rangeMin, rangeMax] = valueRange;
  const span = rangeMax - rangeMin;
  const norm = (v: number): number =>
    span > 1e-12 ? Math.min(1, Math.max(0, (v - rangeMin) / span)) : 0.5;

  let written = 0;
  for (const { index, value } of patch) {
    const i = Math.floor(index);
    if (i < 0 || i >= texelCount) continue;
    const base = i * 4;
    data[base] = Math.round(norm(value) * 255);
    data[base + 3] = 255; // occupancy mask
    written++;
  }
  if (written > 0) texture.needsUpdate = true;
  return written;
}
