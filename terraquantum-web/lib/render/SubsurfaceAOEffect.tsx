"use client";

/**
 * Subsurface ambient occlusion — Fase 6 (Render God-Tier) slice 5.
 *
 * Screen-space AO (N8AO, via the already-installed @react-three/postprocessing)
 * as the HONEST stand-in for the roadmap's "RTAO hardware ray tracing oclusión
 * subsuelo". WebGL2 cannot do hardware ray tracing; true RTAO is DEFERRED until
 * WebGPU exposes stable ray queries (see docs/ADR-fase6-render.md). Screen-space
 * AO still adds the contact-shadow depth cue between voxels/bodies that makes the
 * subsurface readable.
 *
 * Opt-in and self-contained: returns null unless `enabled`, so mounting it
 * cannot regress the default render path. Mount once, at the scene root (a
 * sibling of the scene content under <Canvas>), NOT inside a transformed group.
 *
 * Scale independence: TerraQuantum scenes span anywhere from tens to thousands
 * of world units, so a fixed WORLD-space AO radius would over/under-occlude per
 * model. We use N8AO's `screenSpaceRadius`, which interprets `aoRadius` in
 * PIXELS — making the effect scale-invariant and removing the per-scene tuning
 * the previous world-radius version required.
 *
 * Caveat (residual, needs visual QA): the Canvas uses `logarithmicDepthBuffer`;
 * any screen-space AO reconstructs position from the depth buffer, so log-depth
 * can still introduce minor inaccuracy at grazing angles. The effect is opt-in
 * and default OFF, so it can never regress the base render. tsc/eslint validated.
 */

import { EffectComposer, N8AO } from "@react-three/postprocessing";

export interface SubsurfaceAOEffectProps {
  enabled?: boolean;
  /**
   * AO radius in PIXELS (screen-space) — scale-invariant across scene sizes.
   * Default 24.
   */
  aoRadius?: number;
  /** How fast occlusion fades with depth distance. Default 1. */
  distanceFalloff?: number;
  /** Darkening strength. Default 2. */
  intensity?: number;
  /** Quality/perf tradeoff. Default "medium". */
  quality?: "performance" | "low" | "medium" | "high" | "ultra";
  /** Half-resolution AO pass for performance. Default true. */
  halfRes?: boolean;
}

export default function SubsurfaceAOEffect(props: SubsurfaceAOEffectProps) {
  const {
    enabled = false,
    aoRadius = 24,
    distanceFalloff = 1,
    intensity = 2,
    quality = "medium",
    halfRes = true,
  } = props;

  if (!enabled) return null;

  return (
    <EffectComposer enableNormalPass={false}>
      <N8AO
        // Pixel-space radius → independent of world scale (tens..thousands of units).
        screenSpaceRadius
        aoRadius={aoRadius}
        distanceFalloff={distanceFalloff}
        intensity={intensity}
        quality={quality}
        halfRes={halfRes}
      />
    </EffectComposer>
  );
}
