/**
 * GPU capability probe — Fase 6 (Render God-Tier) groundwork.
 *
 * Pure feature-detection: no React, no Zustand, no Three.js import, SSR-safe.
 * Answers ONE question honestly: "what can the user's browser/GPU actually do
 * for the render upgrades in [[godtier_roadmap_fases_0_8]] Fase 6?" — so every
 * later slice (volumetric raymarch, meshlet LOD, RTAO stand-ins) can gate itself
 * on real capability instead of assuming, and degrade to the current WebGL2
 * instanced-mesh renderer when the feature is missing.
 *
 * Decision rationale lives in docs/ADR-fase6-render.md. This module is the
 * machine-readable half of that ADR.
 *
 * It does NOT create a renderer, mutate the scene, or touch Scene3D. It opens a
 * throwaway <canvas> for the WebGL2 probe and (optionally) requests a WebGPU
 * adapter, then discards both.
 *
 * How to verify manually (browser console, no test runner):
 *   import { probeGpuCapabilities, summarizeGpuReport } from '@/lib/render/gpuCapabilities';
 *   probeGpuCapabilities().then(r => console.log(summarizeGpuReport(r)));
 */

// ─── Recommended backend ─────────────────────────────────────────────────────

/**
 * `webgpu`  — WebGPU adapter present and usable (compute, storage buffers,
 *             3D textures). Preferred target for the heavy Fase 6 paths.
 * `webgl2`  — No usable WebGPU, but WebGL2 is available (today's renderer).
 * `none`    — Neither: fall back to the non-3D UI; do not attempt 3D rendering.
 */
export type RenderBackend = 'webgpu' | 'webgl2' | 'none';

// ─── WebGL2 capabilities ──────────────────────────────────────────────────────

export interface Webgl2Capabilities {
  /** A WebGL2 context could be created at all. */
  available: boolean;
  /** GL_MAX_TEXTURE_SIZE — caps 2D texture atlases. */
  maxTextureSize: number;
  /** GL_MAX_3D_TEXTURE_SIZE — caps the volume texture for raymarching. */
  max3dTextureSize: number;
  /**
   * EXT_color_buffer_float present — required to render to float targets
   * (front-to-back σ accumulation / HDR raymarch). Without it, the σ-fog pass
   * must quantise to 8-bit and will band.
   */
  floatColorBuffer: boolean;
  /**
   * OES_texture_float_linear present — required for smooth trilinear sampling
   * of a float 3D texture. Without it the volume must use NEAREST and looks
   * blocky (or the data must be pre-normalised to UNORM8).
   */
  floatLinearFilter: boolean;
  /** GL_MAX_SAMPLES — MSAA ceiling for the existing instanced-mesh pass. */
  maxSamples: number;
  /** Unmasked renderer string when WEBGL_debug_renderer_info is allowed. */
  renderer: string | null;
}

// ─── WebGPU capabilities ──────────────────────────────────────────────────────

export interface WebgpuLimits {
  maxTextureDimension3D: number;
  maxBufferSize: number;
  maxStorageBufferBindingSize: number;
  maxComputeWorkgroupStorageSize: number;
  maxComputeInvocationsPerWorkgroup: number;
}

export interface WebgpuCapabilities {
  /** `navigator.gpu` exists (API surface present). */
  apiPresent: boolean;
  /** An adapter was actually granted (hardware/driver usable). */
  adapterOk: boolean;
  /** WGSL feature flags advertised by the adapter (e.g. "float32-filterable"). */
  features: string[];
  /** Subset of adapter limits relevant to Fase 6, or null if no adapter. */
  limits: WebgpuLimits | null;
  /** Human-readable reason, in Spanish, for the adapterOk verdict. */
  reason: string;
}

// ─── Full report ──────────────────────────────────────────────────────────────

export interface GpuCapabilityReport {
  /** Recommended backend given everything below. */
  backend: RenderBackend;
  webgpu: WebgpuCapabilities;
  webgl2: Webgl2Capabilities;
  /**
   * Derived Fase 6 feature gates. A later render slice should read THESE, not
   * the raw fields, so the gating logic lives in one place.
   */
  gates: {
    /** Volumetric σ/density raymarch (needs a usable 3D texture + linear filter). */
    volumeRaymarch: boolean;
    /** GPU-side culling for 1M+ drillhole segments (needs WebGPU compute). */
    computeCulling: boolean;
    /** Float render targets for HDR/σ accumulation. */
    floatRenderTargets: boolean;
  };
  /** One-line, human-readable, Spanish summary for logs / the about panel. */
  recommendation: string;
}

