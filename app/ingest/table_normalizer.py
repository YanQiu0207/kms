from __future__ import annotations

import re
from dataclasses import dataclass

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


@dataclass(slots=True)
class TableNormalizationResult:
    text: str
    table_count: int
    row_count: int


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_cells(line)
    return bool(cells) and all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def _is_table_row(line: str) -> bool:
    return bool(_TABLE_ROW_RE.match(line))


def normalize_markdown_tables(text: str) -> TableNormalizationResult:
    lines = text.split("\n")
    normalized_lines: list[str] = []
    table_count = 0
    row_count = 0
    index = 0

    while index < len(lines):
        current = lines[index]
        if (
            index + 1 < len(lines)
            and _is_table_row(current)
            and _is_table_separator(lines[index + 1])
        ):
            headers = _split_table_cells(current)
            index += 2
            table_rows: list[list[str]] = []
            while index < len(lines) and _is_table_row(lines[index]):
                table_rows.append(_split_table_cells(lines[index]))
                index += 1

            if not table_rows:
                normalized_lines.append(current)
                normalized_lines.append(lines[index - 1])
                continue

            normalized_lines.append(f"表格列: {' | '.join(headers)}")
            for row in table_rows:
                pairs: list[str] = []
                for header_index, header in enumerate(headers):
                    if not header:
                        continue
                    value = row[header_index] if header_index < len(row) else ""
                    if not value:
                        continue
                    pairs.append(f"{header}是 {value}")
                normalized_lines.append(f"表格行: {'；'.join(pairs)}" if pairs else "表格行:")

            table_count += 1
            row_count += len(table_rows)
            continue

        normalized_lines.append(current)
        index += 1

    return TableNormalizationResult(
        text="\n".join(normalized_lines),
        table_count=table_count,
        row_count=row_count,
    )
