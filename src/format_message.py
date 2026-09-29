"""Build the WhatsApp alert text (WhatsApp *bold* / _italic_ markup, not Markdown)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src import config
from src.utils import gift_label, to_float

LEVEL_EMOJI = {"RED": "🔴", "YELLOW": "🟡"}

SUGGESTED_ACTIONS = {
    "RED": [
        "Consider reducing 30–50% exposure AFTER 9:30 AM",
        "IF price stays below VWAP.",
        "❌ Do NOT sell everything at 9:15 open.",
    ],
    "YELLOW": [
        "Monitor closely. Wait 15–30 min after open",
        "before deciding anything.",
        "No need to act at the 9:15 open.",
    ],
}

DISCLAIMER = "_This is an alert, not financial advice._"


def _num(data: Any, key: str) -> float | None:
    """Read a numeric field from a possibly-missing dict."""
    return to_float(data.get(key)) if isinstance(data, Mapping) else None


def _timestamp(now: datetime | None) -> str:
    """Format ``now`` (default: current time) as ``29-Sep-2026 08:45 IST``."""
    moment = (now or datetime.now(config.IST)).astimezone(config.IST)
    return moment.strftime("%d-%b-%Y %H:%M") + " IST"


def _gift_line(gift: Any) -> str | None:
    ltp = _num(gift, "ltp")
    if ltp is None:
        return None
    change = _num(gift, "change_pct")
    emoji = "📉" if change is not None and change < 0 else "📈"
    change_text = f" ({change:+.2f}%)" if change is not None else ""
    return f"{emoji} {gift_label(gift)}: {ltp:,.0f}{change_text}"


def _vix_line(vix: Any) -> str | None:
    current = _num(vix, "current")
    if current is None:
        return None
    change = _num(vix, "change_pct")
    change_text = f" ({change:+.1f}%)" if change is not None else ""
    return f"😨 India VIX: {current:.1f}{change_text}"


def _flow_line(fii: Any, key: str, emoji: str, label: str) -> str | None:
    net = _num(fii, key)
    return f"{emoji} {label} Net: ₹{net:+,.0f} Cr".replace("₹+", "₹") if net is not None else None


def _portfolio_line(stocks: Any) -> str | None:
    if not isinstance(stocks, Mapping):
        return None
    changes = [c for c in (_num(quote, "change_pct") for quote in stocks.values()) if c is not None]
    if not changes:
        return None
    average = sum(changes) / len(changes)
    return f"📊 Portfolio ({len(changes)} stocks): avg {average:+.1f}%"


def format_message(
    level: str,
    reasons: Sequence[str],
    gift: Mapping[str, Any] | None,
    vix: Mapping[str, Any] | None,
    fii: Mapping[str, Any] | None,
    stocks: Mapping[str, Mapping[str, Any]] | None,
    now: datetime | None = None,
) -> str | None:
    """Build the WhatsApp alert message.

    Lines whose data is missing are skipped, so partial data still produces
    a readable message.

    Args:
        level: GREEN, YELLOW or RED.
        reasons: Signal descriptions from ``evaluate_alert``.
        gift: GIFT Nifty data (``ltp``, ``change_pct``, ``source``).
        vix: India VIX data (``current``, ``change_pct``).
        fii: FII/DII data (``fii_net``, ``dii_net``).
        stocks: Portfolio quotes ``{symbol: {change_pct, ...}}``.
        now: Timestamp for the header; defaults to the current IST time.

    Returns:
        The message text, or None when ``level`` is GREEN (nothing to send).
    """
    level = (level or "").upper()
    if level == "GREEN":
        return None

    lines = [f"{LEVEL_EMOJI.get(level, '⚠️')} *MARKET ALERT — {level}* ({_timestamp(now)})", ""]

    data_lines = [
        line
        for line in (
            _gift_line(gift),
            _vix_line(vix),
            _flow_line(fii, "fii_net", "🏦", "FII"),
            _flow_line(fii, "dii_net", "🏛️", "DII"),
            _portfolio_line(stocks),
        )
        if line
    ]
    if data_lines:
        lines += [*data_lines, ""]

    if reasons:
        lines.append("⚠️ *Signals detected:*")
        lines += [f"  • {reason}" for reason in reasons]
        lines.append("")

    lines.append("📋 *Suggested action:*")
    lines += SUGGESTED_ACTIONS.get(level, SUGGESTED_ACTIONS["YELLOW"])
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def format_data_failure_message(missing: Sequence[str], now: datetime | None = None) -> str:
    """Build a notice for when the primary signal could not be fetched.

    Args:
        missing: Names of the data sources that failed.
        now: Timestamp for the header; defaults to the current IST time.

    Returns:
        A short WhatsApp message asking the user to check the market manually.
    """
    failed = ", ".join(missing) if missing else "market data"
    return "\n".join(
        [
            f"⚪ *PRE-MARKET CHECK INCOMPLETE* ({_timestamp(now)})",
            "",
            f"Could not fetch: {failed}.",
            "No grade could be computed — check the market yourself before 9:15.",
            "",
            DISCLAIMER,
        ]
    )
