"""Fetch GIFT Nifty from Upstox, falling back to Yahoo Finance Nifty 50 spot."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests

from src import config
from src.utils import pct_change, to_float

logger = logging.getLogger(__name__)

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}
_RETRY_STATUSES = {429, 500, 502, 503, 504}  # rate limited or flaky: try the next Yahoo host


def _upstox_quote(url: str, token: str, instrument_key: str) -> dict[str, Any] | None:
    """Call an Upstox market-quote endpoint and return the first instrument entry."""
    response = requests.get(
        url,
        params={"instrument_key": instrument_key},
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    logger.debug("Upstox %s -> HTTP %s: %s", url, response.status_code, response.text[:500])
    response.raise_for_status()
    data = response.json().get("data")
    # Response keys use ':' instead of '|', so take the first entry rather than
    # looking the instrument key up directly.
    if not isinstance(data, dict) or not data:
        return None
    first = next(iter(data.values()))
    return first if isinstance(first, dict) else None


def fetch_from_upstox(token: str, instrument_key: str = config.DEFAULT_GIFT_NIFTY_INSTRUMENT_KEY) -> dict[str, Any] | None:
    """Fetch GIFT Nifty from the Upstox market-quote API.

    The v2 LTP endpoint returns only ``last_price``; when it carries no
    previous close, the full-quote endpoint's ``net_change`` is used to derive it.

    Args:
        token: Upstox Analytics Token.
        instrument_key: Upstox instrument key for GIFT Nifty.

    Returns:
        ``{ltp, prev_close, change_pct, source}``, or None on any failure.
    """
    try:
        quote = _upstox_quote(config.UPSTOX_LTP_URL, token, instrument_key)
        if not quote:
            logger.warning("Upstox LTP returned no data for %s", instrument_key)
            return None
        ltp = to_float(quote.get("last_price"))
        prev_close = to_float(quote.get("cp") or quote.get("close_price") or quote.get("prev_close"))

        if prev_close is None:
            full = _upstox_quote(config.UPSTOX_QUOTE_URL, token, instrument_key) or {}
            ltp = to_float(full.get("last_price")) or ltp
            net_change = to_float(full.get("net_change"))
            if ltp is not None and net_change is not None:
                prev_close = ltp - net_change

        change = pct_change(ltp, prev_close)
        if ltp is None or prev_close is None or change is None:
            logger.warning("Upstox data incomplete for %s (ltp=%s, prev_close=%s)", instrument_key, ltp, prev_close)
            return None
        return {"ltp": ltp, "prev_close": round(prev_close, 2), "change_pct": change, "source": "upstox"}
    except Exception as exc:  # noqa: BLE001 - fall back instead of crashing
        logger.error("Upstox GIFT Nifty fetch failed: %s", exc)
        return None


def fetch_from_yahoo(ticker: str = config.YAHOO_GIFT_PROXY_TICKER) -> dict[str, Any] | None:
    """Fetch a daily quote from Yahoo Finance's chart API.

    With the default ticker (^NSEI, Nifty 50 spot) this is the GIFT Nifty
    fallback. Before the 9:15 open it reflects the previous session's move,
    so it is a weaker signal than GIFT Nifty itself. Also used for NSE stocks
    (``RELIANCE.NS``) when NSE's own API is unavailable.

    Args:
        ticker: Yahoo Finance symbol.

    Returns:
        ``{ltp, prev_close, change_pct, source}``, or None on any failure.
    """
    try:
        for host in config.YAHOO_HOSTS:
            response = requests.get(
                config.YAHOO_CHART_URL.format(host=host, ticker=quote(ticker, safe="")),
                params={"range": "5d", "interval": "1d"},
                headers=_YAHOO_HEADERS,
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            logger.debug("Yahoo %s via %s -> HTTP %s: %s", ticker, host, response.status_code, response.text[:500])
            if response.status_code not in _RETRY_STATUSES:
                break
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        meta = result.get("meta") or {}
        bars = ((result.get("indicators") or {}).get("quote") or [{}])[0]

        # One close per IST trading day; later entries for the same day win.
        closes_by_day: dict[str, float] = {}
        for stamp, raw_close in zip(result.get("timestamp") or [], bars.get("close") or []):
            close = to_float(raw_close)
            if close is not None:
                closes_by_day[datetime.fromtimestamp(stamp, config.IST).date().isoformat()] = close
        closes = [closes_by_day[day] for day in sorted(closes_by_day)]

        ltp = to_float(meta.get("regularMarketPrice")) or (closes[-1] if closes else None)
        prev_close = closes[-2] if len(closes) >= 2 else to_float(meta.get("chartPreviousClose"))
        change = pct_change(ltp, prev_close)
        if ltp is None or change is None:
            logger.warning("Yahoo %s data incomplete (ltp=%s, prev_close=%s)", ticker, ltp, prev_close)
            return None
        return {"ltp": ltp, "prev_close": prev_close, "change_pct": change, "source": f"yahoo:{ticker}"}
    except Exception as exc:  # noqa: BLE001
        logger.error("Yahoo Finance %s fetch failed: %s", ticker, exc)
        return None


def fetch_gift_nifty(
    token: str | None, instrument_key: str = config.DEFAULT_GIFT_NIFTY_INSTRUMENT_KEY
) -> dict[str, Any] | None:
    """Fetch the pre-market GIFT Nifty signal, trying Upstox first then Yahoo.

    Args:
        token: Upstox Analytics Token; if empty, Upstox is skipped.
        instrument_key: Upstox instrument key for GIFT Nifty.

    Returns:
        ``{ltp, prev_close, change_pct, source}``, or None if every source failed.
    """
    try:
        if token:
            data = fetch_from_upstox(token, instrument_key)
            if data:
                logger.info("GIFT Nifty source: Upstox (%s) %s", instrument_key, _describe(data))
                return data
            logger.warning("Upstox unavailable; falling back to Yahoo Finance ^NSEI proxy")
        else:
            logger.warning("UPSTOX_ANALYTICS_TOKEN not set; using Yahoo Finance ^NSEI proxy")

        data = fetch_from_yahoo()
        if data:
            logger.info("GIFT Nifty source: Yahoo Finance ^NSEI (Nifty 50 spot proxy) %s", _describe(data))
            return data
        logger.error("GIFT Nifty unavailable from all sources")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("GIFT Nifty fetch failed: %s", exc)
        return None


def _describe(data: dict[str, Any]) -> str:
    """Short log description of a quote."""
    return f"ltp={data['ltp']:.2f} prev_close={data['prev_close']:.2f} change={data['change_pct']:+.2f}%"
