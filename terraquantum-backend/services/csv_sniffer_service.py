"""F2 — Sniffer universal de la capa física del CSV (encoding / separador /
decimal / preámbulo / filas rotas), CON EVIDENCIA.

El activo del producto es "cualquier CSV entra": un consultor con un export de
Excel-ES de 2009 (preámbulo de proyecto, ';' + coma decimal, cp1252) debe llegar
a un TQPKG sin pelear. Este módulo detecta la capa FÍSICA del archivo y produce
un `SniffReport` tipado que viaja al frontend para que el usuario CONFIRME:
"detecté separador ';', decimales con coma, 2 líneas de preámbulo — ¿correcto?".

Reglas (las mismas del fix 60d1c56 de unidad embebida):
  1. Inferir SOLO con evidencia (cada dimensión lleva evidencia + descartados).
  2. Avisar SIEMPRE (nada de decisiones silenciosas: el reporte es parte del dato).
  3. Jamás adivinar en silencio: lo indecidible se reporta "ambiguous" y la capa
     de ingesta lo convierte en error claro (AmbiguousDelimiterError), nunca en
     números corruptos sellados "Calidad GOOD".

GUARDRAIL byte-idéntico: para archivos UTF-8/latin-1 SIN preámbulo, la decisión
sep/decimal la sigue tomando la lógica histórica de `gravity_import_service`
(`_resolve_sep_decimal`); el sniffer solo AGREGA encoding robusto (UTF-8/BOM →
UTF-16 → cp1252 → latin-1), salto de preámbulo y reporte de filas rotas con
número de línea (antes se tragaban en silencio). Los tests del corpus y de la
matriz Fase 4 son el guardián de esa identidad.

`sniff_csv` NUNCA lanza: en fallo catastrófico devuelve un reporte de confianza
baja con el problema en `warnings` (contrato nunca-crashea de F2).
"""
from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger

_log = get_logger(__name__)

# Muestra acotada: suficiente para decidir formato, barata para archivos grandes.
_SAMPLE_BYTES = 262_144          # 256 KB
_SAMPLE_MAX_LINES = 200          # líneas físicas a analizar
_MAX_PREAMBLE_SCAN = 30          # un preámbulo real nunca es más largo que esto
_EXCERPT_CHARS = 90              # texto máximo por línea reportada
_MAX_BROKEN_REPORTED = 20        # filas rotas listadas con nº de línea

_SEPARATOR_CANDIDATES = (";", "\t", "|", ",")   # prioridad de desempate: el
# ';' gana a la ',' cuando ambos son consistentes (Excel-ES usa ',' decimal);
# tab/pipe casi nunca colisionan con texto.

_SEPARATOR_LABELS = {";": "';'", ",": "','", "\t": "tabulador", "|": "'|'"}


class AmbiguousDelimiterError(ValueError):
    """No se puede determinar delimitador/decimal del CSV con confianza.

    INVARIANTE (BUG decimal-coma e7d2858): la ingesta entrega dato LIMPIO o un
    ERROR CLARO, jamás un número silenciosamente equivocado con sello "Calidad
    GOOD". Se lanza, p.ej., con separador de miles (1,234,567) o comas de texto
    mezcladas dentro de un CSV ';'-delimitado, donde adivinar produciría basura.
    """


AMBIGUOUS_DELIM_MSG = (
    "Detecté ';' como delimitador pero las comas están mezcladas (no son todas "
    "decimales): no puedo decidir el formato sin adivinar y produciría valores "
    "equivocados. Re-exporta el CSV con punto decimal, o declara el formato "
    "(delimitador ';' + decimal ',')."
)


# ─────────────────────────────────────────────────────────────────────────────
# Estructuras del reporte
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SniffDetection:
    """Una dimensión detectada: valor + confianza + evidencia + descartados."""

    value: str
    confidence: str                    # "high" | "medium" | "low"
    evidence: str                      # explicación humana en español
    discarded: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "discarded": list(self.discarded),
        }


