"use client";

/**
 * Volumetric ray-march layer — Fase 6 (Render God-Tier) slice 2.
 *
 * An opt-in, self-contained React-Three-Fiber layer that ray-marches the voxel
 * model as a continuous field (isosurface OR σ-fog) instead of drawing one
 * instanced box per cell. It is the realistic WebGL2 stand-in for the roadmap's
 * "NanoVDB HDDA ray-marching isosuperficies + volumen σ".
 *
 * Decoupling contract (deliberate):
 *  - Does NOT import Scene3D, the store, or any backend client. The caller hands
 *    it the SAME `cells` array Scene3D already has, plus accessor callbacks.
 *  - Renders NOTHING when `visible` is false or capability/data gates fail, so
 *    wiring it in cannot regress the current renderer (default = off).
 *  - All math is in geometry-LOCAL space, so it stays correct under any parent
 *    group transform (scale/offset) the caller mounts it under.
 *
 * Placement (when wired into Scene3D, a later slice):
 *   <VolumeRaymarchLayer cells={model.cells} getX={..} getY={..} getZ={..}
 *      getValue={c => getVoxelVisualValue(c, visualLayer)} capable={gate}
 *      visible={volumeMode} mode="fog" />
 * mounted as a sibling of the InstancedMesh under the same group.
 */

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import {
  buildVolumeTexture,
  type VolumeCell,
  type VolumeGrid,
} from "./buildVolumeTexture";

export type VolumeRenderMode = "isosurface" | "fog";

export interface VolumeRaymarchLayerProps {
  /** The voxel cells (same array Scene3D renders as instanced meshes). */
  cells: ReadonlyArray<VolumeCell>;
  getX: (cell: VolumeCell) => number;
  getY: (cell: VolumeCell) => number;
  getZ: (cell: VolumeCell) => number;
  /** Scalar channel to visualise (e.g. density or σ). */
  getValue: (cell: VolumeCell) => number;
  /** Capability gate (from probeGpuCapabilities().gates.volumeRaymarch). */
  capable: boolean;
  /** Master on/off. Default false → renders nothing. */
  visible?: boolean;
  /** "isosurface" (shaded shell) or "fog" (accumulated σ). Default "fog". */
  mode?: VolumeRenderMode;
  /** Normalised iso level in [0,1] for isosurface mode. Default 0.5. */
  isoLevel?: number;
  /** Opacity / fog density multiplier in [0,1]. Default 0.6. */
  opacity?: number;
  /** Ray steps. Higher = smoother, slower. Default 192, capped at 512. */
  steps?: number;
  /** Low/high transfer-function colors (CSS hex). Defaults blue→red. */
  colorLow?: string;
  colorHigh?: string;
  /** Max 3D texture dimension the device supports (from the probe). Default 256. */
  maxTextureDim?: number;
  /** Fixed normalisation range; omit to auto-range from data. */
  valueRange?: [number, number];
  /** Treat a cell as inactive when this returns false. */
  isActive?: (cell: VolumeCell) => boolean;
}

const VERTEX_SHADER = /* glsl */ `
out vec3 vLocalPos;
void main() {
  vLocalPos = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

// GLSL3 fragment: ray-box march in geometry-local space.
const FRAGMENT_SHADER = /* glsl */ `
precision highp float;
precision highp sampler3D;

in vec3 vLocalPos;
out vec4 fragColor;

uniform sampler3D uVolume;
uniform vec3 uHalfSize;     // half extents of the box, local space
uniform vec3 uCamLocal;     // camera position in geometry-local space
uniform int uMode;          // 0 = isosurface, 1 = fog
uniform float uIso;         // iso level [0,1]
uniform float uOpacity;     // fog density / shell opacity
uniform int uSteps;
uniform vec3 uColorLow;
uniform vec3 uColorHigh;

vec3 toUVW(vec3 p) { return (p + uHalfSize) / (2.0 * uHalfSize); }
float sampleV(vec3 uvw) { return texture(uVolume, uvw).r; }
float sampleMask(vec3 uvw) { return texture(uVolume, uvw).a; }

