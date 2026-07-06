"""F2B — Sondajes: DESURVEY por curvatura mínima + QA/QC + compositación.

Hoy TQ asume sondajes VERTICALES (borehole_service): un pozo inclinado se
posiciona MAL en silencio. Aquí:

  1. DESURVEY por curvatura mínima (el estándar de la industria, SRK/AusIMM):
     collar + estaciones de survey (MD, azimut, dip) → traza 3D verdadera.
  2. QA/QC automático de intervalos: cada hallazgo con fila y severidad
     (bloqueante/advertencia) — FROM≥TO, solapes, huecos, duplicados,
     densidades fuera de rango físico, profundidades negativas.
  3. COMPOSITACIÓN a intervalos regulares (elección del usuario, documentada):
     densidad ponderada por largo; litología = moda por largo; composites con
     cobertura <50% se descartan CON aviso.

Convenciones (documentadas, jamás implícitas):
  - Ejes del backend: x=este, z=norte (planta); y=profundidad POSITIVA hacia
    abajo (la convención interna de TQ).
  - Azimut en grados desde el NORTE hacia el ESTE.
  - DIP en grados BAJO la horizontal, positivo hacia abajo (90 = vertical).
    Up-holes (dip<0, minería subterránea) se aceptan con advertencia.
  - MD = profundidad medida a lo largo del pozo desde el collar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.logging import get_logger

_log = get_logger(__name__)

SEV_BLOCKING = "bloqueante"
SEV_WARNING = "advertencia"

# Rango físico de densidades de roca (t/m³) para QA/QC (Telford et al.).
DENSITY_PHYSICAL_MIN = 1.0
DENSITY_PHYSICAL_MAX = 6.0

_GAP_OVERLAP_TOL_M = 0.01


class DesurveyInputError(ValueError):
    """Input de desurvey inválido (mensaje ES accionable)."""


# ─────────────────────────────────────────────────────────────────────────────
# 1. Desurvey por curvatura mínima
# ─────────────────────────────────────────────────────────────────────────────
def _direction_unit(azimuth_deg: float, dip_deg: float) -> np.ndarray:
    """(este, norte, abajo) unitario desde azimut (N→E) y dip (bajo horizontal)."""
    az = np.radians(azimuth_deg)
    dip = np.radians(dip_deg)
    h = np.cos(dip)
    return np.array([h * np.sin(az), h * np.cos(az), np.sin(dip)])


@dataclass
class DesurveyedTrace:
    hole_id: str
    md: np.ndarray            # (n,) profundidad medida en cada estación
    east: np.ndarray          # (n,) desplazamiento este desde el collar [m]
    north: np.ndarray         # (n,) desplazamiento norte desde el collar [m]
    depth: np.ndarray         # (n,) profundidad VERTICAL bajo el collar [m]
    warnings: List[str] = field(default_factory=list)

    def position_at(self, md_query: "float | np.ndarray") -> np.ndarray:
        """(este, norte, profundidad) interpolados a lo largo de la traza."""
        mdq = np.atleast_1d(np.asarray(md_query, dtype=float))
        e = np.interp(mdq, self.md, self.east)
        n = np.interp(mdq, self.md, self.north)
        d = np.interp(mdq, self.md, self.depth)
        return np.column_stack([e, n, d])


def desurvey_minimum_curvature(
    hole_id: str,
    survey_md: Sequence[float],
    survey_azimuth_deg: Sequence[float],
    survey_dip_deg: Sequence[float],
    total_depth_m: Optional[float] = None,
) -> DesurveyedTrace:
    """Traza 3D verdadera por CURVATURA MÍNIMA (factor de razón RF estándar).

    Entre estaciones consecutivas: Δr = (ΔMD/2)·RF·(v₁+v₂), con
    RF = (2/β)·tan(β/2) y β el ángulo dogleg (RF→1 si β→0). Si la primera
    estación no está en MD=0 se asume el mismo rumbo desde el collar (aviso).
    """
    md = np.asarray(survey_md, dtype=float)
    az = np.asarray(survey_azimuth_deg, dtype=float)
    dip = np.asarray(survey_dip_deg, dtype=float)
    if not (len(md) == len(az) == len(dip)):
        raise DesurveyInputError(
            f"Survey de '{hole_id}': md/azimut/dip deben tener el mismo largo."
        )
    if len(md) < 1:
        raise DesurveyInputError(
            f"Survey de '{hole_id}': se necesita al menos 1 estación (MD, azimut, dip)."
        )
    if np.any(np.diff(md) <= 0):
        raise DesurveyInputError(
            f"Survey de '{hole_id}': las MD deben ser estrictamente crecientes "
            "(ordene las estaciones por profundidad medida)."
        )
    if np.any(md < 0):
        raise DesurveyInputError(f"Survey de '{hole_id}': MD negativa.")
    if np.any(np.abs(dip) > 90.0):
        raise DesurveyInputError(
            f"Survey de '{hole_id}': dip fuera de [-90, 90] grados (convención: "
            "grados bajo la horizontal, 90 = vertical hacia abajo)."
        )

    warnings: List[str] = []
    if np.any(dip < 0):
        warnings.append(
            f"'{hole_id}': dip negativo (up-hole de minería subterránea): la "
            "traza sube; verifique que la convención sea la esperada."
        )

    # Estación implícita en el collar (MD=0) con el rumbo de la primera.
    if md[0] > 0:
        warnings.append(
            f"'{hole_id}': la primera estación está en MD={md[0]:.1f} m; se "
            "asumió rumbo constante desde el collar (MD=0)."
        )
        md = np.concatenate([[0.0], md])
        az = np.concatenate([[az[0]], az])
        dip = np.concatenate([[dip[0]], dip])

    # Extender hasta el fondo del pozo si el survey se queda corto.
    if total_depth_m is not None and total_depth_m > md[-1] + 1e-9:
        warnings.append(
            f"'{hole_id}': el survey llega a MD={md[-1]:.1f} m pero el pozo a "
            f"{total_depth_m:.1f} m; se extendió con el rumbo de la última estación."
        )
        md = np.concatenate([md, [float(total_depth_m)]])
        az = np.concatenate([az, [az[-1]]])
        dip = np.concatenate([dip, [dip[-1]]])

    vecs = np.array([_direction_unit(a, d) for a, d in zip(az, dip)])
    pos = np.zeros((len(md), 3))
    for i in range(1, len(md)):
        v1, v2 = vecs[i - 1], vecs[i]
        cosb = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
        beta = float(np.arccos(cosb))
        rf = 1.0 if beta < 1e-9 else (2.0 / beta) * np.tan(beta / 2.0)
        dmd = md[i] - md[i - 1]
        pos[i] = pos[i - 1] + (dmd / 2.0) * rf * (v1 + v2)

    return DesurveyedTrace(
        hole_id=hole_id, md=md,
        east=pos[:, 0], north=pos[:, 1], depth=pos[:, 2],
        warnings=warnings,
    )


def position_intervals_on_trace(
    trace: DesurveyedTrace,
    collar_x_m: float,
    collar_z_m: float,
    intervals: "List[dict]",
) -> "List[dict]":
    """Posiciona intervalos (from/to en MD) sobre la traza desurveyada.

    Devuelve intervalos en el CONTRATO del ancla de TQ: (x_m, z_m) del punto
    medio del intervalo + y_from/y_to = profundidades VERTICALES verdaderas.
    (El ancla del motor es por columna; para pozos muy desviados el largo del
    intervalo en MD ≠ espesor vertical — se reporta el factor por intervalo.)
    """
    out: List[dict] = []
    for iv in intervals:
        f, t = float(iv["depth_from"]), float(iv["depth_to"])
        p_f, p_mid, p_t = trace.position_at([f, (f + t) / 2.0, t])
        vertical_thickness = float(p_t[2] - p_f[2])
        md_length = t - f
        out.append({
            **iv,
            "x_m": collar_x_m + float(p_mid[0]),
            "z_m": collar_z_m + float(p_mid[1]),
            "y_from_m": float(p_f[2]),
            "y_to_m": float(p_t[2]),
            "vertical_over_md_ratio": (
                vertical_thickness / md_length if md_length > 0 else 1.0
            ),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. QA/QC automático de intervalos
# ─────────────────────────────────────────────────────────────────────────────
def qaqc_intervals(intervals: "List[dict]") -> dict:
    """QA/QC formal: cada hallazgo con fila (1-based del listado), severidad y
    acción. `bloqueante` = el intervalo no puede usarse como ancla sin
    corrección; `advertencia` = usable pero revisar."""
    findings: List[dict] = []

    def _add(row, severity, code, message):
        findings.append({
            "row": row, "severity": severity, "code": code, "message": message,
        })

    by_hole: Dict[str, List[Tuple[int, dict]]] = {}
    seen_exact: set = set()
    for i, iv in enumerate(intervals, start=1):
        hole = str(iv.get("hole_id", "?"))
        try:
            f = float(iv["depth_from"])
            t = float(iv["depth_to"])
        except (KeyError, TypeError, ValueError):
            _add(i, SEV_BLOCKING, "INTERVALO_ILEGIBLE",
                 f"Fila {i} ('{hole}'): depth_from/depth_to ausentes o no numéricos.")
            continue
        if f < 0 or t < 0:
            _add(i, SEV_BLOCKING, "PROFUNDIDAD_NEGATIVA",
                 f"Fila {i} ('{hole}'): profundidad negativa ({f}, {t}).")
            continue
        if f >= t:
            _add(i, SEV_BLOCKING, "FROM_MAYOR_IGUAL_TO",
                 f"Fila {i} ('{hole}'): FROM={f} ≥ TO={t} — intervalo invertido o nulo.")
            continue
        key = (hole, round(f, 4), round(t, 4))
        if key in seen_exact:
            _add(i, SEV_WARNING, "INTERVALO_DUPLICADO",
                 f"Fila {i} ('{hole}'): intervalo {f}-{t} m duplicado exacto.")
        seen_exact.add(key)

        dens = iv.get("density")
        if dens is not None and str(dens) != "":
            try:
                dv = float(dens)
                if not (DENSITY_PHYSICAL_MIN <= dv <= DENSITY_PHYSICAL_MAX):
                    _add(i, SEV_WARNING, "DENSIDAD_FUERA_DE_RANGO",
                         f"Fila {i} ('{hole}'): densidad {dv} t/m³ fuera del rango "
                         f"físico de rocas [{DENSITY_PHYSICAL_MIN}, {DENSITY_PHYSICAL_MAX}] — "
                         "¿unidad equivocada (g/cc vs kg/m³)?")
            except (TypeError, ValueError):
                _add(i, SEV_WARNING, "DENSIDAD_ILEGIBLE",
                     f"Fila {i} ('{hole}'): densidad no numérica ('{dens}').")
        elif not iv.get("lithology"):
            _add(i, SEV_WARNING, "SIN_DENSIDAD_NI_LITOLOGIA",
                 f"Fila {i} ('{hole}'): sin densidad ni litología — el intervalo "
                 "no aporta al anclaje ni a los priors PGI.")
        by_hole.setdefault(hole, []).append((i, {"from": f, "to": t}))

    for hole, rows in by_hole.items():
        rows_sorted = sorted(rows, key=lambda r: r[1]["from"])
        for (i1, a), (i2, b) in zip(rows_sorted, rows_sorted[1:]):
            if b["from"] < a["to"] - _GAP_OVERLAP_TOL_M:
                _add(i2, SEV_BLOCKING, "SOLAPE",
                     f"Filas {i1}/{i2} ('{hole}'): intervalos solapados "
                     f"({a['from']}-{a['to']} y {b['from']}-{b['to']} m).")
            elif b["from"] > a["to"] + _GAP_OVERLAP_TOL_M:
                _add(i2, SEV_WARNING, "HUECO",
                     f"Filas {i1}/{i2} ('{hole}'): hueco de "
                     f"{b['from'] - a['to']:.2f} m entre {a['to']} y {b['from']} m.")

    n_block = sum(1 for f in findings if f["severity"] == SEV_BLOCKING)
    n_warn = len(findings) - n_block
    return {
        "findings": findings,
        "n_blocking": n_block,
        "n_warnings": n_warn,
        "n_intervals": len(intervals),
        "usable": n_block == 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Compositación a intervalos regulares
# ─────────────────────────────────────────────────────────────────────────────
def composite_intervals(
    intervals: "List[dict]",
    composite_length_m: float,
    min_coverage: float = 0.5,
) -> "Tuple[List[dict], List[str]]":
    """Composita por pozo a ventanas regulares [k·L, (k+1)·L).

    Densidad = promedio ponderado por largo; litología = moda por largo.
    Composites con cobertura < min_coverage se DESCARTAN con aviso (jamás se
    inventa densidad para el tramo sin datos).
    """
    if composite_length_m <= 0:
        raise ValueError("composite_length_m debe ser > 0.")
    warnings: List[str] = []
    by_hole: Dict[str, List[dict]] = {}
    for iv in intervals:
        by_hole.setdefault(str(iv.get("hole_id", "?")), []).append(iv)

    out: List[dict] = []
    n_dropped = 0
    for hole, ivs in by_hole.items():
        max_to = max(float(iv["depth_to"]) for iv in ivs)
        n_comp = int(np.ceil(max_to / composite_length_m))
        for k in range(n_comp):
            c_from = k * composite_length_m
            c_to = (k + 1) * composite_length_m
            cover = 0.0
            dens_wsum = 0.0
            dens_w = 0.0
            litho_w: Dict[str, float] = {}
            for iv in ivs:
                f, t = float(iv["depth_from"]), float(iv["depth_to"])
                lo, hi = max(f, c_from), min(t, c_to)
                if hi <= lo:
                    continue
                w = hi - lo
                cover += w
                d = iv.get("density")
                if d is not None and str(d) != "":
                    try:
                        dens_wsum += float(d) * w
                        dens_w += w
                    except (TypeError, ValueError):
                        pass
                lit = str(iv.get("lithology") or "").strip()
                if lit:
                    litho_w[lit] = litho_w.get(lit, 0.0) + w
            if cover / composite_length_m < min_coverage:
                if cover > 0:
                    n_dropped += 1
                continue
            comp: dict = {
                "hole_id": hole,
                "depth_from": c_from,
                "depth_to": c_to,
                "coverage": cover / composite_length_m,
            }
            if dens_w > 0:
                comp["density"] = dens_wsum / dens_w
            if litho_w:
                comp["lithology"] = max(litho_w.items(), key=lambda kv: kv[1])[0]
            out.append(comp)
    if n_dropped:
        warnings.append(
            f"{n_dropped} composite(s) con cobertura <{min_coverage:.0%} se "
            "descartaron (no se inventa densidad para tramos sin datos)."
        )
    return out, warnings
