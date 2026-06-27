/**
 * Segment LOD + frustum culling — Fase 6 (Render God-Tier) slice 3.
 *
 * Pure helpers (no React, no store) for rendering very large sets of line
 * segments — the drillhole "1M+ segmentos" case in [[godtier_roadmap_fases_0_8]]
 * Fase 6. Hardware mesh-shaders/meshlets are not available in WebGL2, so this is
 * the honest CPU-side stand-in: frustum-cull the segments and cap how many draw
 * by a budget (nearest-first), plus pick cylinder radial detail by total count.
 *
 * The real GPU-compute version of this culling is slice 4 (WebGPU), which is
 * DEFERRED (Three's WebGPURenderer is experimental in r0.183). `gates.computeCulling`
 * from gpuCapabilities.ts is the seam where that path would plug in.
 *
 * How to verify manually (browser console):
 *   import { chooseRadialSegments } from '@/lib/render/segmentLOD';
 *   console.assert(chooseRadialSegments(5) === 8 && chooseRadialSegments(300000) === 3);
 */

import * as THREE from "three";

const UP = /* @__PURE__ */ new THREE.Vector3(0, 1, 0);

export interface Segment {
  ax: number; ay: number; az: number; // endpoint A
  bx: number; by: number; bz: number; // endpoint B
  value?: number;                       // optional scalar for coloring
}

/** Cylinder radial subdivisions chosen by total segment count (fewer faces when huge). */
export function chooseRadialSegments(total: number): number {
  if (total > 200_000) return 3;
  if (total > 50_000) return 4;
  if (total > 10_000) return 6;
  return 8;
}

/** Midpoint of a segment, written into `out`. */
export function segmentMidpoint(s: Segment, out: THREE.Vector3): THREE.Vector3 {
  return out.set((s.ax + s.bx) / 2, (s.ay + s.by) / 2, (s.az + s.bz) / 2);
}

/** Euclidean length of a segment. */
export function segmentLength(s: Segment): number {
  const dx = s.bx - s.ax, dy = s.by - s.ay, dz = s.bz - s.az;
  return Math.hypot(dx, dy, dz);
}

/**
 * Packs segment bounding spheres into a Float32Array (4 floats per segment:
 * center.xyz, radius) — the upload format for the WebGPU culler (slice 4). Pure.
 */
export function packSegmentSpheres(segments: ReadonlyArray<Segment>): Float32Array {
  const out = new Float32Array(segments.length * 4);
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    out[i * 4] = (s.ax + s.bx) / 2;
    out[i * 4 + 1] = (s.ay + s.by) / 2;
    out[i * 4 + 2] = (s.az + s.bz) / 2;
    out[i * 4 + 3] = segmentLength(s) * 0.5;
  }
  return out;
}

/**
 * Extracts the 6 frustum planes from a view-projection matrix into a Float32Array
 * of 24 (6 × [nx, ny, nz, constant]) — the uniform format for the WebGPU culler.
 * Same plane convention as THREE.Frustum, so the GPU result matches the CPU path.
 */
export function extractFrustumPlanes(viewProj: THREE.Matrix4): Float32Array {
  const frustum = new THREE.Frustum().setFromProjectionMatrix(viewProj);
  const out = new Float32Array(24);
  for (let p = 0; p < 6; p++) {
    const pl = frustum.planes[p];
    out[p * 4] = pl.normal.x;
    out[p * 4 + 1] = pl.normal.y;
    out[p * 4 + 2] = pl.normal.z;
    out[p * 4 + 3] = pl.constant;
  }
  return out;
}

export interface SegmentSelection {
  /** Indices to render this pass (in frustum, within budget). */
  indices: number[];
  /** True if the budget clipped the in-frustum set (i.e. some were dropped). */
  clippedByBudget: boolean;
  /** How many segments were inside the frustum before the budget cap. */
  inFrustumCount: number;
}

/**
 * Selects which segments to draw: keeps those whose bounding sphere intersects
 * the frustum, then — if more than `budget` survive — keeps the nearest `budget`
 * to the camera (a full sort only runs in the over-budget case).
 *
 * NOT a silent cap: `clippedByBudget` / `inFrustumCount` report exactly what was
 * dropped so the caller can surface it (e.g. "mostrando 50k de 1.2M segmentos").
 *
 * Cost is O(n) per call for the frustum test; throttle the caller (e.g. every
 * few frames) for very large n. The O(n log n) sort only happens when clipping.
 */
