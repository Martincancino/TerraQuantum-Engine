"""FASE 11 — El paquete TQPKG visto desde un script.

El paquete es la pieza que hace reproducible una corrida: un solo archivo de
texto con la configuración, los sondajes, el plan multimodal y las estaciones ya
normalizadas. Guardarlo es guardar el experimento entero.

Esta clase no lo re-implementa: envuelve el texto que produjo
`POST /v2/gravity-import/enrich-package` y lo relee con el MISMO parser del
backend (`services.csv_package_service.parse_package_text`), así que si el
formato cambia, cambia para los dos a la vez.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Package:
    """Un paquete TQPKG listo para invertir.

    Atributos que un script mira de verdad:
      · `needs_context` — lo que el enriquecimiento **no pudo derivar** y por
        tanto NO inventó. Una lista no vacía no impide invertir, pero es la
        diferencia entre un resultado y un resultado que sabes interpretar.
      · `warnings` — degradaciones con motivo (preámbulo omitido, unidad
        inferida del nombre de la columna, topografía plana…). El canal de la
        Fase 1/H-27: si el backend degradó algo, aquí está dicho.
      · `plan` — la ruta decidida (`gravity_only`/`joint`/…) y su confianza.
    """

    text: str
    filename: str = "package.tqpkg.csv"
    n_stations: int = 0
    plan: Dict[str, Any] = field(default_factory=dict)
    enrichment: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    needs_context: List[Any] = field(default_factory=list)
    sniff: Dict[str, Any] = field(default_factory=dict)

    # ── Lectura ───────────────────────────────────────────────────────────────

    @property
    def route(self) -> str:
        """Ruta física que el backend usará (la decide el plan, no el script)."""
        return str(self.plan.get("route") or "gravity_only")

    @property
    def config(self) -> Dict[str, Any]:
        """La configuración EFECTIVA escrita en el encabezado `#CONFIG`.

        Se relee con el parser del backend a propósito: es la única forma de
        que «lo que creo que pedí» y «lo que el solver va a leer» no puedan
        divergir.
        """
        from services.csv_package_service import parse_package_text

        return dict(parse_package_text(self.text).config)

    @property
    def boreholes(self) -> List[dict]:
        from services.csv_package_service import parse_package_text

        return list(parse_package_text(self.text).boreholes or [])

    @property
    def steps(self) -> List[Any]:
        """Qué hizo el enriquecimiento, paso a paso (física real, no relleno)."""
        return list((self.enrichment or {}).get("steps") or [])

    @property
    def columns_added(self) -> List[Any]:
        return list((self.enrichment or {}).get("columns_added") or [])

    # ── Persistencia ──────────────────────────────────────────────────────────

    def save(self, path: "str | pathlib.Path") -> pathlib.Path:
        """Escribe el paquete a disco. Es el artefacto reproducible de la corrida."""
        destino = pathlib.Path(path)
        if destino.is_dir():
            destino = destino / self.filename
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(self.text, encoding="utf-8")
        return destino

    @classmethod
    def from_file(cls, path: "str | pathlib.Path") -> "Package":
        """Relee un paquete guardado. Valida que sea TQPKG con el parser oficial.

        Los campos que sólo produce el enriquecimiento (`warnings`,
        `needs_context`, `enrichment`) quedan **vacíos**, porque no están en el
        archivo: el paquete guarda la configuración y el dato, no el relato de
        cómo se derivó. Fingir que sí los lleva sería inventar procedencia.
        """
        from services.csv_package_service import parse_package_text

        ruta = pathlib.Path(path)
        texto = ruta.read_text(encoding="utf-8")
        parsed = parse_package_text(texto)  # ValueError si no es un TQPKG
        n = max(0, len([ln for ln in parsed.body_csv.splitlines() if ln.strip()]) - 1)
        return cls(
            text=texto,
            filename=ruta.name,
            n_stations=n,
            plan=dict(parsed.plan or {}),
        )

    def __repr__(self) -> str:  # pragma: no cover - presentación
        pend = f", needs_context={len(self.needs_context)}" if self.needs_context else ""
        return (
            f"Package(route={self.route!r}, n_stations={self.n_stations}, "
            f"warnings={len(self.warnings)}{pend})"
        )


@dataclass
class ColumnPlan:
    """El plan de mapeo de columnas, sin invertir nada (`analyze-columns`).

    Sirve para lo que un consultor hace de verdad antes de procesar un lote:
    mirar UNA planilla, ver cómo se van a interpretar sus columnas, y escribir
    el `column_map` que va a reutilizar en los 12 surveys.
    """

    mapping: Dict[str, Any]
    sniff: Dict[str, Any] = field(default_factory=dict)
    sample_rows: List[dict] = field(default_factory=list)

    @property
    def needs_mapping(self) -> bool:
        return bool(self.mapping.get("needs_mapping"))

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.mapping.get("needs_confirmation"))

    @property
    def roles(self) -> Dict[str, Any]:
        """`{rol: columna}` tal como el importador lo va a leer."""
        return dict(self.mapping.get("roles") or {})

    @property
    def raw_columns(self) -> List[str]:
        return list(self.mapping.get("raw_columns") or [])

    @property
    def questions(self) -> List[dict]:
        return list(self.mapping.get("questions") or [])

    @property
    def suspicions(self) -> Any:
        """Lo que la heurística de RANGO físico sospecha (northing en `y`…)."""
        return self.mapping.get("suspicions")

    @property
    def suggestions(self) -> Dict[str, Any]:
        """`{rol: {column, confidence, reason}}` propuesto por RANGO de valores.

        Lo añade la Fase 16 (H-F11-1). Desde que una terna `x/y/z` desnuda se
        PREGUNTA en vez de adivinarse, `needs_mapping=True` es una respuesta
        frecuente y legítima — y un script que sólo ve el `True` no tiene con qué
        seguir. El backend ya calculaba estas sugerencias y las publica en el
        contrato (`ingest_contracts_schema`); lo que faltaba era el accesor, así
        que desde Python había que hurgar en `plan.mapping`.

        Nunca son de confianza alta: se proponen para confirmar, jamás se aplican
        solas. Ése es el contrato que el propio `column_mapping_service` declara.
        """
        return dict(self.mapping.get("suggestions") or {})

    @property
    def confidence(self) -> Optional[float]:
        valor = self.mapping.get("confidence")
        return float(valor) if isinstance(valor, (int, float)) else None

    def __repr__(self) -> str:  # pragma: no cover - presentación
        return (
            f"ColumnPlan(needs_mapping={self.needs_mapping}, "
            f"needs_confirmation={self.needs_confirmation}, roles={self.roles})"
        )