void main() {
  vec3 rayDir = normalize(vLocalPos - uCamLocal);
  vec3 invD = 1.0 / rayDir;
  vec3 t0 = (-uHalfSize - uCamLocal) * invD;
  vec3 t1 = ( uHalfSize - uCamLocal) * invD;
  vec3 tmin = min(t0, t1);
  vec3 tmax = max(t0, t1);
  float tEnter = max(max(tmin.x, tmin.y), tmin.z);
  float tExit  = min(min(tmax.x, tmax.y), tmax.z);
  tEnter = max(tEnter, 0.0);
  if (tExit <= tEnter) discard;

  int steps = uSteps;
  float dt = (tExit - tEnter) / float(steps);
  vec3 texel = (2.0 * uHalfSize) / vec3(textureSize(uVolume, 0));

  vec3 accumColor = vec3(0.0);
  float accumAlpha = 0.0;

  for (int i = 0; i < 512; i++) {
    if (i >= steps) break;
    float t = tEnter + (float(i) + 0.5) * dt;
    vec3 pos = uCamLocal + rayDir * t;
    vec3 uvw = toUVW(pos);
    if (sampleMask(uvw) < 0.5) continue;
    float v = sampleV(uvw);

    if (uMode == 0) {
      if (v >= uIso) {
        // Central-difference gradient → normal for simple lambert shading.
        vec3 e = texel;
        float gx = sampleV(uvw + vec3(e.x, 0.0, 0.0)) - sampleV(uvw - vec3(e.x, 0.0, 0.0));
        float gy = sampleV(uvw + vec3(0.0, e.y, 0.0)) - sampleV(uvw - vec3(0.0, e.y, 0.0));
        float gz = sampleV(uvw + vec3(0.0, 0.0, e.z)) - sampleV(uvw - vec3(0.0, 0.0, e.z));
        vec3 n = normalize(-vec3(gx, gy, gz) + 1e-5);
        float diff = clamp(dot(n, normalize(vec3(0.4, 0.8, 0.5))), 0.0, 1.0);
        vec3 base = mix(uColorLow, uColorHigh, v);
        fragColor = vec4(base * (0.35 + 0.65 * diff), uOpacity);
        return;
      }
    } else {
      float a = clamp(v * uOpacity, 0.0, 1.0);
      vec3 c = mix(uColorLow, uColorHigh, v);
      accumColor += (1.0 - accumAlpha) * a * c;
      accumAlpha += (1.0 - accumAlpha) * a;
      if (accumAlpha > 0.98) break;
    }
  }

  if (uMode == 0) discard;        // isosurface never crossed
  if (accumAlpha <= 0.001) discard;
  fragColor = vec4(accumColor / max(accumAlpha, 1e-3), accumAlpha);
}
`;

export default function VolumeRaymarchLayer(props: VolumeRaymarchLayerProps) {
  const {
    cells,
    getX,
    getY,
    getZ,
    getValue,
    capable,
    visible = false,
    mode = "fog",
    isoLevel = 0.5,
    opacity = 0.6,
    steps = 192,
    colorLow = "#1e3a8a",
    colorHigh = "#dc2626",
    maxTextureDim = 256,
    valueRange,
    isActive,
  } = props;

  const meshRef = useRef<THREE.Mesh>(null);
  const camLocal = useRef(new THREE.Vector3());
  const invMatrix = useRef(new THREE.Matrix4());

  const enabled = visible && capable && cells.length > 0;

  // Build the volume texture only when enabled and inputs change.
  // NOTE: the accessor callbacks are dependencies — callers MUST memoize them
  // (useCallback), otherwise the texture rebuilds every render. Changing the
  // value accessor (e.g. switching visualLayer) correctly rebuilds the volume.
  const grid = useMemo<VolumeGrid | null>(() => {
    if (!enabled) return null;
    const g = buildVolumeTexture(cells, getX, getY, getZ, getValue, {
      valueRange,
      isActive,
    });
    if (!g) return null;
    // Reject lattices the device cannot store as a 3D texture.
    if (Math.max(g.dims[0], g.dims[1], g.dims[2]) > maxTextureDim) {
      g.texture.dispose();
      return null;
    }
    return g;
  }, [enabled, cells, getX, getY, getZ, getValue, valueRange, isActive, maxTextureDim]);

  const material = useMemo(() => {
    if (!grid) return null;
    const half = new THREE.Vector3(
      grid.worldSize[0] / 2,
      grid.worldSize[1] / 2,
      grid.worldSize[2] / 2
    );
    return new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      transparent: true,
      depthWrite: false,
      side: THREE.BackSide,
      uniforms: {
        uVolume: { value: grid.texture },
        uHalfSize: { value: half },
        uCamLocal: { value: new THREE.Vector3() },
        uMode: { value: mode === "isosurface" ? 0 : 1 },
        uIso: { value: isoLevel },
        uOpacity: { value: opacity },
        uSteps: { value: Math.min(512, Math.max(8, Math.round(steps))) },
        uColorLow: { value: new THREE.Color(colorLow) },
        uColorHigh: { value: new THREE.Color(colorHigh) },
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
    });
  }, [grid, mode, isoLevel, opacity, steps, colorLow, colorHigh]);

  // Dispose GPU resources when they change or on unmount (no leaks).
  useEffect(() => {
    return () => {
      grid?.texture.dispose();
      material?.dispose();
    };
  }, [grid, material]);

  // Feed the camera position in geometry-local space every frame.
  useFrame(({ camera }) => {
    const mesh = meshRef.current;
    if (!mesh || !material) return;
    mesh.updateWorldMatrix(true, false);
    invMatrix.current.copy(mesh.matrixWorld).invert();
    camLocal.current.copy(camera.position).applyMatrix4(invMatrix.current);
    (material.uniforms.uCamLocal.value as THREE.Vector3).copy(camLocal.current);
  });

  if (!grid || !material) return null;

  return (
    <mesh
      ref={meshRef}
      position={grid.center}
      material={material}
      renderOrder={2}
    >
      <boxGeometry args={grid.worldSize} />
    </mesh>
  );
}
