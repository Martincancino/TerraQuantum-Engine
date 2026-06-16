/**
 * Unified color pipeline for voxel visualization.
 * Consolidates spectral/turbo/inferno colormaps, DOI attenuation, and visibility gating.
 * Self-contained: no imports from terraQuantumGeology to avoid circular deps.
 */

type ColorStop = [number, [number, number, number]];

const SPECTRAL_STOPS: ColorStop[] = [
  [0.00, [0.000, 0.000, 0.549]],
  [0.10, [0.000, 0.102, 1.000]],
  [0.22, [0.000, 0.700, 1.000]],
  [0.35, [0.000, 1.000, 0.800]],
  [0.45, [0.102, 1.000, 0.200]],
  [0.55, [0.700, 1.000, 0.000]],
  [0.63, [1.000, 1.000, 0.000]],
  [0.73, [1.000, 0.600, 0.000]],
  [0.83, [1.000, 0.100, 0.000]],
  [0.92, [1.000, 0.000, 0.700]],
  [1.00, [1.000, 0.500, 0.900]],
];

const TURBO_STOPS: ColorStop[] = [
  [0.000, [0.188, 0.071, 0.231]],
  [0.143, [0.153, 0.392, 0.945]],
  [0.286, [0.090, 0.745, 0.812]],
  [0.429, [0.188, 0.933, 0.353]],
  [0.571, [0.686, 0.980, 0.082]],
  [0.714, [0.996, 0.776, 0.082]],
  [0.857, [0.957, 0.365, 0.004]],
  [1.000, [0.478, 0.027, 0.000]],
];

const INFERNO_STOPS: ColorStop[] = [
  [0.000, [0.000, 0.000, 0.016]],
  [0.143, [0.122, 0.047, 0.165]],
  [0.286, [0.369, 0.082, 0.325]],
  [0.429, [0.580, 0.071, 0.298]],
  [0.571, [0.780, 0.239, 0.224]],
  [0.714, [0.937, 0.494, 0.122]],
  [0.857, [0.988, 0.749, 0.353]],
  [1.000, [0.988, 1.000, 0.643]],
];

function sampleColormap(stops: ColorStop[], t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const t0 = stops[i - 1][0], t1 = stops[i][0];
      const local = (t - t0) / Math.max(t1 - t0, 1e-9);
      const a = stops[i - 1][1], b = stops[i][1];
      return [
        a[0] + (b[0] - a[0]) * local,
        a[1] + (b[1] - a[1]) * local,
        a[2] + (b[2] - a[2]) * local,
      ];
    }
  }
  return stops[stops.length - 1][1];
}

export interface ColorPipelineConfig {
  /** DOI threshold (0.0–1.0): voxels below threshold get attenuated alpha. */
  doiThreshold: number;
  /** Colormap for the active physical layer. */
  colormapMode: 'spectral' | 'turbo' | 'inferno';
  /** When true, voxels below doiThreshold are fully hidden (alpha=0) instead of attenuated. */
  gateByDoi: boolean;
  /** Applies a 30% desaturation toward gray. */
  professionalMode: boolean;
}

export interface VoxelColorResult {
  /** RGB in [0, 1] range. */
  r: number;
  g: number;
  b: number;
  /** Alpha in [0, 1]. 1.0 = fully opaque, 0.0 = invisible. */
  a: number;
}

export interface VoxelColorInput {
  normalizedValue: number;
  doi_index?: number;
}

export class ColorPipeline {
  private config: ColorPipelineConfig;

  constructor(config: ColorPipelineConfig) {
    this.config = config;
  }

  computeVoxelColor(voxel: VoxelColorInput): VoxelColorResult {
    const stops =
      this.config.colormapMode === 'turbo' ? TURBO_STOPS :
      this.config.colormapMode === 'inferno' ? INFERNO_STOPS :
      SPECTRAL_STOPS;

    let [r, g, b] = sampleColormap(stops, Math.max(0, Math.min(1, voxel.normalizedValue)));

    if (this.config.professionalMode) {
      const gray = 0.299 * r + 0.587 * g + 0.114 * b;
      const blend = 0.3;
      r = r * (1 - blend) + gray * blend;
      g = g * (1 - blend) + gray * blend;
      b = b * (1 - blend) + gray * blend;
    }

    const doiIndex = voxel.doi_index ?? 1.0;
    let a: number;
    if (this.config.gateByDoi) {
      a = doiIndex > this.config.doiThreshold ? 1.0 : 0.0;
    } else {
      a = doiIndex < this.config.doiThreshold
        ? Math.max(0.2, doiIndex / Math.max(this.config.doiThreshold, 1e-6))
        : 1.0;
    }

    return { r, g, b, a };
  }

  updateConfig(partial: Partial<ColorPipelineConfig>): void {
    this.config = { ...this.config, ...partial };
  }

  getConfig(): ColorPipelineConfig {
    return { ...this.config };
  }

  /** Derive the correct colormap from a viewMode string. */
  static colormapForMode(viewMode: string): ColorPipelineConfig['colormapMode'] {
    if (viewMode === 'susceptibility') return 'turbo';
    if (viewMode === 'uncertainty') return 'inferno';
    return 'spectral';
  }
}
