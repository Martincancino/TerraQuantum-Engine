"""
F2 (apertura) — Inferencia de unidad desde header con unidad embebida.

Bug destapado por la suite completa (2026-07-03, preexistente a F1): un CSV de
gravedad con columna `g_mgal` y SIN columna `unit` moría con
"Missing required column: unit", aunque el propio header declara la unidad.

Regla implementada (gravity_import_service):
  - Si la columna de gravedad elegida lleva "mgal" embebido en el nombre
    (g_mgal, bouguer_mgal, gravity_mgal, free_air_mgal...) → se infiere mGal
    CON warning explícito (nunca en silencio).
  - Si no hay evidencia embebida ni mapeo manual → sigue siendo error
    (no adivinar: lección del doble-Bouguer).

FASE 16 — por qué cambió el encabezado de estos CSV. Usaban `x,y,z`, que dejó de
auto-resolverse (H-F11-1: `y` junto a `x` y `z` es ambiguo y ahora se pregunta).
El encabezado era ANDAMIAJE —el tema de este fichero es la UNIDAD, no los ejes— y
además estaba mal: con la tercera columna a 0 en todas las filas, la vieja
lectura mandaba TODAS las estaciones a norte=0, una geometría degenerada que
ningún assert miraba. Ahora es `x,z,depth_m`, que es el contrato documentado y
da una geometría no degenerada.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gravity_import_service import import_gravity_csv_v1


def _write_csv(text: str) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(text)
    f.close()
    return f.name


def _rows(n: int = 12) -> str:
    return "\n".join(
        f"{i * 100},{(i % 3) * 100},0,{0.1 + i * 0.01}" for i in range(n)
    )


class TestUnitInferenceFromHeader:
    def test_g_mgal_header_infers_unit_with_warning(self):
        """CSV x,z,depth_m,g_mgal sin columna unit → importa OK e infiere mGal avisando."""
        path = _write_csv("x,z,depth_m,g_mgal\n" + _rows())
        try:
            result = import_gravity_csv_v1(path, strict=False)
            assert not any(
                "Missing required column: unit" in e for e in result.errors
            ), f"errors: {result.errors}"
            assert result.observations, f"sin observaciones; errors: {result.errors}"
            assert any("inferida mGal" in w for w in result.warnings), (
                f"falta el warning de inferencia; warnings: {result.warnings}"
            )
        finally:
            os.unlink(path)

    def test_bouguer_mgal_header_also_infers(self):
        path = _write_csv("x,z,depth_m,bouguer_mgal\n" + _rows())
        try:
            result = import_gravity_csv_v1(path, strict=False)
            assert not any("Missing required column: unit" in e for e in result.errors)
            assert result.observations
        finally:
            os.unlink(path)

    def test_plain_g_header_without_unit_still_errors(self):
        """Sin unidad embebida ni columna unit → sigue exigiendo unit (no adivinar)."""
        path = _write_csv("x,z,depth_m,g\n" + _rows())
        try:
            result = import_gravity_csv_v1(path, strict=False)
            assert any(
                "Missing required column: unit" in e for e in result.errors
            ), f"debió exigir unit; errors: {result.errors}"
        finally:
            os.unlink(path)

    def test_explicit_unit_column_unchanged(self):
        """Con columna unit explícita el comportamiento histórico no cambia."""
        rows = "\n".join(
            f"{i * 100},{(i % 3) * 100},0,{0.1 + i * 0.01},mGal" for i in range(12)
        )
        path = _write_csv("x,z,depth_m,g,unit\n" + rows)
        try:
            result = import_gravity_csv_v1(path, strict=False)
            assert result.observations, f"errors: {result.errors}"
            assert not any("inferida" in w for w in result.warnings)
        finally:
            os.unlink(path)
