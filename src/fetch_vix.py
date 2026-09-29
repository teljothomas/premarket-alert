"""Fetch India VIX: live value from nsepython, previous close from nselib."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Any

from src.utils import pct_change, to_float, to_records

logger = logging.getLogger(__name__)

_DATE_FORMATS = ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%y", "%d/%m/%Y")
_CLOSE_KEYS = ("closeindexval", "eodcloseindexval", "close", "closeprice", "closingindexvalue")


def _parse_date(value: Any) -> date | None:
    """Parse a date from a pandas Timestamp, datetime, or NSE-style string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    text = str(value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _current_vix() -> float | None:
    """Live India VIX via ``nsepython.indiavix()``."""
    from nsepython import indiavix

    value = indiavix()
    logger.debug("nsepython.indiavix() -> %r", value)
    return to_float(value)


def _vix_closes() -> list[float]:
    """Daily India VIX closes for the past week, oldest first, via nselib."""
    from nselib import capital_market

    frame = capital_market.india_vix_data(period="1W")
    logger.debug("nselib india_vix_data(period='1W') ->\n%s", frame)
    rows = to_records(frame)
    if not rows:
        return []

    close_key = next((key for key in _CLOSE_KEYS if key in rows[0]), None)
    if close_key is None:
        close_key = next((key for key in rows[0] if "close" in key and "prev" not in key), None)
    date_key = next((key for key in rows[0] if "timestamp" in key or "date" in key), None)
    if close_key is None:
        raise ValueError(f"no close column in India VIX history: {sorted(rows[0])}")

    dated = [(_parse_date(row.get(date_key)) if date_key else None, to_float(row.get(close_key))) for row in rows]
    dated = [(day, close) for day, close in dated if close is not None]
    if dated and all(day is not None for day, _ in dated):
        dated.sort(key=lambda item: item[0])
    return [close for _, close in dated]


def fetch_vix() -> dict[str, Any] | None:
    """Fetch India VIX and its change versus the previous close.

    The previous close is normally the second-last row of the one-week
    history (before the open the "live" value equals the last settled close).
    If the live value differs from the last close, the market is already
    trading, so the last row is the previous close instead.

    Returns:
        ``{current, prev_close, change_pct}``, or None if no VIX value is available.
    """
    try:
        current: float | None = None
        try:
            current = _current_vix()
        except Exception as exc:  # noqa: BLE001
            logger.error("nsepython.indiavix() failed: %s", exc)

        closes: list[float] = []
        try:
            closes = _vix_closes()
        except Exception as exc:  # noqa: BLE001
            logger.error("nselib india_vix_data() failed: %s", exc)

        if current is None and closes:
            logger.warning("Live India VIX unavailable; using last settled close")
            current = closes[-1]
        if current is None:
            logger.error("India VIX unavailable")
            return None

        prev_close: float | None = None
        if len(closes) >= 2 and math.isclose(closes[-1], current, abs_tol=0.01):
            prev_close = closes[-2]
        elif closes:
            prev_close = closes[-1]

        change = pct_change(current, prev_close)
        logger.info("India VIX: current=%.2f prev_close=%s change=%s", current, prev_close, change)
        return {"current": current, "prev_close": prev_close, "change_pct": change}
    except Exception as exc:  # noqa: BLE001
        logger.error("India VIX fetch failed: %s", exc)
        return None
