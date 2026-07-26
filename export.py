from __future__ import annotations

import csv
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from openpyxl import Workbook

from db import EXPORT_COLUMNS


def _safe_competition(value: str) -> str:
    return (value or "Unknown").replace("/", "_").replace("\\", "_")


def _sort_key(row: Mapping[str, str]) -> tuple[int, str]:
    try:
        timestamp = int(float(row.get("betTime", "0") or 0))
    except (TypeError, ValueError):
        timestamp = 0
    return timestamp, row.get("fillHash", "")


def _write_csv(path: Path, rows: list[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in EXPORT_COLUMNS} for row in rows)


def _normalise_zip_timestamps(path: Path) -> None:
    temporary = path.with_suffix(".xlsx.tmp")
    fixed_time = (2000, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for item in sorted(source.infolist(), key=lambda entry: entry.filename):
            content = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:modified\b[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                    content,
                )
            info = zipfile.ZipInfo(item.filename, fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = item.external_attr
            info.create_system = item.create_system
            target.writestr(info, content)
    temporary.replace(path)


def _write_xlsx(path: Path, rows: list[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.properties.creator = "aimidas1"
    workbook.properties.lastModifiedBy = "aimidas1"
    workbook.properties.created = datetime(2000, 1, 1)
    workbook.properties.modified = datetime(2000, 1, 1)
    sheet = workbook.active
    sheet.title = "Sheet"
    sheet.append(EXPORT_COLUMNS)
    for row in rows:
        sheet.append([row.get(column, "") for column in EXPORT_COLUMNS])
    workbook.save(path)
    _normalise_zip_timestamps(path)


def export_trades(data_root: Path, trades: Iterable[Mapping[str, str]]) -> tuple[int, int]:
    rows = sorted(list(trades), key=_sort_key, reverse=True)
    general_dir = data_root / "todos trades"
    _write_csv(general_dir / "soccer_trades_7d.csv", rows)
    _write_xlsx(general_dir / "soccer_trades_7d.xlsx", rows)

    by_competition: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        competition = str(row.get("competition") or "Unknown")
        by_competition.setdefault(competition, []).append(row)
    for competition, competition_rows in sorted(by_competition.items()):
        directory = data_root / "ligas" / _safe_competition(competition)
        _write_csv(directory / "trades.csv", competition_rows)
        _write_xlsx(directory / "trades.xlsx", competition_rows)
    return len(rows), len(by_competition)
