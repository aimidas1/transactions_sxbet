from __future__ import annotations

import argparse
import time

from config import get_settings
from db import connect, import_existing_exports, all_trades, upsert_trades
from export import export_trades
from extract import SXBetClient
from push import commit_and_push, prepare_repository


def run_once() -> bool:
    settings = get_settings(require_github=True)
    prepare_repository(settings)
    connection = connect(settings.db_path)
    try:
        imported = import_existing_exports(connection, settings.data_root)
        if imported:
            print(f"Imported {imported} existing CSV rows into SQLite")

        client = SXBetClient(settings)
        markets = client.active_soccer_markets()
        trades = client.trades_for_markets(markets)
        upserted = upsert_trades(connection, trades)
        print(f"Upserted {upserted} API trades; SQLite total={len(all_trades(connection))}")

        total, competitions = export_trades(settings.data_root, all_trades(connection))
        print(f"Exported {total} trades across {competitions} competitions")
        return commit_and_push(settings)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hourly SXBet Soccer trades pipeline")
    parser.add_argument("--once", action="store_true", help="run one complete cycle and exit")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    while True:
        started = time.monotonic()
        try:
            run_once()
        except Exception as exc:
            print(f"Pipeline cycle failed: {exc}")
        elapsed = time.monotonic() - started
        wait_seconds = max(0, 3600 - elapsed)
        print(f"Waiting {wait_seconds:.0f} seconds before the next cycle")
        time.sleep(wait_seconds)


if __name__ == "__main__":
    main()
