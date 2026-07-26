from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping


DB_COLUMNS = [
    "fillHash",
    "sportXeventId",
    "eventId",
    "gameLabel",
    "teamOneName",
    "teamTwoName",
    "competition",
    "marketHash",
    "marketType",
    "marketLabel",
    "betLabel",
    "side",
    "bettor",
    "stake",
    "odds",
    "oddsRaw",
    "maker",
    "settled",
    "tradeStatus",
    "valid",
    "betTime",
    "gameTime",
    "netReturn",
    "fillOrderHash",
    "chainVersion",
    "baseToken",
    "createdAt",
]

EXPORT_COLUMNS = [
    "fillHash",
    "bettor",
    "side",
    "stake",
    "odds",
    "marketLabel",
    "betLabel",
    "competition",
    "gameLabel",
    "teamOneName",
    "teamTwoName",
    "marketHash",
    "sportXeventId",
    "maker",
    "settled",
    "tradeStatus",
    "valid",
    "betTime",
    "gameTime",
    "netReturn",
    "chainVersion",
    "baseToken",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialize(connection)
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    columns = ", ".join(f'"{column}" TEXT' for column in DB_COLUMNS)
    connection.execute(f'CREATE TABLE IF NOT EXISTS trades ({columns}, PRIMARY KEY ("fillHash"))')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_trades_competition ON trades (competition)')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_trades_bet_time ON trades (betTime)')
    connection.commit()


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def upsert_trades(connection: sqlite3.Connection, trades: Iterable[Mapping[str, object]]) -> int:
    assignments = ", ".join(f'"{column}" = excluded."{column}"' for column in DB_COLUMNS if column != "fillHash")
    placeholders = ", ".join("?" for _ in DB_COLUMNS)
    sql = (
        f'INSERT INTO trades ({", ".join(f"\"{column}\"" for column in DB_COLUMNS)}) '
        f"VALUES ({placeholders}) ON CONFLICT(\"fillHash\") DO UPDATE SET {assignments}"
    )
    values = []
    for trade in trades:
        fill_hash = _text(trade.get("fillHash"))
        if not fill_hash:
            continue
        values.append(tuple(_text(trade.get(column, "")) for column in DB_COLUMNS))
    if values:
        connection.executemany(sql, values)
        connection.commit()
    return len(values)


def count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0])


def all_trades(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        'SELECT * FROM trades ORDER BY CAST(CASE WHEN betTime = "" THEN 0 ELSE betTime END AS INTEGER) DESC, fillHash DESC'
    ).fetchall()
    return [dict(row) for row in rows]


def _row_from_export(row: Mapping[str, str]) -> dict[str, str]:
    result = {column: row.get(column, "") or "" for column in DB_COLUMNS}
    if not result["oddsRaw"] and result["odds"]:
        try:
            result["oddsRaw"] = str(int(round((float(result["odds"]) - 1) * 10**20)))
        except (TypeError, ValueError):
            pass
    return result


def import_existing_exports(connection: sqlite3.Connection, data_root: Path) -> int:
    if count(connection) > 0:
        return 0
    rows: list[dict[str, str]] = []
    for path in sorted(data_root.rglob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows.extend(_row_from_export(row) for row in csv.DictReader(handle))
    return upsert_trades(connection, rows)
