"""Fetch quotes for the user's portfolio stocks via nsepython."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from src import config
from src.fetch_gift_nifty import fetch_from_yahoo
from src.utils import pct_change, to_float

logger = logging.getLogger(__name__)


def _preopen_price(pre_open: Any, today: date) -> float | None:
    """Return today's pre-open equilibrium price (IEP), if NSE has published one."""
    if not isinstance(pre_open, Mapping):
        return None
    iep = to_float(pre_open.get("IEP"))
    if not iep:
        return None
    try:
        updated = datetime.strptime(str(pre_open.get("lastUpdateTime") or "").strip(), "%d-%b-%Y %H:%M:%S").date()
    except ValueError:
        return None
    return iep if updated == today else None


def parse_quote(payload: Mapping[str, Any], today: date) -> dict[str, Any] | None:
    """Extract price and change from an ``nsepython.nse_eq`` payload.

    Uses today's pre-open price (9:00-9:08 IST session) when available,
    otherwise the last traded price.

    Args:
        payload: Raw ``nse_eq`` response.
        today: Current IST date, used to ignore stale pre-open data.

    Returns:
        ``{ltp, prev_close, change_pct, source}``, or None if no price is present.
    """
    price_info = payload.get("priceInfo") or {}
    prev_close = to_float(price_info.get("previousClose"))
    iep = _preopen_price(payload.get("preOpenMarket"), today)
    if iep is not None:
        return {"ltp": iep, "prev_close": prev_close, "change_pct": pct_change(iep, prev_close), "source": "preopen"}

    ltp = to_float(price_info.get("lastPrice"))
    if ltp is None:
        return None
    change = to_float(price_info.get("pChange"))
    if change is None:
        change = pct_change(ltp, prev_close)
    else:
        change = round(change, 2)
    return {"ltp": ltp, "prev_close": prev_close, "change_pct": change, "source": "last"}


def _nse_quote(nse_eq: Callable[[str], Any], symbol: str, today: date) -> dict[str, Any] | None:
    """Fetch one symbol via ``nsepython.nse_eq``; None if NSE returned nothing usable."""
    try:
        payload = nse_eq(symbol)
        logger.debug("nse_eq(%s) -> %s", symbol, str(payload)[:500])
        return parse_quote(payload, today) if isinstance(payload, Mapping) else None
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the rest
        logger.error("nse_eq(%s) failed: %s", symbol, exc)
        return None


def fetch_stocks(symbols: Sequence[str], deadline: float | None = None) -> dict[str, dict[str, Any]] | None:
    """Fetch quotes for each portfolio symbol, pausing between calls.

    Tries ``nsepython.nse_eq`` first. NSE's ``quote-equity`` API often answers
    403 (especially from cloud IPs); if the first symbol gets no data, the rest
    go straight to the Yahoo Finance ``SYMBOL.NS`` fallback to save time.

    Args:
        symbols: NSE symbols, e.g. ``["RELIANCE", "TCS"]``.
        deadline: ``time.monotonic()`` value after which no new symbols are
            fetched; the quotes gathered so far are returned.

    Returns:
        ``{symbol: {ltp, prev_close, change_pct, source}}`` for the symbols
        that succeeded, or None if none did.
    """
    try:
        nse_eq: Callable[[str], Any] | None
        try:
            from nsepython import nse_eq
        except Exception as exc:  # noqa: BLE001
            logger.error("nsepython unavailable (%s); using Yahoo Finance for stocks", exc)
            nse_eq = None

        today = datetime.now(config.IST).date()
        quotes: dict[str, dict[str, Any]] = {}
        for index, symbol in enumerate(symbols):
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("Stock time budget used up; skipped %s", ", ".join(symbols[index:]))
                break
            if index:
                time.sleep(config.STOCK_CALL_DELAY_SECONDS)

            quote = _nse_quote(nse_eq, symbol, today) if nse_eq else None
            if quote is None and nse_eq and not quotes:
                logger.warning("nsepython.nse_eq returned no data; using Yahoo Finance for remaining stocks")
                nse_eq = None
            if quote is None:
                quote = fetch_from_yahoo(f"{symbol}.NS")
            if quote:
                quotes[symbol] = quote
            else:
                logger.warning("No quote data for %s", symbol)

        logger.info("Fetched quotes for %d/%d symbols", len(quotes), len(symbols))
        return quotes or None
    except Exception as exc:  # noqa: BLE001
        logger.error("Portfolio stock fetch failed: %s", exc)
        return None
