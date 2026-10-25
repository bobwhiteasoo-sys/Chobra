"""CSV export that never lets a spreadsheet execute a cell (spec section 19).

Rule: a text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is
prefixed with a single quote. Numbers are written as numbers and are not changed.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable

DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(DANGEROUS):
        return "'" + value
    return value


def to_csv(header: list[str], rows: Iterable[Iterable[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")
