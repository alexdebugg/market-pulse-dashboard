#!/usr/bin/env python3
"""Fetch public market data/news and write data/dashboard-data.json.

The dashboard deliberately uses only public endpoints and no API keys:
- Yahoo Finance chart endpoint for daily price data
- Google News RSS search for headline context

The news layer is not a causal model. It provides plausible context and
headline links so the dashboard can explain likely drivers without pretending
that a headline definitively caused a price move.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
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
        "news_query": '("MSCI World" OR "global stocks" OR "S&P 500" OR Nasdaq OR "world stocks") (stocks OR markets OR shares)',
        "driver_hint": "Bei globalen Aktien-ETFs zählen vor allem US-Tech, Zins-/Inflationserwartungen, Unternehmensgewinne, Dollar und allgemeine Risikobereitschaft.",
    },
    {
        "name": "MSCI Emerging Markets",
        "symbol": "IS3N.DE",
        "yahoo_symbols": ["IS3N.DE", "EIMI.L"],
        "currency": "EUR",
        "description": "iShares Core MSCI EM IMI UCITS ETF als Emerging-Markets-Proxy",
        "price_decimals": 2,
        "news_query": '("emerging markets" OR China OR India) (stocks OR equities OR markets) (dollar OR rates OR economy)',
        "driver_hint": "Emerging Markets reagieren stark auf China/Asien, US-Dollar, US-Zinsen, Rohstoffe und Kapitalflüsse in Risikoanlagen.",
    },
    {
        "name": "MSCI World Small Caps",
        "symbol": "IUSN.DE",
        "yahoo_symbols": ["IUSN.DE"],
        "currency": "EUR",
        "description": "iShares MSCI World Small Cap UCITS ETF als Small-Cap-Proxy",
        "price_decimals": 3,
        "news_query": '("small caps" OR "small-cap stocks" OR "Russell 2000") (stocks OR markets OR rates OR economy)',
        "driver_hint": "Small Caps reagieren oft überproportional auf Konjunktur-, Kredit- und Zinserwartungen sowie auf Risikoappetit am Aktienmarkt.",
    },
    {
        "name": "Alphabet",
        "symbol": "GOOGL",
        "yahoo_symbols": ["GOOGL"],
        "currency": "USD",
        "description": "Alphabet Inc. Class A",
        "price_decimals": 2,
        "news_query": '(Alphabet OR Google OR GOOGL) (stock OR shares OR earnings OR AI OR antitrust OR cloud OR advertising)',
        "driver_hint": "Bei Alphabet bewegen häufig KI-/Cloud-Nachrichten, Werbemarkt, Quartalszahlen, Analystenkommentare und Regulierung/Antitrust den Kurs.",
    },
    {
        "name": "Gold",
        "symbol": "GC=F",
        "yahoo_symbols": ["GC=F", "XAUUSD=X"],
        "currency": "USD/oz",
        "description": "Goldpreis, primär über Gold-Future, fallback XAU/USD",
        "price_decimals": 2,
        "news_query": '(gold OR "gold price" OR bullion) (dollar OR yields OR Fed OR inflation OR safe-haven OR geopolitical)',
        "driver_hint": "Gold reagiert besonders auf Realzinsen, US-Dollar, Fed-Erwartungen, Inflationssorgen und Sicherheitsnachfrage.",
    },
]

KEYWORD_LABELS = {
    "Zinsen/Fed": ["fed", "rate", "rates", "yield", "yields", "zinsen", "zinssenkung", "zinserhöhung", "treasury", "bond"],
    "Inflation": ["inflation", "cpi", "verbraucherpreise", "preisauftrieb"],
    "US-Dollar": ["dollar", "usd", "greenback"],
    "KI/Tech": ["ai", "ki", "artificial intelligence", "cloud", "semiconductor", "chip", "nvidia", "tech"],
    "Regulierung": ["antitrust", "regulation", "regulator", "eu", "doj", "kartell", "wettbewerb"],
    "Konjunktur": ["economy", "growth", "recession", "jobs", "employment", "gdp", "konjunktur", "arbeitsmarkt"],
    "China/EM": ["china", "chinese", "india", "emerging", "asia", "yuan"],
    "Geopolitik/Sicherheit": ["war", "geopolitical", "safe-haven", "crisis", "conflict", "krieg", "nahost", "ukraine"],
    "Gewinne/Analysten": ["earnings", "revenue", "profit", "forecast", "guidance", "analyst", "upgrade", "downgrade", "quartal"],
}


def fetch_text(url: str, accept: str = "application/json,text/plain,*/*") -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarketPulseDashboard/2.0; +https://github.com/)",
            "Accept": accept,
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc


def fetch_json(url: str) -> dict[str, Any]:
    text = fetch_text(url, "application/json,text/plain,*/*")
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


def clean_text(value: str | None, max_len: int = 220) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def fetch_google_news(query: str, max_items: int = 4) -> list[dict[str, str]]:
    params = urlencode({"q": query, "hl": "de", "gl": "AT", "ceid": "AT:de"})
    url = f"https://news.google.com/rss/search?{params}"
    text = fetch_text(url, "application/rss+xml,application/xml,text/xml,*/*")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RuntimeError(f"RSS was not XML. Starts with: {text[:120]!r}") from exc

    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"), 140)
        link = clean_text(item.findtext("link"), 500)
        pub_date_raw = item.findtext("pubDate") or ""
        source = item.findtext("source") or "Google News"
        published = ""
        if pub_date_raw:
            try:
                dt = parsedate_to_datetime(pub_date_raw)
                published = dt.astimezone(ZoneInfo("Europe/Vienna")).strftime("%d.%m., %H:%M")
            except Exception:
                published = clean_text(pub_date_raw, 40)
        if title and link:
            items.append({"title": title, "url": link, "source": clean_text(source, 50), "published": published})
        if len(items) >= max_items:
            break
    return items


def extract_keyword_themes(headlines: list[dict[str, str]], max_themes: int = 3) -> list[str]:
    text = " ".join(h.get("title", "") for h in headlines).lower()
    themes = []
    for label, keywords in KEYWORD_LABELS.items():
        if any(keyword.lower() in text for keyword in keywords):
            themes.append(label)
    return themes[:max_themes]


def movement_sentence(asset: dict[str, Any]) -> tuple[str, str]:
    change = asset.get("change_pct")
    if change is None:
        return "seitwärts", "Es liegt keine verlässliche Tagesveränderung vor."
    abs_change = abs(change)
    if abs_change < 0.05:
        return "seitwärts", "Der Kurs liegt nahezu unverändert gegenüber dem letzten Schlusskurs."
    strength = "leicht"
    if abs_change >= 1.0:
        strength = "deutlich"
    elif abs_change >= 0.35:
        strength = "spürbar"
    direction = "gestiegen" if change > 0 else "gefallen"
    sign = "+" if change > 0 else ""
    return direction, f"Der Kurs ist heute {strength} {direction} ({sign}{change:.2f} % gegenüber dem vorherigen Schlusskurs)."


def market_mood(assets: list[dict[str, Any]]) -> str:
    valid = [a for a in assets if isinstance(a.get("change_pct"), (int, float))]
    if not valid:
        return "neutral"
    positives = len([a for a in valid if a["change_pct"] > 0])
    avg = sum(a["change_pct"] for a in valid) / len(valid)
    if avg > 0.35 and positives >= 4:
        return "risk-on"
    if avg < -0.35 and positives <= 1:
        return "risk-off"
    return "neutral"


def market_context_sentence(asset_name: str, change: float | None, mood: str) -> str:
    if mood == "risk-on":
        if asset_name == "Gold":
            return "Das Gesamtbild der Watchlist wirkt eher risk-on; Gold kann in solchen Phasen hinter Aktien zurückbleiben, außer Zinsen/Dollar oder Sicherheitsnachfrage dominieren."
        return "Das Gesamtbild der Watchlist wirkt risk-on; das unterstützt typischerweise Aktien-ETFs und wachstumsorientierte Titel."
    if mood == "risk-off":
        if asset_name == "Gold":
            return "Das Gesamtbild der Watchlist wirkt risk-off; das kann Gold stützen, wenn Anleger Sicherheit suchen."
        return "Das Gesamtbild der Watchlist wirkt risk-off; Risikoanlagen wie Aktien-ETFs stehen dann eher unter Druck."
    return "Das Gesamtbild ist gemischt; die Bewegung dürfte eher durch produktspezifische Nachrichten und einzelne Makrothemen getrieben sein."


def build_explanation(asset: dict[str, Any], asset_config: dict[str, Any], headlines: list[dict[str, str]], mood: str) -> dict[str, Any]:
    direction, move_text = movement_sentence(asset)
    themes = extract_keyword_themes(headlines)
    change = asset.get("change_pct")

    if headlines and themes:
        theme_text = ", ".join(themes)
        summary = f"Mögliche Treiber: {theme_text}. Die verlinkten Schlagzeilen liefern Kontext; die Kursbewegung wird daraus nicht sicher kausal bewiesen."
    elif headlines:
        summary = "Mögliche Treiber ergeben sich aus der aktuellen Schlagzeilenlage. Die Links dienen als Kontext, nicht als sicherer Kausalnachweis."
    else:
        summary = "Keine aktuellen Schlagzeilen gefunden; die Einordnung basiert daher nur auf Kursbewegung und typischen Markttreibern."

    bullets = [
        move_text,
        market_context_sentence(asset["name"], change, mood),
        asset_config.get("driver_hint", "Beobachte Nachrichtenlage, Makrodaten und Marktstimmung."),
    ]

    if headlines:
        titles = [h["title"] for h in headlines[:2]]
        bullets.append("Aktuelle Quellen im Blick: " + " | ".join(titles))

    confidence = "mittel" if headlines else "niedrig"
    if change is not None and abs(change) < 0.05:
        confidence = "niedrig"

    return {
        "direction": direction,
        "confidence": confidence,
        "summary": summary,
        "themes": themes,
        "bullets": bullets,
        "headlines": headlines,
    }


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

    # 1) Price data first.
    configs_by_name = {asset["name"]: asset for asset in ASSETS}
    for asset_config in ASSETS:
        try:
            assets.append(build_asset_payload(asset_config))
        except Exception as exc:
            errors.append({"symbol": asset_config["symbol"], "stage": "prices", "error": str(exc)})

    mood = market_mood(assets)

    # 2) Headline context. News errors are non-fatal.
    for asset_payload in assets:
        asset_config = configs_by_name.get(asset_payload["name"], {})
        headlines: list[dict[str, str]] = []
        try:
            headlines = fetch_google_news(asset_config.get("news_query", asset_payload["name"]), max_items=4)
        except Exception as exc:
            errors.append({"symbol": asset_payload["symbol"], "stage": "news", "error": str(exc)})
        asset_payload["explanation"] = build_explanation(asset_payload, asset_config, headlines, mood)

    data = {
        "is_sample": False,
        "source": "Yahoo Finance Kursdaten + Google News RSS Kontext",
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "generated_at_vienna": now_vienna.strftime("%d.%m.%Y, %H:%M Uhr"),
        "market_mood_internal": mood,
        "assets": assets,
        "errors": errors,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print("Completed with non-fatal errors:", errors, file=sys.stderr)
    print(f"Wrote {OUTPUT} with {len(assets)} assets and explanations")

    # Do not fail the workflow just because one external source is temporarily unavailable.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
