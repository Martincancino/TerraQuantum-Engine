"use client";

/**
 * Instanced segments with LOD + frustum culling — Fase 6 slice 3.
 *
 * Renders a large set of line segments (e.g. drillhole intervals, 1M+ case) as a
 * single InstancedMesh of cylinders. Per-frame it frustum-culls and caps the
 * draw count by a budget (nearest-first), hiding the rest by zeroing their
 * instance matrix — the same trick Scene3D's voxel mesh uses. This is the
 * honest WebGL2 stand-in for hardware mesh-shaders/meshlets; the GPU-compute
 * culling version is slice 4 (WebGPU, deferred).
 *
 * Self-contained (no Scene3D/store import): the caller passes `segments` and
 * mounts it under the scene group. Renders nothing when `visible` is false or
 * there are no segments, so it can never regress the current renderer.
 *
 * NOTE: not yet wired into Scene3D — the 3D scene has no drillhole geometry
 * today (boreholes are uploaded only to anchor the inversion). This is the
 * reusable engine, ready for when collar/path geometry reaches the frontend.
 */

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import {
  type Segment,
  chooseRadialSegments,
  composeSegmentMatrix,
  extractFrustumPlanes,
  packSegmentSpheres,
  selectVisibleSegments,
} from "./segmentLOD";
import { createWebGpuCuller, type WebGpuCuller } from "./webgpuCull";

export interface InstancedSegmentsLayerProps {
  segments: ReadonlyArray<Segment>;
  /** Master on/off. Default false → renders nothing. */
  visible?: boolean;
  /** Cylinder radius in world units. Default 2. */
  radius?: number;
  /** Max segments drawn per frame (nearest-first). Default 50,000. */
  budget?: number;
  /** Recompute culling every N frames (throttle for huge sets). Default 4. */
  cullInterval?: number;
  /** Low/high transfer-function colors for `segment.value` in [0,1]. */
  colorLow?: string;
  colorHigh?: string;
  /** Fixed value range for coloring; omit to auto-range. */
  valueRange?: [number, number];
  /**
   * Opt-in: use WebGPU compute culling (slice 4) instead of the CPU path, when a
   * WebGPU device is available. Default false. Falls back to CPU automatically if
   * WebGPU is absent or until the first GPU mask resolves (double-buffered, so
   * the applied mask is ~1 frame late — expected for GPU culling).
   */
  useGpuCulling?: boolean;
  /** Reports how many were drawn vs in-frustum vs total, and which path ran. */
  onLOD?: (info: {
    drawn: number;
    inFrustum: number;
    total: number;
    mode: "cpu" | "gpu";
  }) => void;
}

const HIDDEN = /* @__PURE__ */ new THREE.Matrix4().makeScale(0, 0, 0);

