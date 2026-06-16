#!/usr/bin/env python3
"""Fetch public market data and write data/dashboard-data.json.

Uses the public Yahoo Finance chart endpoint without API keys. Intended for
GitHub Actions or local execution.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "dashboard-data.json"

ASSETS = [
    {
        "name": "MSCI World",
        "symbol": "EUNL.DE",
        "yahoo_symbols": ["EUNL.DE", "IWDA.AS", "IWDA.L"],
        "currency": "EUR",
        "description": "iShares Core MSCI World UCITS ETF als handelbarer Developed-Markets-Proxy",
        "price_decimals": 2,
    },
    {
        "name": "MSCI Emerging Markets",
        "symbol": "IS3N.DE",
        "yahoo_symbols": ["IS3N.DE", "EIMI.L"],
        "currency": "EUR",
        "description": "iShares Core MSCI EM IMI UCITS ETF als Emerging-Markets-Proxy",
        "price_decimals": 2,
    },
    {
        "name": "MSCI World Small Caps",
        "symbol": "IUSN.DE",
        "yahoo_symbols": ["IUSN.DE"],
        "currency": "EUR",
        "description": "iShares MSCI World Small Cap UCITS ETF als Small-Cap-Proxy",
        "price_decimals": 3,
    },
    {
        "name": "Alphabet",
        "symbol": "GOOGL",
        "yahoo_symbols": ["GOOGL"],
        "currency": "USD",
        "description": "Alphabet Inc. Class A",
        "price_decimals": 2,
    },
    {
        "name": "Gold",
        "symbol": "GC=F",
        "yahoo_symbols": ["GC=F", "XAUUSD=X"],
        "currency": "USD/oz",
        "description": "Goldpreis, primär über Gold-Future, fallback XAU/USD",
        "price_decimals": 2,
    },
]


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarketPulseDashboard/1.0)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response was not JSON. Starts with: {text[:120]!r}") from exc


def fetch_yahoo_rows(symbol: str) -> list[dict[str, Any]]:
    encoded = quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d&includePrePost=false&events=history"
    data = fetch_json(url)

    chart = data.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Yahoo returned error for {symbol}: {error}")

    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"No chart result for {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]

    closes = quote_data.get("close") or []
    opens = quote_data.get("open") or []
    highs = quote_data.get("high") or []
    lows = quote_data.get("low") or []
    volumes = quote_data.get("volume") or []

    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append(
            {
                "date": day,
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": float(close),
                "volume": volumes[i] if i < len(volumes) else None,
            }
        )

    rows.sort(key=lambda item: item["date"])
    if len(rows) < 2:
        raise RuntimeError(f"Not enough Yahoo data for {symbol}")
    return rows


def fetch_first_working(symbols: list[str]) -> tuple[str, list[dict[str, Any]]]:
    errors = []
    for symbol in symbols:
        try:
            return symbol, fetch_yahoo_rows(symbol)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    raise RuntimeError("; ".join(errors))


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
    used_symbol, rows = fetch_first_working(asset["yahoo_symbols"])
    last = rows[-1]
    prev = rows[-2]
    latest_close = last["close"]

    return {
        "name": asset["name"],
        "symbol": used_symbol,
        "source_symbol": used_symbol,
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


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    now_vienna = now_utc.astimezone(ZoneInfo("Europe/Vienna"))
    assets = []
    errors = []

    for asset in ASSETS:
        try:
            assets.append(build_asset_payload(asset))
        except Exception as exc:
            errors.append({"symbol": asset["symbol"], "error": str(exc)})

    data = {
        "is_sample": False,
        "source": "Yahoo Finance public chart endpoint",
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

    # Do not fail the workflow just because one external source is temporarily unavailable.
    # The dashboard can still show partial data and the stored errors.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