// ─── Minimal structural WebGPU typings ────────────────────────────────────────
// We avoid a hard dependency on @webgpu/types (no new deps per project rules) by
// declaring only the structural surface we touch. These are intentionally loose.

interface MinimalGpuAdapter {
  readonly features: { has(name: string): boolean } & Iterable<string>;
  readonly limits: Record<string, number>;
}

interface MinimalGpu {
  requestAdapter(options?: {
    powerPreference?: 'low-power' | 'high-performance';
  }): Promise<MinimalGpuAdapter | null>;
}

function getNavigatorGpu(): MinimalGpu | null {
  if (typeof navigator === 'undefined') return null;
  const gpu = (navigator as unknown as { gpu?: MinimalGpu }).gpu;
  return gpu ?? null;
}

// ─── WebGL2 probe ─────────────────────────────────────────────────────────────

const EMPTY_WEBGL2: Webgl2Capabilities = {
  available: false,
  maxTextureSize: 0,
  max3dTextureSize: 0,
  floatColorBuffer: false,
  floatLinearFilter: false,
  maxSamples: 0,
  renderer: null,
};

/**
 * Synchronously probes WebGL2 by opening a throwaway canvas. SSR-safe: returns
 * an all-false report when `document` is unavailable. Never throws.
 */
export function detectWebgl2Capabilities(): Webgl2Capabilities {
  if (typeof document === 'undefined') return EMPTY_WEBGL2;

  let gl: WebGL2RenderingContext | null = null;
  try {
    const canvas = document.createElement('canvas');
    gl = canvas.getContext('webgl2', { failIfMajorPerformanceCaveat: false });
  } catch {
    gl = null;
  }
  if (!gl) return EMPTY_WEBGL2;

  const num = (pname: GLenum): number => {
    const v = gl!.getParameter(pname);
    return typeof v === 'number' && Number.isFinite(v) ? v : 0;
  };

  let renderer: string | null = null;
  try {
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    if (dbg) {
      const value = gl.getParameter(
        (dbg as { UNMASKED_RENDERER_WEBGL: GLenum }).UNMASKED_RENDERER_WEBGL
      );
      renderer = typeof value === 'string' ? value : null;
    }
  } catch {
    renderer = null;
  }

  const result: Webgl2Capabilities = {
    available: true,
    maxTextureSize: num(gl.MAX_TEXTURE_SIZE),
    max3dTextureSize: num(gl.MAX_3D_TEXTURE_SIZE),
    floatColorBuffer: gl.getExtension('EXT_color_buffer_float') !== null,
    floatLinearFilter: gl.getExtension('OES_texture_float_linear') !== null,
    maxSamples: num(gl.MAX_SAMPLES),
    renderer,
  };

  // Release the throwaway context promptly instead of waiting for GC.
  try {
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    /* best effort */
  }

  return result;
}

// ─── WebGPU probe ─────────────────────────────────────────────────────────────

const FASE6_WEBGPU_LIMIT_KEYS: ReadonlyArray<keyof WebgpuLimits> = [
  'maxTextureDimension3D',
  'maxBufferSize',
  'maxStorageBufferBindingSize',
  'maxComputeWorkgroupStorageSize',
  'maxComputeInvocationsPerWorkgroup',
];

/** Synchronous, cheap check: is the WebGPU API surface even present? */
export function detectWebgpuApiPresent(): boolean {
  return getNavigatorGpu() !== null;
}

/**
 * Requests a WebGPU adapter and extracts the Fase 6-relevant limits/features.
 * Async because adapter acquisition is async and may be denied even when
 * `navigator.gpu` exists (driver blocklist, headless, software fallback off).
 * Never throws; reports the failure in `reason`.
 */