@dataclass
class SniffReport:
    """Resultado tipado del sniff físico. Viaja al frontend tal cual."""

    filename: str
    encoding: SniffDetection
    separator: SniffDetection
    decimal: SniffDetection
    preamble_lines: List[Dict[str, Any]] = field(default_factory=list)
    header_line_number: Optional[int] = None       # 1-based, línea física
    header_columns: List[str] = field(default_factory=list)
    broken_rows: List[Dict[str, Any]] = field(default_factory=list)
    broken_row_count: int = 0
    n_lines_sampled: int = 0
    sample_truncated: bool = False
    warnings: List[str] = field(default_factory=list)
    version: str = "csv_sniff_v1"

    @property
    def preamble_count(self) -> int:
        return len(self.preamble_lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "filename": self.filename,
            "encoding": self.encoding.to_dict(),
            "separator": self.separator.to_dict(),
            "decimal": self.decimal.to_dict(),
            "preamble_count": self.preamble_count,
            "preamble_lines": list(self.preamble_lines),
            "header_line_number": self.header_line_number,
            "header_columns": list(self.header_columns),
            "broken_rows": list(self.broken_rows),
            "broken_row_count": self.broken_row_count,
            "n_lines_sampled": self.n_lines_sampled,
            "sample_truncated": self.sample_truncated,
            "warnings": list(self.warnings),
        }

    def import_warnings(self) -> List[str]:
        """Avisos que la INGESTA agrega a sus warnings (siempre avisar).

        Solo se emiten cuando el sniffer hizo algo no-trivial (preámbulo, filas
        rotas, encoding no-UTF-8): un CSV limpio no gana avisos nuevos, así los
        tests históricos quedan byte-idénticos.
        """
        out: List[str] = []
        if self.preamble_count:
            nums = ", ".join(str(p["line_number"]) for p in self.preamble_lines[:5])
            first = self.preamble_lines[0]["text"]
            out.append(
                f"{self.preamble_count} línea(s) de preámbulo omitidas antes del "
                f"encabezado (línea(s) {nums}; p.ej. «{first}»). Verifica que no "
                "fueran datos."
            )
        if self.broken_row_count:
            nums = ", ".join(str(b["line_number"]) for b in self.broken_rows[:5])
            out.append(
                f"{self.broken_row_count} fila(s) con número de campos inconsistente "
                f"(línea(s) {nums}{'…' if self.broken_row_count > 5 else ''}): se "
                "omiten o completan vacías según el caso; revisa esas líneas en el "
                "archivo original."
            )
        out.extend(self.warnings)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 1. Encoding: UTF-8/BOM → UTF-16(BOM) → charset-normalizer → cp1252 → latin-1
