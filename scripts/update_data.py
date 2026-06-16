#!/usr/bin/env python3
"""Fetch public market data from Stooq and write data/dashboard-data.json.

No API key required. Intended for GitHub Actions or local execution.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "dashboard-data.json"

ASSETS = [
    {
        "name": "MSCI World",
        "symbol": "IWDA.UK",
        "stooq_symbol": "iwda.uk",
        "currency": "USD",
        "description": "iShares Core MSCI World UCITS ETF als handelbarer Developed-Markets-Proxy",
        "price_decimals": 2,
    },
    {
        "name": "MSCI Emerging Markets",
        "symbol": "EIMI.UK",
        "stooq_symbol": "eimi.uk",
        "currency": "USD",
        "description": "iShares Core MSCI EM IMI UCITS ETF als Emerging-Markets-Proxy",
        "price_decimals": 2,
    },
    {
        "name": "MSCI World Small Caps",
        "symbol": "IUSN.DE",
        "stooq_symbol": "iusn.de",
        "currency": "EUR",
        "description": "iShares MSCI World Small Cap UCITS ETF als Small-Cap-Proxy",
        "price_decimals": 3,
    },
    {
        "name": "Alphabet",
        "symbol": "GOOGL.US",
        "stooq_symbol": "googl.us",
        "currency": "USD",
        "description": "Alphabet Inc. Class A",
        "price_decimals": 2,
    },
    {
        "name": "Gold",
        "symbol": "XAUUSD",
        "stooq_symbol": "xauusd",
        "currency": "USD/oz",
        "description": "Gold Spotpreis gegen US-Dollar",
        "price_decimals": 2,
    },
]


def fetch_stooq_csv(symbol: str) -> list[dict[str, Any]]:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    request = Request(url, headers={"User-Agent": "market-pulse-dashboard/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError) as exc:
        raise RuntimeError(f"Could not fetch {symbol}: {exc}") from exc

    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        try:
            if not row.get("Date") or row.get("Close") in (None, "", "N/D"):
                continue
            rows.append(
                {
                    "date": row["Date"],
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": None if not row.get("Volume") or row.get("Volume") == "N/D" else float(row["Volume"]),
                }
            )
        except (ValueError, TypeError, KeyError):
            continue

    rows.sort(key=lambda item: item["date"])
    if len(rows) < 2:
        raise RuntimeError(f"Not enough data for {symbol}. Response starts with: {text[:120]!r}")
    return rows


def pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round(((current / previous) - 1.0) * 100.0, 2)


def close_n_days_back(rows: list[dict[str, Any]], trading_days: int) -> float | None:
    idx = len(rows) - trading_days - 1
    if idx < 0:
        return None
    return rows[idx]["close"]


def ytd_base(rows: list[dict[str, Any]]) -> float | None:
    last_year = rows[-1]["date"][:4]
    prior_rows = [r for r in rows if r["date"][:4] < last_year]
    if prior_rows:
        return prior_rows[-1]["close"]
    current_year_rows = [r for r in rows if r["date"][:4] == last_year]
    if current_year_rows:
        return current_year_rows[0]["close"]
    return None


def annualized_volatility(rows: list[dict[str, Any]], days: int = 30) -> float | None:
    recent = rows[-(days + 1) :]
    if len(recent) < 3:
        return None
    returns = []
    for prev, curr in zip(recent, recent[1:]):
        if prev["close"]:
            returns.append((curr["close"] / prev["close"]) - 1.0)
    if len(returns) < 2:
        return None
    return round(statistics.stdev(returns) * math.sqrt(252) * 100.0, 2)


def build_asset_payload(asset: dict[str, Any]) -> dict[str, Any]:
    rows = fetch_stooq_csv(asset["stooq_symbol"])
    last = rows[-1]
    prev = rows[-2]
    latest_close = last["close"]

    payload = {
        "name": asset["name"],
        "symbol": asset["symbol"],
        "source_symbol": asset["stooq_symbol"],
        "currency": asset["currency"],
        "description": asset["description"],
        "price_decimals": asset["price_decimals"],
        "last_date": last["date"],
        "last_close": latest_close,
        "previous_close": prev["close"],
        "change_abs": round(latest_close - prev["close"], asset["price_decimals"]),
        "change_pct": pct(latest_close, prev["close"]),
        "change_5d_pct": pct(latest_close, close_n_days_back(rows, 5)),
        "change_1m_pct": pct(latest_close, close_n_days_back(rows, 21)),
        "change_3m_pct": pct(latest_close, close_n_days_back(rows, 63)),
        "change_1y_pct": pct(latest_close, close_n_days_back(rows, 252)),
        "ytd_pct": pct(latest_close, ytd_base(rows)),
        "volatility_30d_pct": annualized_volatility(rows, 30),
        "sparkline": [{"date": r["date"], "close": r["close"]} for r in rows[-90:]],
    }
    return payload


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    now_vienna = now_utc.astimezone(ZoneInfo("Europe/Vienna"))
    assets = []
    errors = []

    for asset in ASSETS:
        try:
            assets.append(build_asset_payload(asset))
        except Exception as exc:  # keep dashboard usable if one symbol fails
            errors.append({"symbol": asset["symbol"], "error": str(exc)})

    data = {
        "is_sample": False,
        "source": "Stooq public daily CSV",
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "generated_at_vienna": now_vienna.strftime("%d.%m.%Y, %H:%M Uhr"),
        "assets": assets,
        "errors": errors,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print("Completed with symbol errors:", errors, file=sys.stderr)
    print(f"Wrote {OUTPUT} with {len(assets)} assets")
    return 0 if assets else 1


if __name__ == "__main__":
    raise SystemExit(main())
