/**
 * WebGPU compute culling — Fase 6 (Render God-Tier) slice 4.
 *
 * Real WGSL compute pass that frustum-culls segment bounding spheres on the GPU
 * and returns a per-segment visibility mask. This is the GPU version of the CPU
 * `selectVisibleSegments` in segmentLOD.ts (slice 3) — the A/B pair the roadmap
 * asked for.
 *
 * Key design point (why this is NOT blocked on Three's experimental WebGPURenderer):
 * culling is a *computation*, not rendering. We create a STANDALONE WebGPU device
 * via `navigator.gpu` and run compute on it; the result (a mask) feeds the
 * existing WebGL2 InstancedMesh renderer. No renderer swap, no GLSL→WGSL port of
 * the scene. WebGPU-compute + WebGL2-render is a legitimate hybrid.
 *
 * Honesty caveats:
 *  - The HOST (TypeScript) code is type-checked (@webgpu/types) and bundles, but
 *    the WGSL and the GPU execution are compiled/run by the browser at runtime —
 *    NOT verified here (no WebGPU device in this environment). Treat as "implemented
 *    + builds", pending real-GPU QA.
 *  - GPU readback (mapAsync) is async, so a render loop applying the mask is
 *    inherently ~1 frame latent. That's expected for GPU culling; integrate with
 *    double-buffering, not by awaiting mid-frame.
 *  - Hardware ray tracing (RTAO) is a DIFFERENT, harder wall: WebGPU ships no
 *    `ray_query` in any stable browser today, so it stays deferred. The
 *    screen-space AO (slice 5) is the substitute. This module does NOT do RT.
 */

const CULL_SHADER = /* wgsl */ `
@group(0) @binding(0) var<storage, read>       spheres : array<vec4<f32>>; // xyz=center, w=radius
@group(0) @binding(1) var<uniform>             planes  : array<vec4<f32>, 6>; // frustum: xyz=normal, w=constant
@group(0) @binding(2) var<storage, read_write> mask    : array<u32>;          // 1=visible, 0=culled

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid : vec3<u32>) {
  let i = gid.x;
  if (i >= arrayLength(&spheres)) { return; }
  let s = spheres[i];
  var visible : u32 = 1u;
  for (var p : u32 = 0u; p < 6u; p = p + 1u) {
    let pl = planes[p];
    // Signed distance from sphere center to plane; if it is farther than the
    // radius on the negative side, the sphere is fully outside this plane.
    if (dot(pl.xyz, s.xyz) + pl.w < -s.w) { visible = 0u; break; }
  }
  mask[i] = visible;
}
`;

export interface WebGpuCuller {
  /** Capacity (max segments) this culler was allocated for. */
  readonly capacity: number;
  /**
   * Uploads segment bounding spheres (Float32Array, 4 floats per segment:
   * center.x, center.y, center.z, radius). Length/4 must be ≤ capacity.
   */
  upload(spheres: Float32Array): void;
  /**
   * Runs the compute cull for the given 6 frustum planes (Float32Array of 24:
   * 6 × [nx, ny, nz, constant]). Resolves to a Uint32Array mask (1=visible) of
   * length = uploaded segment count.
   */
  cull(frustumPlanes: Float32Array): Promise<Uint32Array>;
  /** Releases all GPU resources. */
  dispose(): void;
}

/**
 * Creates a standalone WebGPU culler, or returns null when WebGPU is unavailable
 * (no adapter/device). Never throws on absence — the caller falls back to the
 * CPU path (slice 3). `capacity` fixes the buffer sizes (allocated once).
 */
export async function createWebGpuCuller(
  capacity: number
): Promise<WebGpuCuller | null> {
  if (typeof navigator === "undefined") return null;
  const gpu = (navigator as unknown as { gpu?: GPU }).gpu;
  if (!gpu) return null;

  let device: GPUDevice;
  try {
    const adapter = await gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) return null;
    device = await adapter.requestDevice();
  } catch {
    return null;
  }

  const cap = Math.max(1, Math.floor(capacity));
  const sphereBytes = cap * 4 * 4; // vec4<f32>
  const maskBytes = cap * 4;       // u32

  const sphereBuffer = device.createBuffer({
    size: sphereBytes,
    usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
  });
  const planesBuffer = device.createBuffer({
    size: 6 * 4 * 4, // array<vec4<f32>, 6>
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  const maskBuffer = device.createBuffer({
    size: maskBytes,
    usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
  });
  const readbackBuffer = device.createBuffer({
    size: maskBytes,
    usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
  });

  const shaderModule = device.createShaderModule({ code: CULL_SHADER });
  const pipeline = device.createComputePipeline({
    layout: "auto",
    compute: { module: shaderModule, entryPoint: "main" },
  });
  const bindGroup = device.createBindGroup({
    layout: pipeline.getBindGroupLayout(0),
    entries: [
      { binding: 0, resource: { buffer: sphereBuffer } },
      { binding: 1, resource: { buffer: planesBuffer } },
      { binding: 2, resource: { buffer: maskBuffer } },
    ],
  });

  let count = 0;

  return {
    capacity: cap,

    upload(spheres: Float32Array) {
      count = Math.min(cap, Math.floor(spheres.length / 4));
      // Cast: TS 5.7 types arrays as Float32Array<ArrayBufferLike>, while
      // @webgpu/types wants BufferSource. Runtime sees a typed array, so the
      // dataOffset/size args stay in ELEMENTS as intended.
      device.queue.writeBuffer(sphereBuffer, 0, spheres as BufferSource, 0, count * 4);
    },

    async cull(frustumPlanes: Float32Array): Promise<Uint32Array> {
      if (count === 0) return new Uint32Array(0);
      device.queue.writeBuffer(planesBuffer, 0, frustumPlanes as BufferSource, 0, 24);

      const encoder = device.createCommandEncoder();
      const pass = encoder.beginComputePass();
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, bindGroup);
      pass.dispatchWorkgroups(Math.ceil(count / 64));
      pass.end();
      encoder.copyBufferToBuffer(maskBuffer, 0, readbackBuffer, 0, count * 4);
      device.queue.submit([encoder.finish()]);

      await readbackBuffer.mapAsync(GPUMapMode.READ, 0, count * 4);
      // Copy out before unmapping (the mapped range is invalidated on unmap).
      const view = new Uint32Array(readbackBuffer.getMappedRange(0, count * 4));
      const out = view.slice(0, count);
      readbackBuffer.unmap();
      return out;
    },

    dispose() {
      sphereBuffer.destroy();
      planesBuffer.destroy();
      maskBuffer.destroy();
      readbackBuffer.destroy();
      device.destroy();
    },
  };
}
