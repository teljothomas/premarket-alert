"""Graded alert logic: turn market signals into GREEN / YELLOW / RED."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src import config
from src.utils import gift_label, to_float

GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"


def _value(data: Any, key: str) -> float | None:
    """Read a numeric field from a possibly-missing dict."""
    return to_float(data.get(key)) if isinstance(data, Mapping) else None


def _weak_stocks(stocks: Any) -> list[tuple[str, float]]:
    """Return ``(symbol, change_pct)`` for stocks below the weak threshold, weakest first."""
    if not isinstance(stocks, Mapping):
        return []
    weak = []
    for symbol, quote in stocks.items():
        change = _value(quote, "change_pct")
        if change is not None and change < config.STOCK_WEAK_THRESHOLD:
            weak.append((str(symbol), change))
    return sorted(weak, key=lambda item: item[1])


def evaluate_alert(
    gift: Mapping[str, Any] | None,
    vix: Mapping[str, Any] | None,
    fii: Mapping[str, Any] | None,
    stocks: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[str, list[str]]:
    """Grade pre-market conditions.

    Severe signals: GIFT Nifty change <= severe threshold, India VIX change >=
    spike threshold, FII net < selling threshold. Mild signals: GIFT Nifty
    change between the mild and severe thresholds, any portfolio stock below
    the weak threshold. RED needs two or more severe signals; any signal gives
    at least YELLOW. Missing data (None or absent fields) is skipped.

    Args:
        gift: ``{change_pct, source, ...}`` from ``fetch_gift_nifty``.
        vix: ``{current, change_pct, ...}`` from ``fetch_vix``.
        fii: ``{fii_net, ...}`` from ``fetch_fii_dii`` (₹ crore).
        stocks: ``{symbol: {change_pct, ...}}`` from ``fetch_stocks``.

    Returns:
        ``(level, reasons)`` where level is GREEN, YELLOW or RED and reasons
        are human-readable descriptions of each signal.
    """
    reasons: list[str] = []
    severe = 0
    mild = 0

    gift_change = _value(gift, "change_pct")
    if gift_change is not None:
        if gift_change <= config.GIFT_NIFTY_SEVERE_THRESHOLD:
            severe += 1
            reasons.append(f"{gift_label(gift)} down {abs(gift_change):.2f}% (severe)")
        elif gift_change <= config.GIFT_NIFTY_MILD_THRESHOLD:
            mild += 1
            reasons.append(f"{gift_label(gift)} down {abs(gift_change):.2f}% (mild)")

    vix_change = _value(vix, "change_pct")
    if vix_change is not None and vix_change >= config.VIX_SPIKE_THRESHOLD:
        severe += 1
        current = _value(vix, "current")
        level_text = f" to {current:.1f}" if current is not None else ""
        reasons.append(f"India VIX spiked {vix_change:.1f}%{level_text}")

    fii_net = _value(fii, "fii_net")
    if fii_net is not None and fii_net < config.FII_SELLING_THRESHOLD:
        severe += 1
        reasons.append(f"FII net sellers: ₹{fii_net:,.0f} Cr")

    weak = _weak_stocks(stocks)
    if weak:
        mild += 1
        reasons.append("Weak stocks: " + ", ".join(f"{symbol} ({change:+.1f}%)" for symbol, change in weak))

    if severe >= 2:
        return RED, reasons
    if severe or mild:
        return YELLOW, reasons
    return GREEN, reasons