export default function InstancedSegmentsLayer(props: InstancedSegmentsLayerProps) {
  const {
    segments,
    visible = false,
    radius = 2,
    budget = 50_000,
    cullInterval = 4,
    colorLow = "#38bdf8",
    colorHigh = "#f59e0b",
    valueRange,
    useGpuCulling = false,
    onLOD,
  } = props;

  const meshRef = useRef<THREE.InstancedMesh>(null);
  const frameRef = useRef(0);
  // WebGPU compute-culling state (double-buffered, never awaited mid-frame).
  const cullerRef = useRef<WebGpuCuller | null>(null);
  const maskRef = useRef<Uint32Array | null>(null);
  const inFlightRef = useRef(false);
  const scratch = useRef({
    pos: new THREE.Vector3(),
    quat: new THREE.Quaternion(),
    scale: new THREE.Vector3(),
    dir: new THREE.Vector3(),
    mat: new THREE.Matrix4(),
    frustum: new THREE.Frustum(),
    viewProj: new THREE.Matrix4(),
  });

  const enabled = visible && segments.length > 0;
  const count = enabled ? segments.length : 0;
  const radial = useMemo(() => chooseRadialSegments(count), [count]);

  // One cylinder geometry shared by all instances (unit height along +Y).
  const geometry = useMemo(
    () => new THREE.CylinderGeometry(radius, radius, 1, radial, 1, false),
    [radius, radial]
  );
  const material = useMemo(
    () => new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.1, vertexColors: true }),
    []
  );

  useEffect(() => {
    return () => {
      geometry.dispose();
      material.dispose();
    };
  }, [geometry, material]);

  // Initialize per-instance color from value (one-time per segments/range change).
  const colorRange = useMemo<[number, number]>(() => {
    if (valueRange) return valueRange;
    let lo = Infinity, hi = -Infinity;
    for (const s of segments) {
      const v = s.value ?? 0;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    return Number.isFinite(lo) && hi > lo ? [lo, hi] : [0, 1];
  }, [segments, valueRange]);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;
    const cLow = new THREE.Color(colorLow);
    const cHigh = new THREE.Color(colorHigh);
    const c = new THREE.Color();
    const span = colorRange[1] - colorRange[0] || 1;
    for (let i = 0; i < count; i++) {
      const t = Math.min(1, Math.max(0, ((segments[i].value ?? 0) - colorRange[0]) / span));
      c.copy(cLow).lerp(cHigh, t);
      mesh.setColorAt(i, c);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [segments, count, colorLow, colorHigh, colorRange]);

  // WebGPU culler lifecycle (slice 4). Created only when opted-in and enabled;
  // uploads sphere bounds once per segments change. Null device → CPU fallback.
  useEffect(() => {
    cullerRef.current = null;
    maskRef.current = null;
    inFlightRef.current = false;
    if (!enabled || !useGpuCulling || count === 0) return;

    let disposed = false;
    let local: WebGpuCuller | null = null;
    createWebGpuCuller(count)
      .then((culler) => {
        if (disposed || !culler) {
          culler?.dispose();
          return;
        }
        culler.upload(packSegmentSpheres(segments));
        local = culler;
        cullerRef.current = culler;
      })
      .catch(() => {
        /* no WebGPU → stay on CPU path */
      });
    return () => {
      disposed = true;
      cullerRef.current = null;
      maskRef.current = null;
      inFlightRef.current = false;
      local?.dispose();
    };
  }, [enabled, useGpuCulling, segments, count]);

  // Per-frame (throttled) LOD: frustum cull (GPU compute or CPU) + budget cap.
  useFrame(({ camera }) => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;
    if (frameRef.current++ % Math.max(1, cullInterval) !== 0) return;

    const s = scratch.current;
    s.viewProj.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);

    const shown = new Uint8Array(count);
    let drawn = 0;
    let inFrustum = 0;
    let usedGpu = false;

    const culler = cullerRef.current;
    if (useGpuCulling && culler) {
      // Kick a non-blocking compute cull; apply the most recently resolved mask
      // (double-buffered → ~1 frame latency, expected for GPU culling).
      if (!inFlightRef.current) {
        inFlightRef.current = true;
        const planes = extractFrustumPlanes(s.viewProj);
        culler
          .cull(planes)
          .then((m) => { maskRef.current = m; })
          .catch(() => { /* keep last mask / CPU fallback */ })
          .finally(() => { inFlightRef.current = false; });
      }
      const mask = maskRef.current;
      if (mask && mask.length === count) {
        usedGpu = true;
        // Budget here truncates in index order (NOT nearest-first; that would
        // need a second compute/sort pass). Frustum culling is the GPU win.
        for (let i = 0; i < count; i++) {
          if (mask[i] !== 0) {
            inFrustum++;
            if (drawn < budget) { shown[i] = 1; drawn++; }
          }
        }
      }
    }

    if (!usedGpu) {
      // CPU path (slice 3), also used until the first GPU mask resolves.
      s.frustum.setFromProjectionMatrix(s.viewProj);
      const sel = selectVisibleSegments(segments, s.frustum, camera.position, budget);
      inFrustum = sel.inFrustumCount;
      drawn = sel.indices.length;
      for (const idx of sel.indices) shown[idx] = 1;
    }

    for (let i = 0; i < count; i++) {
      if (shown[i]) {
        composeSegmentMatrix(segments[i], s.mat, s);
        mesh.setMatrixAt(i, s.mat);
      } else {
        mesh.setMatrixAt(i, HIDDEN);
      }
    }
    mesh.instanceMatrix.needsUpdate = true;
    onLOD?.({ drawn, inFrustum, total: count, mode: usedGpu ? "gpu" : "cpu" });
  });

  if (!enabled) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, material, count]}
      frustumCulled={false}
      castShadow
      receiveShadow
    />
  );
}
