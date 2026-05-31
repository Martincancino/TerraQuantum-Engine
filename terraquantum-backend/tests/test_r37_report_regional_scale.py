"""
R3.7-E — Tests del HTML generado por generate_technical_report_html
para la sección "Escala del Dataset".

Casos obligatorios (10):
1.  HTML con REGIONAL_SCALE muestra 'Escala del Dataset'
2.  HTML muestra scale_class
3.  HTML muestra extent
4.  HTML muestra grid nx/ny/nz
5.  HTML muestra warnings
6.  HTML muestra recommended_action
7.  HTML con TOO_LARGE muestra alerta roja (rs-alert-red)
8.  HTML con LOCAL_SURVEY no muestra alerta roja (rs-alert-red)
9.  HTML legacy sin preflight no crashea y muestra sección
10. HTML no contiene lenguaje peligroso
"""
import unittest
from unittest.mock import MagicMock, patch

from reporting.report_generator import (
    _regional_scale_preflight_section_html,
    generate_technical_report_html,
)


# ---------------------------------------------------------------------------
# Payloads mínimos de preflight
# ---------------------------------------------------------------------------

def _regional_rsp():
    return {
        "version": "1.0",
        "scale_class": "REGIONAL_SCALE",
        "can_run_single_inversion": True,
        "requires_user_acknowledgement": True,
        "recommended_action": "Ejecutar con acknowledgement y revisar resultados con profesional.",
        "extent_x_m": 50000.0,
        "extent_z_m": 30000.0,
        "area_km2": 1500.0,
        "station_count": 77,
        "estimated_nx": 20,
        "estimated_ny": 10,
        "estimated_nz": 20,
        "estimated_voxel_count": 4000,
        "estimated_depth_m": 10000.0,
        "estimated_block_size_m": 500.0,
        "max_allowed_nx": 80,
        "max_allowed_ny": 40,
        "max_allowed_nz": 80,
        "warnings": ["Cobertura de estaciones baja para escala regional."],
        "blocked_reasons": [],
        "allowed_outputs": ["inversion_regional_conceptual"],
        "rationale": "Extensión ~50 km x 30 km cae en rango REGIONAL_SCALE.",
    }


def _too_large_rsp():
    return {
        "version": "1.0",
        "scale_class": "TOO_LARGE_SINGLE_INVERSION",
        "can_run_single_inversion": False,
        "requires_user_acknowledgement": False,
        "recommended_action": "Crear un subset espacial o usar tileado.",
        "extent_x_m": 250000.0,
        "extent_z_m": 200000.0,
        "area_km2": 50000.0,
        "station_count": 121,
        "estimated_nx": 100,
        "estimated_ny": 50,
        "estimated_nz": 100,
        "estimated_voxel_count": 500000,
        "estimated_depth_m": 50000.0,
        "estimated_block_size_m": 2500.0,
        "max_allowed_nx": 80,
        "max_allowed_ny": 40,
        "max_allowed_nz": 80,
        "warnings": ["Grilla excede límites de inversión única."],
        "blocked_reasons": ["nx=100 > max_allowed_nx=80"],
        "allowed_outputs": [],
        "rationale": "nx/nz estimados superan 80. Inversión única bloqueada.",
    }


def _local_survey_rsp():
    return {
        "version": "1.0",
        "scale_class": "LOCAL_SURVEY",
        "can_run_single_inversion": True,
        "requires_user_acknowledgement": False,
        "recommended_action": "Proceder con inversión local.",
        "extent_x_m": 800.0,
        "extent_z_m": 800.0,
        "area_km2": 0.64,
        "station_count": 25,
        "estimated_nx": 4,
        "estimated_ny": 4,
        "estimated_nz": 4,
        "estimated_voxel_count": 64,
        "estimated_depth_m": 200.0,
        "estimated_block_size_m": 50.0,
        "max_allowed_nx": 80,
        "max_allowed_ny": 40,
        "max_allowed_nz": 80,
        "warnings": [],
        "blocked_reasons": [],
        "allowed_outputs": ["inversion_local_preliminary"],
        "rationale": "Extensión <5 km LOCAL_SURVEY.",
    }