export async function probeWebgpuAdapter(): Promise<WebgpuCapabilities> {
  const gpu = getNavigatorGpu();
  if (!gpu) {
    return {
      apiPresent: false,
      adapterOk: false,
      features: [],
      limits: null,
      reason: 'navigator.gpu ausente — el navegador no expone WebGPU.',
    };
  }

  let adapter: MinimalGpuAdapter | null = null;
  try {
    adapter = await gpu.requestAdapter({ powerPreference: 'high-performance' });
  } catch (err) {
    return {
      apiPresent: true,
      adapterOk: false,
      features: [],
      limits: null,
      reason: `requestAdapter lanzó excepción: ${
        err instanceof Error ? err.message : String(err)
      }.`,
    };
  }

  if (!adapter) {
    return {
      apiPresent: true,
      adapterOk: false,
      features: [],
      limits: null,
      reason:
        'WebGPU presente pero sin adaptador disponible (driver en lista de bloqueo o sin GPU usable).',
    };
  }

  const features: string[] = [];
  try {
    for (const f of adapter.features) features.push(f);
  } catch {
    /* features iteration is best-effort */
  }

  const rawLimits = adapter.limits ?? {};
  const limits = {} as WebgpuLimits;
  for (const key of FASE6_WEBGPU_LIMIT_KEYS) {
    const v = rawLimits[key];
    limits[key] = typeof v === 'number' && Number.isFinite(v) ? v : 0;
  }

  return {
    apiPresent: true,
    adapterOk: true,
    features,
    limits,
    reason: 'Adaptador WebGPU obtenido correctamente.',
  };
}

// ─── Combined report ──────────────────────────────────────────────────────────

function chooseBackend(
  webgpu: WebgpuCapabilities,
  webgl2: Webgl2Capabilities
): RenderBackend {
  if (webgpu.adapterOk) return 'webgpu';
  if (webgl2.available) return 'webgl2';
  return 'none';
}

function buildRecommendation(
  backend: RenderBackend,
  gates: GpuCapabilityReport['gates'],
  webgl2: Webgl2Capabilities
): string {
  if (backend === 'none') {
    return 'Sin WebGPU ni WebGL2: deshabilitar la vista 3D y mostrar solo tablas/2D.';
  }
  if (backend === 'webgpu') {
    return 'WebGPU disponible: habilitar rutas God-Tier (raymarch volumétrico, culling por compute). Mantener WebGL2 como respaldo.';
  }
  // webgl2
  if (gates.volumeRaymarch) {
    return `WebGL2 (sin WebGPU): raymarch volumétrico viable vía Data3DTexture (max3D=${webgl2.max3dTextureSize}). Culling por compute NO disponible — usar LOD instanciado en CPU.`;
  }
  return 'WebGL2 sin texturas 3D filtrables: mantener el renderer instanciado actual; raymarch volumétrico no recomendado (se vería bloqueado).';
}

/**
 * Full async probe: WebGL2 (sync) + WebGPU adapter (async), folded into a single
 * report with derived Fase 6 gates and a Spanish recommendation. Never throws.
 */
export async function probeGpuCapabilities(): Promise<GpuCapabilityReport> {
  const webgl2 = detectWebgl2Capabilities();
  const webgpu = await probeWebgpuAdapter();
  const backend = chooseBackend(webgpu, webgl2);

  const gates: GpuCapabilityReport['gates'] = {
    // A usable 3D texture needs both the dimension AND linear filtering of the
    // sampled format. On WebGPU we assume 3D + float32-filterable; on WebGL2 we
    // require the explicit extensions.
    volumeRaymarch:
      backend === 'webgpu'
        ? (webgpu.limits?.maxTextureDimension3D ?? 0) >= 256
        : webgl2.available &&
          webgl2.max3dTextureSize >= 256 &&
          webgl2.floatLinearFilter,
    computeCulling: backend === 'webgpu',
    floatRenderTargets:
      backend === 'webgpu' ? true : webgl2.floatColorBuffer,
  };

  return {
    backend,
    webgpu,
    webgl2,
    gates,
    recommendation: buildRecommendation(backend, gates, webgl2),
  };
}

/** Compact multi-line string for logging or an "About / GPU" panel. */
export function summarizeGpuReport(report: GpuCapabilityReport): string {
  const lines = [
    `backend recomendado: ${report.backend}`,
    `WebGPU: ${report.webgpu.adapterOk ? 'OK' : 'no'} (${report.webgpu.reason})`,
    `WebGL2: ${report.webgl2.available ? 'OK' : 'no'} · max3D=${report.webgl2.max3dTextureSize} · floatLinear=${report.webgl2.floatLinearFilter} · floatRT=${report.webgl2.floatColorBuffer}`,
    `gates: raymarch=${report.gates.volumeRaymarch} · computeCulling=${report.gates.computeCulling} · floatRT=${report.gates.floatRenderTargets}`,
    `→ ${report.recommendation}`,
  ];
  return lines.join('\n');
}
