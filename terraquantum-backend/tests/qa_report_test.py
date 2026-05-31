"""
FASE 11 — QA de Trazabilidad: Config Hash.

Verifica que el hash SHA-256 de los parámetros de inversión cambia cada vez
que cambia cualquier clave física auditada, y permanece estable si solo cambian
metadatos de UI no auditados.

Esta propiedad es el núcleo de la trazabilidad JORC/NI-43-101:
garantiza que dos runs con hashes idénticos tendrán resultados reproducibles.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

# Asegurar que el backend esté en el path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from reporting.report_generator import _build_config_hash


# ─── Fixtures ────────────────────────────────────────────────────────────────

BASE_INPUTS: dict = {
    "nx": 32,
    "ny": 20,
    "nz": 32,
    "block_size": 1552.0,
    "cutoff_radius": 3000.0,
    "lambda_mag": 1e-3,
    "alpha_spatial": 1.0,
    "depth": 5000.0,
    "nir": 60,
    "fe": 40,
    "enable_focusing": False,
    "noise_floor": 0.01,
    "noise_pct": 0.05,
}

NON_AUDITED_KEYS = [
    "region",
    "lat",
    "lon",
    "project_id",
    "run_id",
    "ui_theme",
    "user_note",
    "timestamp",
    "session_token",
]


# ─── Tests de determinismo ────────────────────────────────────────────────────

class TestConfigHashDeterminism:
    """El hash debe ser idéntico para el mismo set de parámetros."""

    def test_same_inputs_produce_same_hash(self):
        """Propiedad fundamental: mismos params → mismo hash."""
        h1 = _build_config_hash(BASE_INPUTS.copy())
        h2 = _build_config_hash(BASE_INPUTS.copy())
        assert h1 == h2, "El mismo set de parámetros debe producir siempre el mismo hash."

    def test_hash_is_nonempty_string(self):
        h = _build_config_hash(BASE_INPUTS.copy())
        assert isinstance(h, str)
        assert len(h) > 0

    def test_hash_is_16_hex_chars_uppercase(self):
        """El hash debe ser los primeros 16 caracteres de SHA-256 en mayúsculas."""
        h = _build_config_hash(BASE_INPUTS.copy())
        assert len(h) == 16, f"Longitud esperada: 16, obtenida: {len(h)}"
        assert h == h.upper(), "El hash debe estar en mayúsculas."
        # Debe ser hexadecimal válido
        int(h, 16)  # lanza ValueError si no es hex

    def test_empty_inputs_hash_is_deterministic(self):
        """Inputs vacíos deben producir un hash válido y determinista."""
        h1 = _build_config_hash({})
        h2 = _build_config_hash({})
        assert h1 == h2

    def test_partial_inputs_hash_is_deterministic(self):
        partial = {"nx": 16, "nz": 16, "lambda_mag": 0.01}
        h1 = _build_config_hash(partial)
        h2 = _build_config_hash(partial)
        assert h1 == h2


# ─── Tests de sensibilidad a cambios ─────────────────────────────────────────

class TestConfigHashChangesOnAuditedKeyChange:
    """Cambiar CUALQUIER clave auditada debe cambiar el hash (trazabilidad estricta)."""

    @pytest.mark.parametrize("key,new_value", [
        ("nx",             64),
        ("ny",             40),
        ("nz",             64),
        ("block_size",     500.0),
        ("cutoff_radius",  1500.0),
        ("lambda_mag",     1e-2),
        ("alpha_spatial",  0.5),
        ("depth",          3000.0),
        ("nir",            80),
        ("fe",             20),
        ("enable_focusing", True),
        ("noise_floor",    0.05),
        ("noise_pct",      0.10),
    ])
    def test_audited_key_change_changes_hash(self, key: str, new_value):
        """
        Propiedad de trazabilidad: si se cambia el parámetro físico `key`,
        el Config Hash del reporte debe ser diferente al del run original.
        """
        original_hash = _build_config_hash(BASE_INPUTS.copy())

        modified = BASE_INPUTS.copy()
        modified[key] = new_value
        modified_hash = _build_config_hash(modified)

        assert original_hash != modified_hash, (
            f"Cambiar '{key}' de {BASE_INPUTS[key]!r} a {new_value!r} "
            f"debe producir un hash diferente. "
            f"Original: {original_hash} | Modificado: {modified_hash}"
        )


# ─── Tests de estabilidad ante claves no auditadas ───────────────────────────

class TestConfigHashStableOnNonAuditedKeyChange:
    """Cambiar metadatos de UI/trace NO debe cambiar el hash."""

    @pytest.mark.parametrize("key", NON_AUDITED_KEYS)
    def test_non_audited_key_does_not_change_hash(self, key: str):
        """
        Claves de UI/metadatos no afectan la física del run
        y por tanto NO deben cambiar el Config Hash.
        """
        original_hash = _build_config_hash(BASE_INPUTS.copy())

        modified = BASE_INPUTS.copy()
        modified[key] = "test_value_does_not_matter"
        modified_hash = _build_config_hash(modified)

        assert original_hash == modified_hash, (
            f"La clave no auditada '{key}' no debería cambiar el hash. "
            f"Original: {original_hash} | Modificado: {modified_hash}"
        )


# ─── Tests de orden de claves (sort_keys) ────────────────────────────────────

class TestConfigHashKeyOrderIndependence:
    """El orden de inserción del dict no debe afectar el hash."""

    def test_key_order_does_not_affect_hash(self):
        """json.dumps(sort_keys=True) garantiza orden determinista."""
        inputs_a = {
            "nx": 32, "lambda_mag": 1e-3, "depth": 5000.0,
            "nz": 32, "ny": 20, "block_size": 1552.0,
        }
        inputs_b = {
            "depth": 5000.0, "block_size": 1552.0, "nz": 32,
            "nx": 32, "ny": 20, "lambda_mag": 1e-3,
        }
        assert _build_config_hash(inputs_a) == _build_config_hash(inputs_b), (
            "El orden de las claves en el dict no debe afectar el Config Hash."
        )


# ─── Tests de unicidad entre runs distintos ──────────────────────────────────

class TestConfigHashUniqueness:
    """Verifica que configuraciones razonablemente distintas producen hashes distintos."""

    def test_different_grid_sizes_produce_different_hashes(self):
        configs = [
            {**BASE_INPUTS, "nx": nx, "ny": ny, "nz": nz}
            for nx, ny, nz in [(8, 8, 8), (16, 10, 16), (32, 20, 32), (64, 40, 64)]
        ]
        hashes = [_build_config_hash(c) for c in configs]
        assert len(set(hashes)) == len(hashes), (
            "Cada configuración de grilla distinta debe producir un hash único."
        )

    def test_different_lambdas_produce_different_hashes(self):
        lambdas = [1e-5, 1e-4, 1e-3, 1e-2, 1e-1]
        hashes = [_build_config_hash({**BASE_INPUTS, "lambda_mag": lam}) for lam in lambdas]
        assert len(set(hashes)) == len(hashes), (
            "Cada valor de lambda debe producir un hash único."
        )


# ─── Tests de formato del reporte HTML ───────────────────────────────────────

class TestReportContainsAuditSection:
    """Verifica que el reporte HTML contiene la sección de audit trail."""

    def test_report_html_contains_config_hash_section(self):
        """
        El reporte HTML generado debe contener la sección SYSTEM AUDIT
        con el config hash y el disclaimer JORC/NI-43-101.
        """
        # Import aquí para aislar el test de I/O del disco
        from reporting.report_generator import (
            _build_config_hash,
            _system_audit_section_html,
        )

        test_inputs = BASE_INPUTS.copy()
        test_inputs["project_id"] = "test_proj"
        test_inputs["run_id"] = "test_run_001"

        cfg_hash = _build_config_hash(test_inputs)
        audit_html = _system_audit_section_html(
            project_id="test_proj",
            run_id="test_run_001",
            inputs=test_inputs,
            generated_utc="2026-01-01 00:00:00 UTC",
        )

        assert "SYSTEM AUDIT" in audit_html, "El HTML debe contener la sección SYSTEM AUDIT."
        assert cfg_hash in audit_html, (
            f"El Config Hash '{cfg_hash}' debe aparecer en la sección de audit."
        )
        assert "SHA256" in audit_html, "El audit HTML debe indicar el algoritmo SHA256."
        assert "Trazabilidad" in audit_html or "trazabilidad" in audit_html.lower()

    def test_changing_params_changes_hash_in_audit_section(self):
        """
        Si cambian los parámetros físicos, el hash en el reporte HTML cambia.
        """
        from reporting.report_generator import (
            _build_config_hash,
            _system_audit_section_html,
        )

        inputs_v1 = {**BASE_INPUTS, "lambda_mag": 1e-3}
        inputs_v2 = {**BASE_INPUTS, "lambda_mag": 9e-2}  # lambda diferente

        hash_v1 = _build_config_hash(inputs_v1)
        hash_v2 = _build_config_hash(inputs_v2)

        assert hash_v1 != hash_v2, (
            "Un cambio en lambda_mag debe producir hashes distintos."
        )

        html_v1 = _system_audit_section_html("p1", "r1", inputs_v1, "2026-01-01 UTC")
        html_v2 = _system_audit_section_html("p1", "r1", inputs_v2, "2026-01-01 UTC")

        assert hash_v1 in html_v1
        assert hash_v2 in html_v2
        assert hash_v1 not in html_v2, (
            "El reporte con lambda modificado NO debe contener el hash original."
        )
