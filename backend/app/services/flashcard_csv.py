"""CSV export for flashcard decks (NotebookLM-style download).

Columns: Front, Back, Hint, Tags, Citations. Output is UTF-8 with BOM so
Excel renders Persian correctly. Every cell goes through formula-injection
protection: values starting with ``= + - @`` (after optional whitespace) or
containing tab/CR/LF at the start are prefixed with a single quote.
"""

from __future__ import annotations

import csv
import io
from typing import Any

CSV_HEADERS: tuple[str, ...] = ("Front", "Back", "Hint", "Tags", "Citations")

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _sanitize_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection (CSV injection)."""
    text = str(value or "")
    stripped = text.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@"):
        return "'" + text
    if text[:1] in ("\t", "\r", "\n"):
        return "'" + text
    return text


def _citations_text(citations: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        label = str(citation.get("citation") or "").strip()
        if label:
            parts.append(label)
    return "; ".join(parts)


def build_csv_text(cards: list[dict[str, Any]]) -> str:
    """Build CSV text (without BOM) from ``serialize_card``-shaped dicts."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(list(CSV_HEADERS))
    for card in cards:
        tags = "; ".join(str(t) for t in (card.get("tags") or []) if str(t).strip())
        row = [
            _sanitize_cell(str(card.get("front_md") or "")),
            _sanitize_cell(str(card.get("back_md") or "")),
            _sanitize_cell(str(card.get("hint_md") or "")),
            _sanitize_cell(tags),
            _sanitize_cell(_citations_text(list(card.get("citations") or []))),
        ]
        writer.writerow(row)
    return buffer.getvalue()


def build_csv_bytes(cards: list[dict[str, Any]]) -> bytes:
    """UTF-8 BOM + CSV bytes, ready for the HTTP response body."""
    if not cards:
        raise ValueError("deck has no cards")
    text = build_csv_text(cards)
    return b"\xef\xbb\xbf" + text.encode("utf-8")


__all__ = ["CSV_HEADERS", "build_csv_bytes", "build_csv_text"]
