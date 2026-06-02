/**
 * Scientific QA Status Gating — pure functions, no React, no side effects.
 *
 * Each function classifies a metric as PASS, WARN, FAIL, or NOT_AVAILABLE.
 * "Pure" means: deterministic, no DOM/store access, safe in workers and SSR.
 * Every function is independently testable with plain Jest/Vitest.
 *
 * How to verify manually (no test runner):
 *   import { classifyDoiPercentile } from './qaStatus';
 *   console.assert(classifyDoiPercentile(0).status === 'FAIL');
 *   console.assert(classifyDoiPercentile(null).status === 'NOT_AVAILABLE');
 *   console.assert(classifyDoiPercentile(0.42).status === 'PASS');
 */

export type QaStatus = 'PASS' | 'WARN' | 'FAIL' | 'NOT_AVAILABLE';

export interface QaResult {
  status: QaStatus;
  reason: string;
}

// ─── DOI (Depth of Investigation — Li & Oldenburg 1999) ───────────────────────

/**
 * Classifies a single DOI percentile value (doi_raw per-voxel summary).
 *
 * DOI = 0 is physically impossible in a valid inversion: it would mean the
 * data kernel has zero sensitivity everywhere, which only occurs if the solver
 * crashed, the grid is degenerate, or the output was never written. Showing
 * "0.000" to the user implies a valid resolved depth, which is incorrect.
 */
export function classifyDoiPercentile(
  value: number | null | undefined
): QaResult {
  if (value === null || value === undefined) {
    return {
      status: 'NOT_AVAILABLE',
      reason: 'DOI no calculado para esta corrida.',
    };
  }
  if (!Number.isFinite(value)) {
    return {
      status: 'FAIL',
      reason: 'DOI no finito — valor inválido en el reporte.',
    };
  }
  if (value <= 0) {
    return {
      status: 'FAIL',
      reason: 'DOI ≤ 0 indica fallo del solver o modelo degenerado.',
    };
  }
  return { status: 'PASS', reason: '' };
}

// ─── Uncertainty (posterior σ per-voxel) ──────────────────────────────────────

/**
 * Classifies whether a set of posterior_std values is valid for display.
 *
 * Requires at least one strictly positive finite value. All-zero or empty
 * arrays indicate compute_uncertainty was disabled or the solver skipped
 * the Hutchinson trace estimator step.
 */
export function classifyUncertaintyValues(sigmaValues: number[]): QaResult {
  if (sigmaValues.length === 0) {
    return {
      status: 'NOT_AVAILABLE',
      reason:
        'Sin celdas con datos de incertidumbre (posterior_std ausente en el modelo).',
    };
  }
  const hasValid = sigmaValues.some(v => Number.isFinite(v) && v > 0);
  if (!hasValid) {
    return {
      status: 'NOT_AVAILABLE',
      reason:
        'Todos los valores σ son 0 o inválidos — incertidumbre no calculada en esta corrida.',
    };
  }
  return { status: 'PASS', reason: '' };
}

// ─── L-curve (lambda sweep) ───────────────────────────────────────────────────

/**
 * Classifies whether an L-curve sweep shows informative curvature.
 *
 * A flat curve (relative range < 5% of mean) means the data cannot
 * distinguish between regularization levels, so the optimal λ selected
 * is heuristic and non-conclusive. A valid L-curve should show a clear
 * elbow between the data-fit and regularization branches.
 */
export function classifyLCurvePoints(
  points: Array<{ lambda_mag: number; y: number }>
): QaResult {
  if (points.length < 3) {
    return {
      status: 'NOT_AVAILABLE',
      reason: 'Insuficientes puntos para evaluar curvatura de la L-curve.',
    };
  }
  const ys = points.map(p => p.y);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const yMean = ys.reduce((a, b) => a + b, 0) / ys.length;
  if (yMean > 0 && (yMax - yMin) / yMean < 0.05) {
    return {
      status: 'WARN',
      reason:
        'L-curve plana (variación NRMSE < 5% sobre la media) — λ óptima es heurística, resultado no concluyente.',
    };
  }
  return { status: 'PASS', reason: '' };
}

// ─── ViewMode availability ────────────────────────────────────────────────────

/**
 * Classifies whether the model cells contain physical fields required for a viewMode.
 *
 * density is always available (it is the primary gravity inversion output).
 * susceptibility requires at least one non-zero susceptibility_si value.
 * joint requires at least one finite joint_structural_score value.
 *
 * IMPORTANT: terraQuantumGeology.ts defaults joint_structural_score to 1.0
 * when the field is absent, which makes ALL voxels appear in joint mode even
 * for gravity-only runs. This function detects that case so the UI can block
 * or warn before switching modes.
 */
export function classifyViewModeAvailability(
  viewMode: 'density' | 'susceptibility' | 'joint',
  cells: Array<Record<string, unknown>>
): QaResult {
  if (viewMode === 'density') {
    return { status: 'PASS', reason: '' };
  }

  if (viewMode === 'susceptibility') {
    const hasData = cells.some(c => {
      const v = Number(c.susceptibility_si);
      return Number.isFinite(v) && v !== 0;
    });
    if (!hasData) {
      return {
        status: 'FAIL',
        reason:
          'No existen datos susceptibility_si para esta corrida (inversión solo gravimétrica).',
      };
    }
  }

  if (viewMode === 'joint') {
    const hasData = cells.some(c => {
      const raw = c.joint_structural_score;
      return raw !== undefined && raw !== null && Number.isFinite(Number(raw));
    });
    if (!hasData) {
      return {
        status: 'FAIL',
        reason:
          'No existen datos joint_structural_score para esta corrida.',
      };
    }
  }

  return { status: 'PASS', reason: '' };
}

// ─── UI helpers ───────────────────────────────────────────────────────────────

/**
 * Returns the display value for a metric guarded by a QA result.
 * When the QA status is not PASS, returns null so callers can render "—".
 */
export function qaGatedValue(
  value: number | null | undefined,
  qa: QaResult
): number | null {
  if (qa.status !== 'PASS') return null;
  return value ?? null;
}
