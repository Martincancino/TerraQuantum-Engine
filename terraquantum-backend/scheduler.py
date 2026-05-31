import polars as pl
import numpy as np
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Camiones.fms import TruckPhysics, DispatchEngineV2

# El scheduler opera siempre sobre bloques "normalizados" de 25m equivalentes.
# Con blockSize regional (ej. 1552m), el tonnage real por bloque supera 1e10 t,
# lo que provoca overflow en comparaciones y acumulaciones del loop LOM.
SCHEDULER_NORMALIZED_BLOCK_SIZE_M = 25.0
_NORMALIZED_BLOCK_VOLUME_M3 = SCHEDULER_NORMALIZED_BLOCK_SIZE_M ** 3  # 15_625 m³
_MAX_REASONABLE_BLOCK_TONNAGE = 1e8  # Umbral: >100M t/bloque → escala regional


class ProductionScheduler:
    def __init__(
        self,
        df: pl.DataFrame,
        base_p_cap=80_000_000,
        discount_rate=0.10,
        fleet_size=20,
    ):
        self.df = df
        self.p_cap = float(base_p_cap)
        self.discount_rate = float(discount_rate)
        self.fleet_size = int(fleet_size)

        self.physics = TruckPhysics(payload_t=360.0)
        self.dispatch = DispatchEngineV2(self.physics)

    def _simulate_annual_capacity(self, avg_depth_y, phase_id):
        self.dispatch.reset_network()

        depth_meters = float(avg_depth_y) * 10.0
        ramp_gradient = 10.0

        # PALA 1: fondo
        dist_fondo = 1.5 + (depth_meters / (ramp_gradient / 100.0)) / 1000.0
        self.dispatch.add_shovel("PALA_FONDO", "NODO_FONDO")
        self.dispatch.add_route(
            "NODO_FONDO",
            "DUMP_MAIN",
            distance_km=dist_fondo,
            gradient_pct=ramp_gradient,
        )

        # PALA 2: medio
        depth_medio = max(0.0, depth_meters - 30.0)
        dist_medio = 1.5 + (depth_medio / (ramp_gradient / 100.0)) / 1000.0
        self.dispatch.add_shovel("PALA_MEDIO", "NODO_MEDIO")
        self.dispatch.add_route(
            "NODO_MEDIO",
            "DUMP_MAIN",
            distance_km=dist_medio,
            gradient_pct=ramp_gradient,
        )

        tph_real = self.dispatch.run_shift(
            self.fleet_size,
            dump_node="DUMP_MAIN",
            shift_hours=12.0,
        )

        return float(tph_real) * 24.0 * 360.0

    def _ensure_required_columns(self):
        required = {
            "phase",
            "profit",
            "tonnage",
            "grade",
        }

        missing = required - set(self.df.columns)

        if missing:
            raise ValueError(
                f"ProductionScheduler recibió un DataFrame incompleto. "
                f"Faltan columnas: {sorted(missing)}"
            )

        if "resource_class" not in self.df.columns:
            print("[SCHEDULER] resource_class no existe. Se crea como clase 1 por defecto.")
            self.df = self.df.with_columns(
                pl.lit(1).cast(pl.Int8).alias("resource_class")
            )

        if "iy" not in self.df.columns:
            if "y" in self.df.columns:
                print("[SCHEDULER] iy no existe. Se crea desde y.")
                self.df = self.df.with_columns(
                    pl.col("y").cast(pl.Int32).alias("iy")
                )
            else:
                print("[SCHEDULER] iy/y no existen. Se crea iy=0.")
                self.df = self.df.with_columns(
                    pl.lit(0).cast(pl.Int32).alias("iy")
                )

    def run(self):
        print("[SCHEDULER] Secuenciador LOM Top-Down...")

        self._ensure_required_columns()

        df_pit = self.df.filter(pl.col("phase") > 0)

        if len(df_pit) == 0:
            print("[SCHEDULER] No hay bloques con phase > 0. Retornando schedule vacío.")
            return (
                self.df.with_columns(
                    pl.lit(0).cast(pl.Int32).alias("extraction_year")
                ),
                [],
                0.0,
            )

        df_pit = df_pit.with_columns(
            [
                pl.when(pl.col("resource_class") == 3)
                .then(0.0)
                .otherwise(pl.col("grade"))
                .alias("g_real"),

                (pl.col("profit") > 0).alias("is_ore"),

                pl.when(pl.col("tonnage") > 0)
                .then(pl.col("profit") / pl.col("tonnage"))
                .otherwise(0.0)
                .alias("vpt"),
            ]
        )

        # Orden top-down:
        # phase ascendente, iy ascendente, valor por tonelada descendente
        df_sorted = df_pit.sort(
            by=["phase", "iy", "vpt"],
            descending=[False, False, True],
        )

        ton = df_sorted["tonnage"].to_numpy().astype(float)
        prof = df_sorted["profit"].to_numpy().astype(float)
        ore = df_sorted["is_ore"].to_numpy().astype(bool)
        y_coords = df_sorted["iy"].to_numpy().astype(float)
        phases = df_sorted["phase"].to_numpy().astype(int)

        # ── Normalización de tonelaje para datasets regionales ────────────────
        # Si el tonnage por bloque supera _MAX_REASONABLE_BLOCK_TONNAGE, el
        # blockSize real es demasiado grande (ej. 1552m) y causaría overflow en
        # comparaciones y acumulaciones del loop LOM (errno 34 / ERANGE).
        # Se reemplaza por tonnage calculado sobre blockSize normalizado de 25m.
        # Los valores resultantes son "relativos" (correctos para comparación
        # entre bloques) pero NO representativos de tonelaje absoluto real.
        max_block_ton = float(np.max(ton)) if len(ton) > 0 else 0.0
        if max_block_ton > _MAX_REASONABLE_BLOCK_TONNAGE and "density" in df_sorted.columns:
            density_arr = df_sorted["density"].to_numpy().astype(float)
            ton = density_arr * _NORMALIZED_BLOCK_VOLUME_M3
            print(
                f"[SCHEDULER] Tonelaje normalizado a blockSize equivalente "
                f"{SCHEDULER_NORMALIZED_BLOCK_SIZE_M}m "
                f"(max original: {max_block_ton:.3e} t/bloque -> "
                f"max normalizado: {float(np.max(ton)):.3e} t/bloque). "
                "Tonelaje absoluto no representativo para escala regional."
            )

        # Guard: reemplazar valores no finitos por 0 (no bloqueantes)
        _MAX_SAFE_TONNAGE = sys.float_info.max / 1000
        not_finite_mask = ~np.isfinite(ton)
        if np.any(not_finite_mask):
            ton = np.where(not_finite_mask, 0.0, ton)
        overflow_mask = ton > _MAX_SAFE_TONNAGE
        if np.any(overflow_mask):
            ton = np.where(overflow_mask, 0.0, ton)
        # ─────────────────────────────────────────────────────────────────────

        if len(ton) == 0:
            return (
                df_sorted.with_columns(
                    pl.lit(0).cast(pl.Int32).alias("extraction_year")
                ),
                [],
                0.0,
            )

        years = np.zeros(len(ton), dtype=np.int32)

        curr_y = 1
        p_rem = self.p_cap

        metrics = []

        cf_y = 0.0
        o_y = 0.0
        w_y = 0.0

        current_m_cap = self._simulate_annual_capacity(y_coords[0], phases[0])
        m_rem = current_m_cap

        for i in range(len(ton)):
            t = float(ton[i])
            p = float(prof[i])
            o = bool(ore[i])

            can_mine_ore = o and m_rem >= t and p_rem >= t
            can_mine_waste = (not o) and m_rem >= t

            if can_mine_ore or can_mine_waste:
                years[i] = curr_y
                cf_y += p

                if o:
                    o_y += t
                    p_rem -= t
                else:
                    w_y += t

                m_rem -= t

            else:
                metrics.append(
                    {
                        "year": int(curr_y),
                        "cf": float(cf_y),
                        "ore": float(o_y),
                        "waste": float(w_y),
                        "m_cap_used": float(current_m_cap),
                    }
                )

                curr_y += 1

                current_m_cap = self._simulate_annual_capacity(
                    y_coords[i],
                    phases[i],
                )

                m_rem = current_m_cap - t
                p_rem = self.p_cap - (t if o else 0.0)

                cf_y = p
                o_y = t if o else 0.0
                w_y = 0.0 if o else t

                years[i] = curr_y

        metrics.append(
            {
                "year": int(curr_y),
                "cf": float(cf_y),
                "ore": float(o_y),
                "waste": float(w_y),
                "m_cap_used": float(current_m_cap),
            }
        )

        total_npv = 0.0

        for m in metrics:
            year = int(m["year"])
            cf = float(m["cf"])
            total_npv += cf / ((1.0 + self.discount_rate) ** year)

        df_result = df_sorted.with_columns(
            pl.Series("extraction_year", years)
        )

        print(
            f"[SCHEDULER] Schedule completado. "
            f"Años: {len(metrics)} | NPV: ${total_npv:,.0f}"
        )

        return df_result, metrics, float(total_npv)