export function selectVisibleSegments(
  segments: ReadonlyArray<Segment>,
  frustum: THREE.Frustum,
  cameraPos: THREE.Vector3,
  budget: number
): SegmentSelection {
  const mid = new THREE.Vector3();
  const sphere = new THREE.Sphere();
  const visible: number[] = [];
  const dist2: number[] = [];

  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    segmentMidpoint(s, mid);
    // Bounding sphere = midpoint + half-length radius (conservative).
    sphere.center.copy(mid);
    sphere.radius = segmentLength(s) * 0.5;
    if (!frustum.intersectsSphere(sphere)) continue;
    visible.push(i);
    dist2.push(mid.distanceToSquared(cameraPos));
  }

  const inFrustumCount = visible.length;
  if (inFrustumCount <= budget) {
    return { indices: visible, clippedByBudget: false, inFrustumCount };
  }

  // Over budget: keep the nearest `budget` segments.
  const order = visible
    .map((idx, k) => ({ idx, d: dist2[k] }))
    .sort((a, b) => a.d - b.d);
  const indices = order.slice(0, budget).map((o) => o.idx);
  return { indices, clippedByBudget: true, inFrustumCount };
}

/**
 * Composes the instance matrix that maps a unit cylinder (height 1 along +Y,
 * given radius) onto a segment: oriented along B−A, scaled to its length,
 * positioned at its midpoint. Writes into `out`.
 */
export function composeSegmentMatrix(
  s: Segment,
  out: THREE.Matrix4,
  scratch: {
    pos: THREE.Vector3;
    quat: THREE.Quaternion;
    scale: THREE.Vector3;
    dir: THREE.Vector3;
  }
): THREE.Matrix4 {
  const { pos, quat, scale, dir } = scratch;
  const len = segmentLength(s) || 1e-6;
  dir.set(s.bx - s.ax, s.by - s.ay, s.bz - s.az).normalize();
  quat.setFromUnitVectors(UP, dir);
  pos.set((s.ax + s.bx) / 2, (s.ay + s.by) / 2, (s.az + s.bz) / 2);
  scale.set(1, len, 1);
  return out.compose(pos, quat, scale);
}

/** Minimal borehole-sample shape (mirror of frontendApi BoreholeSample geometry). */
export interface BoreholeSampleGeom {
  x_m: number;          // horizontal easting (collar frame)
  z_m: number;          // horizontal northing (collar frame)
  depth_from_m: number; // interval top, depth below datum (positive down)
  depth_to_m: number;   // interval bottom
  density_t_m3?: number | null;
  susceptibility_si?: number | null;
}

export interface BoreholeToSegmentsOptions {
  /**
   * Maps borehole horizontal/depth coordinates into the SCENE/model frame.
   * REQUIRED for correct placement: borehole x_m/z_m are UTM/local and the voxel
   * model is re-centered, so the identity transform will mis-place drillholes.
   * Returns the scene-space [x, y, z] for a given (x_m, z_m, depth_below_datum).
   * Default identity with y = -depth (down is −Y) — correct ONLY when the model
   * shares the borehole frame; otherwise pass a real transform.
   */
  toScene?: (x_m: number, z_m: number, depthBelowDatum: number) => [number, number, number];
  /** Scalar to color by. Default: density. */
  value?: (s: BoreholeSampleGeom) => number;
}

/**
 * Converts borehole interval samples into renderable {@link Segment}s for
 * {@link InstancedSegmentsLayer}. Pure; no scene/store/network access.
 *
 * IMPORTANT (honest contract): correct placement requires `toScene` to map the
 * borehole CRS into the re-centered model frame. Without it, the default puts
 * holes at raw x_m/z_m with y = −depth, which only aligns if the model uses the
 * same frame. This adapter does NOT invent that transform — it must be supplied
 * (and visually QA'd) by the caller, which is the remaining gate for wiring.
 */
export function boreholeSamplesToSegments(
  samples: ReadonlyArray<BoreholeSampleGeom>,
  options: BoreholeToSegmentsOptions = {}
): Segment[] {
  const toScene =
    options.toScene ?? ((x: number, z: number, d: number): [number, number, number] => [x, -d, z]);
  const value = options.value ?? ((s) => s.density_t_m3 ?? 0);
  const out: Segment[] = [];
  for (const s of samples) {
    if (!Number.isFinite(s.depth_from_m) || !Number.isFinite(s.depth_to_m)) continue;
    const a = toScene(s.x_m, s.z_m, s.depth_from_m);
    const b = toScene(s.x_m, s.z_m, s.depth_to_m);
    out.push({
      ax: a[0], ay: a[1], az: a[2],
      bx: b[0], by: b[1], bz: b[2],
      value: value(s),
    });
  }
  return out;
}