# ─────────────────────────────────────────────────────────────────────────────
def detect_encoding(raw: bytes) -> SniffDetection:
    discarded: List[Dict[str, str]] = []
    if raw.startswith(codecs.BOM_UTF8):
        return SniffDetection("utf-8-sig", "high", "BOM UTF-8 presente al inicio del archivo.")
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        # Export "Texto Unicode" de Excel: UTF-16 con BOM.
        return SniffDetection("utf-16", "high", "BOM UTF-16 presente (export 'Texto Unicode' de Excel).")
    try:
        raw.decode("utf-8")
        return SniffDetection(
            "utf-8-sig", "high", "El contenido decodifica como UTF-8 sin errores."
        )
    except UnicodeDecodeError as exc:
        discarded.append({
            "value": "utf-8",
            "reason": f"byte inválido en la posición {exc.start} (0x{raw[exc.start]:02x})",
        })

    # Refinamiento opcional con charset-normalizer (ya presente en el entorno).
    try:
        from charset_normalizer import from_bytes  # type: ignore

        best = from_bytes(raw).best()
        if best is not None:
            enc = (best.encoding or "").lower().replace("_", "-")
            if enc in ("cp1252", "windows-1252", "iso-8859-1", "latin-1", "cp1250", "iso8859-1"):
                return SniffDetection(
                    "cp1252", "medium",
                    f"charset-normalizer identifica {best.encoding}; se lee como cp1252 "
                    "(ANSI de Windows/Excel-ES, superconjunto de latin-1).",
                    discarded,
                )
            if enc in ("utf-16", "utf-16-le", "utf-16-be"):
                return SniffDetection("utf-16", "medium", "charset-normalizer identifica UTF-16.", discarded)
    except Exception:  # noqa: BLE001 — el refinamiento jamás bloquea la cadena base
        pass

    try:
        raw.decode("cp1252")
        return SniffDetection(
            "cp1252", "medium",
            "No es UTF-8; decodifica como cp1252 (ANSI de Windows, el encoding "
            "típico de Excel en español).",
            discarded,
        )
    except UnicodeDecodeError:
        discarded.append({"value": "cp1252", "reason": "bytes no definidos en cp1252 (0x81/0x8d/0x8f/0x90/0x9d)"})
    return SniffDetection(
        "latin-1", "low",
        "No es UTF-8 ni cp1252; se lee como latin-1 (nunca falla, pero los "
        "acentos pueden salir mal — verifica los nombres de estación).",
        discarded,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Separador por consistencia modal
# ─────────────────────────────────────────────────────────────────────────────
def _mode(values: List[int]) -> int:
    return max(set(values), key=values.count)


def detect_separator(lines: List[str]) -> Tuple[SniffDetection, Optional[str]]:
    """Elige separador por CONSISTENCIA modal: un delimitador real aparece el
    mismo número de veces en ≥80% de las líneas (tolera preámbulo/filas rotas).

    Devuelve (detección, separador_efectivo|None). None = sin delimitadores
    (archivo de una columna).
    """
    considered = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    if not considered:
        return SniffDetection(",", "low", "Archivo sin líneas de datos analizables."), None

    stats: Dict[str, Tuple[float, int, int]] = {}   # sep → (consistencia, moda, total)
    for cand in _SEPARATOR_CANDIDATES:
        counts = [l.count(cand) for l in considered]
        positive = [c for c in counts if c > 0]
        if not positive:
            continue
        mode = _mode(positive)
        consistency = sum(1 for c in counts if c == mode) / len(considered)
        stats[cand] = (consistency, mode, sum(counts))

    if not stats:
        return SniffDetection(
            ",", "low",
            "No se encontró ningún delimitador (',', ';', tab, '|'): el archivo "
            "parece tener UNA sola columna.",
        ), None

    # Consistentes primero; desempate por prioridad de _SEPARATOR_CANDIDATES
    # (';' antes que ',': en Excel-ES la coma decimal también es consistente).
    consistent = [s for s in _SEPARATOR_CANDIDATES if s in stats and stats[s][0] >= 0.8]
    if consistent:
        winner = consistent[0]
        consistency, mode, _total = stats[winner]
        confidence = "high" if consistency >= 0.95 else "medium"
        discarded = [
            {
                "value": _SEPARATOR_LABELS[s],
                "reason": (
                    f"aparece pero sin consistencia de delimitador "
                    f"(consistencia {stats[s][0]:.0%})"
                    if stats[s][0] < 0.8
                    else "consistente, pero interpretado como decimal/texto (gana el de mayor prioridad)"
                ),
            }
            for s in stats if s != winner
        ]
        return SniffDetection(
            winner, confidence,
            f"{_SEPARATOR_LABELS[winner]} aparece {mode} vez/veces por línea en "
            f"{consistency:.0%} de las líneas analizadas.",
            discarded,
        ), winner

    # Nada consistente: reportar el dominante con confianza baja (la ingesta
    # decidirá con su propia lógica o fallará con error claro).
    winner = max(stats, key=lambda s: (stats[s][0], stats[s][2]))
    consistency, mode, _total = stats[winner]
    return SniffDetection(
        winner, "low",
        f"Ningún delimitador es consistente (mejor candidato: "
        f"{_SEPARATOR_LABELS[winner]} con consistencia {consistency:.0%}). "
        "El archivo puede tener filas rotas o formato mixto.",
        [{"value": _SEPARATOR_LABELS[s], "reason": f"consistencia {stats[s][0]:.0%}"}
         for s in stats if s != winner],
    ), winner


# ─────────────────────────────────────────────────────────────────────────────
# 3. Decimal ('.' vs ',') — generalización de _detect_semicolon_decimal_comma
# ─────────────────────────────────────────────────────────────────────────────
def decimal_verdict_for_lines(lines: List[str], sep: str) -> str:
    """Veredicto del decimal para un separador dado.

    Generaliza `_detect_semicolon_decimal_comma` (gravity_import_service, bug
    e7d2858) a cualquier separador no-coma. Devuelve:
      - "point":  decimal '.' (sin comas dentro de los campos).
      - "comma":  decimal ',' (todas las comas son decimales — Excel-ES).
      - "ambiguous": comas de miles (1,234,567) o de texto mezcladas → NO adivinar.
    """
    if sep == ",":
        return "point"   # la coma ES el separador; el decimal solo puede ser '.'
    data_lines = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    total_comma = 0
    decimal_comma = 0
    for line in data_lines:
        for fld in line.split(sep):
            ncomma = fld.count(",")
            if ncomma == 0:
                continue
            total_comma += ncomma
            if ncomma >= 2:
                return "ambiguous"   # separador de miles: no adivinar
            # Coma decimal = coma pegada a dígito por la derecha, con dígito,
            # signo, espacio o inicio a la izquierda (",05" / "-,1396" válidos).
            if re.search(r"(?:^|[\d\s+\-]),\d", fld):
                decimal_comma += 1
    if total_comma == 0:
        return "point"
    return "comma" if decimal_comma == total_comma else "ambiguous"


def _decimal_detection(verdict: str, sep: str) -> SniffDetection:
    if verdict == "comma":
        return SniffDetection(
            ",", "high",
            "Todas las comas dentro de los campos son decimales (formato "
            "Excel-ES: separador ';' + coma decimal).",
            [{"value": ".", "reason": "los campos numéricos no usan punto decimal"}],
        )
    if verdict == "ambiguous":
        return SniffDetection(
            "?", "low",
            "Comas mezcladas dentro de los campos (¿separador de miles o texto "
            "con comas?): no se puede decidir el decimal sin adivinar.",
            [
                {"value": ".", "reason": "hay comas dentro de campos numéricos"},
                {"value": ",", "reason": "no todas las comas son decimales"},
            ],
        )
    if sep == ",":
        return SniffDetection(
            ".", "high",
            "El separador es ',': el decimal solo puede ser '.' (formato inglés).",
        )
    return SniffDetection(
        ".", "high",
        "Sin comas dentro de los campos: decimal '.' estándar.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Preámbulo + encabezado + filas rotas
# ─────────────────────────────────────────────────────────────────────────────
def _split_fields(line: str, sep: Optional[str]) -> List[str]:
    if sep is None:
        return [line]
    return line.split(sep)


def _is_number(token: str) -> bool:
    t = token.strip()
    if not t:
        return False
    for cand in (t, t.replace(",", ".", 1)):
        try:
            float(cand)
            return True
        except ValueError:
            continue
    return False


def _looks_like_header(fields: List[str]) -> bool:
    """Un encabezado real: campos mayormente no-vacíos y NO todos numéricos."""
    non_empty = [f for f in fields if f.strip()]
    if len(fields) == 0 or len(non_empty) / len(fields) < 0.8:
        return False
    return not all(_is_number(f) for f in non_empty)


def detect_preamble_and_header(
    numbered_lines: List[Tuple[int, str]], sep: Optional[str]
) -> Tuple[List[Dict[str, Any]], Optional[int], List[str], List[Dict[str, Any]], int]:
    """Detecta preámbulo (líneas antes del encabezado real) y filas rotas.

    `numbered_lines` = [(nº_línea_física_1based, texto_sin_salto), ...] de la
    muestra COMPLETA (incluye vacías para que los números de línea sean reales).

    Encabezado = primera línea no-'#' cuyo número de campos coincide con la MODA
    de las líneas de datos, con ≥80% de campos no vacíos y no-todo-numérica.
    Las líneas anteriores (metadatos de proyecto, directivas '#') = preámbulo.

    Filas rotas = líneas post-encabezado con número de campos ≠ moda (se
    reportan con número de línea físico; máx _MAX_BROKEN_REPORTED listadas).
    """
    non_blank = [(n, t) for n, t in numbered_lines if t.strip()]
    if not non_blank:
        return [], None, [], [], 0

    body = [(n, t) for n, t in non_blank if not t.lstrip().startswith("#")]
    hash_lines = [(n, t) for n, t in non_blank if t.lstrip().startswith("#")]
    if not body:
        preamble = [
            {"line_number": n, "text": t[:_EXCERPT_CHARS], "reason": "directiva '#'"}
            for n, t in hash_lines
        ]
        return preamble, None, [], [], 0

    field_counts = [len(_split_fields(t, sep)) for _, t in body]
    modal_count = _mode(field_counts)

    header_idx: Optional[int] = None
    for i, (n, t) in enumerate(body[:_MAX_PREAMBLE_SCAN]):
        fields = _split_fields(t, sep)
        if len(fields) == modal_count and _looks_like_header(fields):
            header_idx = i
            break
    if header_idx is None:
        # Sin encabezado reconocible en el escaneo → comportamiento histórico:
        # la primera línea es el encabezado, sin preámbulo.
        header_idx = 0

    header_line_number, header_text = body[header_idx]
    header_columns = [f.strip() for f in _split_fields(header_text, sep)]

    preamble: List[Dict[str, Any]] = []
    for n, t in hash_lines:
        if n < header_line_number:
            preamble.append({"line_number": n, "text": t[:_EXCERPT_CHARS], "reason": "directiva '#'"})
    for n, t in body[:header_idx]:
        preamble.append({
            "line_number": n,
            "text": t[:_EXCERPT_CHARS],
            "reason": "no coincide con la estructura de datos (campos vacíos o texto libre)",
        })
    preamble.sort(key=lambda p: p["line_number"])

    broken: List[Dict[str, Any]] = []
    broken_total = 0
    for n, t in body[header_idx + 1:]:
        n_fields = len(_split_fields(t, sep))
        if n_fields != modal_count:
            broken_total += 1
            if len(broken) < _MAX_BROKEN_REPORTED:
                broken.append({
                    "line_number": n,
                    "field_count": n_fields,
                    "expected_fields": modal_count,
                    "excerpt": t[:_EXCERPT_CHARS],
                })

    return preamble, header_line_number, header_columns, broken, broken_total


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────
def sniff_csv(file_path: "str | Path") -> SniffReport:
    """Sniff físico completo del archivo. NUNCA lanza.

    En fallo catastrófico (archivo ilegible/vacío) devuelve un reporte de
    confianza baja con el problema en `warnings` — la capa de ingesta decide
    el error catalogado.
    """
    path = Path(file_path)
    fallback = SniffReport(
        filename=path.name,
        encoding=SniffDetection("utf-8-sig", "low", "No se pudo analizar el archivo."),
        separator=SniffDetection(",", "low", "No se pudo analizar el archivo."),
        decimal=SniffDetection(".", "low", "No se pudo analizar el archivo."),
    )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fallback.warnings.append(f"No se pudo leer el archivo para el análisis de formato: {exc}")
        return fallback

    truncated = len(raw) > _SAMPLE_BYTES
    sample = raw[:_SAMPLE_BYTES]
    if truncated:
        # No cortar una línea a la mitad: descartar el fragmento final.
        cut = max(sample.rfind(b"\n"), sample.rfind(b"\r"))
        if cut > 0:
            sample = sample[:cut]

    try:
        encoding = detect_encoding(sample if not truncated else raw[:_SAMPLE_BYTES])
        text = sample.decode(encoding.value, errors="replace")
        all_lines = text.splitlines()
        numbered = [(i + 1, l) for i, l in enumerate(all_lines[:_SAMPLE_MAX_LINES])]
        content_lines = [l for _, l in numbered if l.strip()]

        separator, sep_char = detect_separator(content_lines)
        preamble, header_n, header_cols, broken, broken_total = detect_preamble_and_header(
            numbered, sep_char
        )
        # El decimal se decide sobre las líneas de DATOS (post-preámbulo): el
        # preámbulo ("Proyecto: x, y") contaminaría el veredicto.
        data_region = [
            l for n, l in numbered
            if l.strip() and (header_n is None or n >= header_n)
        ]
        verdict = decimal_verdict_for_lines(data_region, sep_char or ",")
        decimal = _decimal_detection(verdict, sep_char or ",")

        report = SniffReport(
            filename=path.name,
            encoding=encoding,
            separator=separator,
            decimal=decimal,
            preamble_lines=preamble,
            header_line_number=header_n,
            header_columns=header_cols,
            broken_rows=broken,
            broken_row_count=broken_total,
            n_lines_sampled=len(numbered),
            sample_truncated=truncated,
        )
        if truncated:
            report.warnings.append(
                "El análisis de formato usó los primeros 256 KB del archivo "
                "(muestra representativa; el parseo completo valida el resto)."
            )
        return report
    except Exception as exc:  # noqa: BLE001 — contrato: sniff jamás crashea
        _log.warning("csv_sniff_failed", file=str(path), error=str(exc))
        fallback.warnings.append(f"El análisis de formato falló ({exc}); se usan valores por defecto.")
        return fallback
