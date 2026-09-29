"""Fetch quotes for the user's portfolio stocks via Upstox, nsepython or Yahoo."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

import requests

from src import config
from src.fetch_gift_nifty import fetch_from_yahoo
from src.nse_instruments import SYMBOL_TO_INSTRUMENT_KEY
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


def _extract_symbol(response_key: str) -> str:
    """Recover the trading symbol from an Upstox quote response key.

    Upstox echoes each instrument back as ``"<EXCHANGE>:<TRADINGSYMBOL>"``
    (e.g. ``"NSE_EQ:HDFCBANK"``), not the ``instrument_key`` it was requested
    with, so entries are matched back to symbols by the part after the colon.

    Args:
        response_key: A key from the quotes response's ``data`` mapping.

    Returns:
        The trading symbol, upper-cased.
    """
    return response_key.rsplit(":", 1)[-1].strip().upper()


def _parse_upstox_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract price and change from one Upstox ``market-quote/quotes`` entry.

    The full-quote endpoint (unlike the cheaper LTP-only endpoint) carries
    ``net_change``, so the previous close is derived as ``last_price -
    net_change`` rather than requiring a second call.

    Args:
        entry: One instrument's entry from the response's ``data`` mapping.

    Returns:
        ``{ltp, prev_close, change_pct, source}``, or None if incomplete.
    """
    ltp = to_float(entry.get("last_price"))
    net_change = to_float(entry.get("net_change"))
    if ltp is None or net_change is None:
        return None
    prev_close = ltp - net_change
    change = pct_change(ltp, prev_close)
    if change is None:
        return None
    return {"ltp": ltp, "prev_close": round(prev_close, 2), "change_pct": change, "source": "upstox"}


def fetch_stocks_upstox(token: str, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Fetch portfolio quotes from the Upstox ``market-quote/quotes`` API.

    Only symbols present in :data:`src.nse_instruments.SYMBOL_TO_INSTRUMENT_KEY`
    can be requested; others are skipped (the caller falls back to nsepython
    or Yahoo for those). Requests are batched (comma-separated
    ``instrument_key`` values, one HTTP call per :data:`config.UPSTOX_BATCH_SIZE`
    symbols) so a full portfolio costs a single call in the common case.

    Args:
        token: Upstox Analytics Token.
        symbols: NSE symbols to fetch.

    Returns:
        ``{symbol: {ltp, prev_close, change_pct, source}}`` for the symbols
        that had both a known instrument key and a usable response; empty
        (never None) if nothing could be fetched.
    """
    known = [(symbol, SYMBOL_TO_INSTRUMENT_KEY[symbol]) for symbol in symbols if symbol in SYMBOL_TO_INSTRUMENT_KEY]
    unknown = [symbol for symbol in symbols if symbol not in SYMBOL_TO_INSTRUMENT_KEY]
    if unknown:
        logger.warning("No Upstox instrument key for %s; will try other sources", ", ".join(unknown))
    if not known:
        return {}

    quotes: dict[str, dict[str, Any]] = {}
    try:
        for start in range(0, len(known), config.UPSTOX_BATCH_SIZE):
            batch = known[start : start + config.UPSTOX_BATCH_SIZE]
            response = requests.get(
                config.UPSTOX_QUOTE_URL,
                params={"instrument_key": ",".join(key for _, key in batch)},
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            logger.debug("Upstox quotes batch (%d symbols) -> HTTP %s: %s", len(batch), response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json().get("data")
            if not isinstance(data, Mapping):
                continue
            wanted = {symbol for symbol, _ in batch}
            for response_key, entry in data.items():
                symbol = _extract_symbol(str(response_key))
                if symbol not in wanted or not isinstance(entry, Mapping):
                    continue
                quote = _parse_upstox_entry(entry)
                if quote:
                    quotes[symbol] = quote
    except Exception as exc:  # noqa: BLE001 - fall back instead of crashing
        logger.error("Upstox portfolio stock fetch failed: %s", exc)

    logger.info("Upstox: fetched %d/%d symbol(s)", len(quotes), len(known))
    return quotes


def _nse_quote(nse_eq: Callable[[str], Any], symbol: str, today: date) -> dict[str, Any] | None:
    """Fetch one symbol via ``nsepython.nse_eq``; None if NSE returned nothing usable."""
    try:
        payload = nse_eq(symbol)
        logger.debug("nse_eq(%s) -> %s", symbol, str(payload)[:500])
        return parse_quote(payload, today) if isinstance(payload, Mapping) else None
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the rest
        logger.error("nse_eq(%s) failed: %s", symbol, exc)
        return None


def fetch_stocks(
    symbols: Sequence[str], deadline: float | None = None, upstox_token: str | None = None
) -> dict[str, dict[str, Any]] | None:
    """Fetch quotes for each portfolio symbol.

    Tries Upstox first (one batched call, only for symbols with a known
    instrument key; see :mod:`src.nse_instruments`) when ``upstox_token`` is
    set. Remaining symbols fall back to ``nsepython.nse_eq``, then to the
    Yahoo Finance ``SYMBOL.NS`` endpoint, one at a time with a pause between
    calls. NSE's ``quote-equity`` API often answers 403 (especially from
    cloud IPs); if the first symbol gets no data, the rest go straight to
    Yahoo to save time.

    Args:
        symbols: NSE symbols, e.g. ``["RELIANCE", "TCS"]``.
        deadline: ``time.monotonic()`` value after which no new symbols are
            fetched; the quotes gathered so far are returned.
        upstox_token: Upstox Analytics Token; if empty, Upstox is skipped.

    Returns:
        ``{symbol: {ltp, prev_close, change_pct, source}}`` for the symbols
        that succeeded, or None if none did.
    """
    try:
        quotes: dict[str, dict[str, Any]] = fetch_stocks_upstox(upstox_token, symbols) if upstox_token else {}
        remaining = [symbol for symbol in symbols if symbol not in quotes]
        if not remaining:
            logger.info("Fetched quotes for %d/%d symbols", len(quotes), len(symbols))
            return quotes or None

        nse_eq: Callable[[str], Any] | None
        try:
            from nsepython import nse_eq
        except Exception as exc:  # noqa: BLE001
            logger.error("nsepython unavailable (%s); using Yahoo Finance for stocks", exc)
            nse_eq = None

        today = datetime.now(config.IST).date()
        got_any_nse = False
        for index, symbol in enumerate(remaining):
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("Stock time budget used up; skipped %s", ", ".join(remaining[index:]))
                break
            if index:
                time.sleep(config.STOCK_CALL_DELAY_SECONDS)

            quote = _nse_quote(nse_eq, symbol, today) if nse_eq else None
            if quote is None and nse_eq and not got_any_nse:
                logger.warning("nsepython.nse_eq returned no data; using Yahoo Finance for remaining stocks")
                nse_eq = None
            if quote:
                got_any_nse = True
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
