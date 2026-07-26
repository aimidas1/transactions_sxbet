from __future__ import annotations

import time
from typing import Any

import requests

from config import Settings


class SXBetAPIError(RuntimeError):
    pass


def _truthy(value: object) -> bool:
    return value is True or str(value).lower() in {"1", "true", "yes"}


def _number(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _odds(odds_raw: object) -> str:
    if odds_raw in (None, ""):
        return ""
    try:
        return f"{round(int(odds_raw) / 10**20 + 1, 4):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError, OverflowError):
        return ""


def _stake(trade: dict[str, Any]) -> str:
    if trade.get("betTimeValue") not in (None, ""):
        return _number(trade["betTimeValue"])
    raw = trade.get("stake")
    try:
        return str(float(raw) / 1_000_000).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return _number(raw)


def _line(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
        return f"{numeric:g}"
    except (TypeError, ValueError):
        return str(value)


def _market_label(market: dict[str, Any], outcome_one: str, outcome_two: str) -> str:
    explicit = market.get("marketLabel") or market.get("marketTypeLabel") or market.get("label")
    if explicit:
        return str(explicit)
    joined = f"{outcome_one} {outcome_two}".lower()
    line = _line(market.get("line"))
    if "over " in joined or "under " in joined:
        return f"Under/Over ({line})" if line else "Under/Over"
    if any(token in joined for token in ("+", "-", "handicap")) and line:
        return f"Asian Handicap ({line})"
    if any(token in joined for token in ("draw", "tie", "not tie")):
        return "1X2"
    if str(market.get("type", "")) in {"1", "226"}:
        return "1X2"
    return str(market.get("group1") or market.get("type") or "")


class SXBetClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": settings.api_key,
            "User-Agent": "aimidas-sxbet-pipeline/1.0",
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: dict[str, object]) -> dict[str, Any]:
        url = f"{self.settings.api_base_url}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                response = self.session.get(url, params=params, timeout=self.settings.request_timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else min(30, 2**attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") not in (None, "success"):
                    raise SXBetAPIError(f"SXBet returned status={payload.get('status')}")
                return payload
            except (requests.RequestException, ValueError, SXBetAPIError) as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(min(30, 2**attempt))
        raise SXBetAPIError(f"GET {endpoint} failed after retries: {last_error}")

    def soccer_sport_id(self) -> int:
        payload = self._get("/sports", {})
        for sport in payload.get("data", []) or []:
            if str(sport.get("label", "")).strip().lower() == "soccer":
                return int(sport["sportId"])
        raise SXBetAPIError("Soccer was not present in /sports")

    def active_soccer_markets(self) -> dict[str, dict[str, Any]]:
        soccer_id = self.soccer_sport_id()
        markets_by_hash: dict[str, dict[str, Any]] = {}
        pagination_key: str | None = None
        seen_keys: set[str] = set()
        page = 0
        while True:
            params: dict[str, object] = {"pageSize": self.settings.market_page_size}
            if pagination_key:
                params["paginationKey"] = pagination_key
            payload = self._get("/markets/active", params)
            data = payload.get("data") or {}
            markets = data.get("markets") or []
            for market in markets:
                label = str(market.get("sportLabel", "")).strip().lower()
                try:
                    market_sport_id = int(market.get("sportId"))
                except (TypeError, ValueError):
                    market_sport_id = -1
                if label != "soccer" and market_sport_id != soccer_id:
                    continue
                market_hash = market.get("marketHash")
                if market_hash:
                    markets_by_hash[str(market_hash)] = market
            page += 1
            next_key = data.get("nextKey") or data.get("paginationKey") or payload.get("nextKey")
            if not next_key or next_key in seen_keys:
                break
            seen_keys.add(str(next_key))
            pagination_key = str(next_key)
        print(f"Active Soccer markets: {len(markets_by_hash)} across {page} pages")
        return markets_by_hash

    def trades_for_markets(self, markets: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
        hashes = list(markets)
        result: dict[str, dict[str, str]] = {}
        for start in range(0, len(hashes), self.settings.market_hash_group_size):
            group = hashes[start : start + self.settings.market_hash_group_size]
            pagination_key: str | None = None
            seen_keys: set[str] = set()
            while True:
                params: dict[str, object] = {
                    "marketHashes": ",".join(group),
                    "pageSize": self.settings.trade_page_size,
                    "tradeStatus": "SUCCESS",
                }
                if pagination_key:
                    params["paginationKey"] = pagination_key
                payload = self._get("/trades", params)
                data = payload.get("data") or {}
                for trade in data.get("trades") or []:
                    if str(trade.get("tradeStatus", "SUCCESS")).upper() != "SUCCESS":
                        continue
                    fill_hash = trade.get("fillHash")
                    if fill_hash:
                        result[str(fill_hash)] = self.normalise_trade(trade, markets.get(str(trade.get("marketHash")), {}))
                next_key = data.get("nextKey") or data.get("paginationKey") or payload.get("nextKey")
                if not next_key or next_key in seen_keys:
                    break
                seen_keys.add(str(next_key))
                pagination_key = str(next_key)
            print(f"Trades: {min(start + len(group), len(hashes))}/{len(hashes)} market hashes")
        return list(result.values())

    @staticmethod
    def normalise_trade(trade: dict[str, Any], market: dict[str, Any]) -> dict[str, str]:
        outcome_one = str(market.get("outcomeOneName") or "")
        outcome_two = str(market.get("outcomeTwoName") or "")
        if _truthy(trade.get("bettingOutcomeOne")):
            side, bet_label = "1", outcome_one
        elif _truthy(trade.get("bettingOutcomeTwo")):
            side, bet_label = "2", outcome_two
        elif _truthy(trade.get("bettingOutcomeVoid")):
            side, bet_label = "void", str(market.get("outcomeVoidName") or "")
        else:
            side = _number(trade.get("side") or trade.get("bettingOutcome"))
            bet_label = str(trade.get("bettingOutcomeLabel") or "")

        team_one = str(market.get("teamOneName") or "")
        team_two = str(market.get("teamTwoName") or "")
        game_label = str(market.get("gameLabel") or f"{team_one} vs {team_two}").strip()
        odds_raw = trade.get("odds") or trade.get("weightedAverageOdds") or ""
        return {
            "fillHash": _number(trade.get("fillHash")),
            "sportXeventId": _number(trade.get("sportXeventId") or market.get("sportXeventId")),
            "eventId": _number(trade.get("eventId") or market.get("eventId")),
            "gameLabel": game_label,
            "teamOneName": team_one,
            "teamTwoName": team_two,
            "competition": str(market.get("leagueLabel") or market.get("competition") or ""),
            "marketHash": _number(trade.get("marketHash") or market.get("marketHash")),
            "marketType": _number(market.get("type") or market.get("marketType")),
            "marketLabel": _market_label(market, outcome_one, outcome_two),
            "betLabel": bet_label,
            "side": side,
            "bettor": _number(trade.get("bettor")),
            "stake": _stake(trade),
            "odds": _odds(odds_raw),
            "oddsRaw": _number(odds_raw),
            "maker": "1" if _truthy(trade.get("maker")) else "0",
            "settled": "1" if _truthy(trade.get("settled")) else "0",
            "tradeStatus": _number(trade.get("tradeStatus") or "SUCCESS"),
            "valid": "1" if _truthy(trade.get("valid")) else "0",
            "betTime": _number(trade.get("betTime") or trade.get("betTimeValue")),
            "gameTime": _number(market.get("gameTime") or trade.get("gameTime")),
            "netReturn": _number(trade.get("netReturn")),
            "fillOrderHash": _number(trade.get("fillOrderHash")),
            "chainVersion": _number(trade.get("chainVersion") or market.get("chainVersion")),
            "baseToken": _number(trade.get("baseToken")),
            "createdAt": _number(trade.get("createdAt")),
        }
