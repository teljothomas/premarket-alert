"""Fetch the latest FII/DII provisional cash-market activity via nselib."""

from __future__ import annotations

import logging
from typing import Any

from src.utils import to_float, to_records

logger = logging.getLogger(__name__)


def _pick(row: dict[str, Any], *words: str) -> Any:
    """Return the value of the first key in ``row`` containing all ``words``."""
    return next((value for key, value in row.items() if all(word in key for word in words)), None)


def _category_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Parse NSE's one-row-per-category layout (``FII/FPI`` and ``DII`` rows)."""
    fii = next((r for r in rows if any(t in str(r.get("category", "")).upper() for t in ("FII", "FPI"))), None)
    dii = next((r for r in rows if "DII" in str(r.get("category", "")).upper()), None)
    if fii is None and dii is None:
        return None
    fii, dii = fii or {}, dii or {}
    return {
        "date": fii.get("date") or dii.get("date"),
        "fii_buy": to_float(_pick(fii, "buy")),
        "fii_sell": to_float(_pick(fii, "sell")),
        "fii_net": to_float(_pick(fii, "net")),
        "dii_buy": to_float(_pick(dii, "buy")),
        "dii_sell": to_float(_pick(dii, "sell")),
        "dii_net": to_float(_pick(dii, "net")),
    }


def fetch_fii_dii() -> dict[str, Any] | None:
    """Fetch the most recent FII/DII trading activity (values in ₹ crore).

    NSE publishes one row per investor category for the latest session;
    both rows are merged into a single dict.

    Returns:
        ``{date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net}``,
        or None if the data is unavailable.
    """
    try:
        from nselib import capital_market

        fetch = getattr(capital_market, "fii_dii_trading_activity", None)
        if fetch is None:
            # nselib 2.5.x defines it but does not re-export it from the package.
            from nselib.capital_market.capital_market_data import fii_dii_trading_activity as fetch

        frame = fetch()
        logger.debug("nselib fii_dii_trading_activity() ->\n%s", frame)
        rows = to_records(frame)
        if not rows:
            logger.error("FII/DII data empty")
            return None

        if any("category" in row for row in rows):
            result = _category_rows(rows)
        else:
            latest = rows[-1]
            result = {
                "date": _pick(latest, "date"),
                "fii_net": to_float(_pick(latest, "fii", "net")),
                "dii_net": to_float(_pick(latest, "dii", "net")),
            }

        if not result or (result.get("fii_net") is None and result.get("dii_net") is None):
            logger.error("FII/DII data had no usable net values: %s", rows)
            return None
        logger.info("FII/DII (%s): FII net=%s Cr, DII net=%s Cr", result.get("date"), result.get("fii_net"), result.get("dii_net"))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("FII/DII fetch failed: %s", exc)
        return None