def _minimal_report(rsp=None, ack=None, scale_class="REGIONAL_SCALE"):
    """Report dict mínimo para generate_technical_report_html."""
    return {
        "status": "done",
        "priority_class": "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE",
        "model_reliability_level": "UNCLASSIFIED_RELIABILITY",
        "max_ranking_score": 0,
        "recommendation": "OBSERVE",
        "risk_level": "HIGH",
        "max_probability": 0,
        "drill_recommendation": "OBSERVE",
        "_legacy_recommendation_deprecated": "OBSERVE",
        "_legacy_risk_level_deprecated": "HIGH",
        "_legacy_max_probability_deprecated": 0,
        "_legacy_drill_recommendation_deprecated": "OBSERVE",
        "min_density": 0,
        "avg_density": 0,
        "max_density": 0,
        "estimated_total_tonnage": 0,
        "estimated_anomaly_tonnage": 0,
        "avg_grade": 0,
        "anomaly_score": 0,
        "cutoff_density": 2.75,
        "total_voxels": 64,
        "returned_voxels": 0,
        "parquet_path": "/tmp/test.parquet",
        "avg_anomaly_intensity": 0,
        "max_target_score": 0,
        "confidence_level": "UNKNOWN",
        "semantic_note": "",
        "misfit_error_percent": 0.0,
        "regional_scale_preflight": rsp,
        "acknowledge_regional_scale": ack,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FORBIDDEN_PHRASES = [
    "posición exacta",
    "perforar aquí",
    "perforar",
    "probabilidad ia",
    "mineral confirmado",
]


def _generate_html_with_mocks(report: dict) -> str:
    """Llama generate_technical_report_html con todos los side-effects en modo mock."""
    fake_meta = {
        "project_name": "Test",
        "region": "Test",
        "lat": -22.0,
        "lon": -68.0,
        "fe": 50,
        "nir": 50,
        "timestamp": "2026-01-01T00:00:00",
    }
    fake_inputs = {}
    fake_metrics = {}
    fake_favorability = {}

    with patch("reporting.report_generator.load_project_meta", return_value=fake_meta):
        return generate_technical_report_html(
            project_id="test_proj",
            run_id="test_run",
            report=report,
            metrics=fake_metrics,
            favorability=fake_favorability,
            inputs=fake_inputs,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReportRegionalScale(unittest.TestCase):

    # ── 1: sección Escala del Dataset siempre presente ────────────────────────

    def test_01_regional_scale_section_heading_present(self):
        """HTML con REGIONAL_SCALE muestra 'Escala del Dataset'."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=True)
        self.assertIn("Escala del Dataset", html)

    # ── 2: scale_class visible ────────────────────────────────────────────────

    def test_02_scale_class_shown_in_html(self):
        """HTML muestra scale_class."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=True)
        self.assertIn("REGIONAL_SCALE", html)

    # ── 3: extent visible ─────────────────────────────────────────────────────

    def test_03_extent_shown_in_html(self):
        """HTML muestra extent X × Z en metros."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=False)
        self.assertIn("50,000", html)
        self.assertIn("30,000", html)

    # ── 4: grid nx/ny/nz visible ──────────────────────────────────────────────

    def test_04_grid_shown_in_html(self):
        """HTML muestra grid estimada nx × ny × nz."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=False)
        self.assertIn("20", html)
        self.assertIn("10", html)

    # ── 5: warnings visibles ──────────────────────────────────────────────────

    def test_05_warnings_shown_in_html(self):
        """HTML muestra warnings del preflight."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=False)
        self.assertIn("Cobertura de estaciones baja", html)

    # ── 6: recommended_action visible ─────────────────────────────────────────

    def test_06_recommended_action_shown_in_html(self):
        """HTML muestra acción recomendada."""
        html = _regional_scale_preflight_section_html(_regional_rsp(), ack_regional=False)
        self.assertIn("acknowledgement", html.lower())

    # ── 7: TOO_LARGE → alerta roja ────────────────────────────────────────────

    def test_07_too_large_shows_red_alert(self):
        """HTML con TOO_LARGE muestra clase rs-alert-red."""
        html = _regional_scale_preflight_section_html(_too_large_rsp(), ack_regional=False)
        self.assertIn("rs-alert-red", html)

    # ── 8: LOCAL_SURVEY → sin alerta roja ────────────────────────────────────

    def test_08_local_survey_no_red_alert(self):
        """HTML con LOCAL_SURVEY no muestra rs-alert-red."""
        html = _regional_scale_preflight_section_html(_local_survey_rsp(), ack_regional=False)
        self.assertNotIn("rs-alert-red", html)
        # Debe mostrar la sección igual
        self.assertIn("Escala del Dataset", html)

    # ── 9: legacy (sin preflight) no crashea ──────────────────────────────────

    def test_09_legacy_no_preflight_no_crash(self):
        """HTML legacy sin preflight no crashea y contiene la sección."""
        html = _regional_scale_preflight_section_html(None, ack_regional=None)
        self.assertIn("Escala del Dataset", html)
        # Debe indicar que no está disponible
        self.assertIn("no disponible", html.lower())

    # ── 10: HTML no contiene lenguaje peligroso ───────────────────────────────

    def test_10_no_dangerous_language_in_html(self):
        """El HTML generado no contiene frases peligrosas."""
        for rsp, ack in [
            (_regional_rsp(), True),
            (_too_large_rsp(), False),
            (_local_survey_rsp(), False),
            (None, None),
        ]:
            html = _regional_scale_preflight_section_html(rsp, ack_regional=ack)
            lower = html.lower()
            for phrase in FORBIDDEN_PHRASES:
                self.assertNotIn(
                    phrase,
                    lower,
                    f"Frase peligrosa '{phrase}' encontrada en HTML (scale={rsp and rsp.get('scale_class')})",
                )

    # ── Bonus: generate_technical_report_html integra la sección ─────────────

    def test_b1_full_html_contains_regional_scale_section(self):
        """generate_technical_report_html integra la sección de escala."""
        report = _minimal_report(rsp=_regional_rsp(), ack=True)
        html = _generate_html_with_mocks(report)
        self.assertIn("Escala del Dataset", html)
        self.assertIn("REGIONAL_SCALE", html)

    def test_b2_full_html_too_large_has_red_alert(self):
        """HTML completo con TOO_LARGE contiene rs-alert-red."""
        report = _minimal_report(rsp=_too_large_rsp(), ack=False)
        html = _generate_html_with_mocks(report)
        self.assertIn("rs-alert-red", html)

    def test_b3_full_html_legacy_no_preflight_no_crash(self):
        """HTML completo sin preflight no crashea."""
        report = _minimal_report(rsp=None, ack=None)
        html = _generate_html_with_mocks(report)
        self.assertIn("Escala del Dataset", html)


if __name__ == "__main__":
    unittest.main()
