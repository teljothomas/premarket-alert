"""Tests for WhatsApp message formatting. Pure functions only; no network calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.config import IST
from src.format_message import format_data_failure_message, format_message

FIXED_NOW = IST.localize(datetime(2026, 9, 29, 8, 45))


@pytest.fixture
def gift() -> dict[str, Any]:
    return {"ltp": 24_150.0, "prev_close": 24_505.3, "change_pct": -1.45, "source": "upstox"}


@pytest.fixture
def vix() -> dict[str, Any]:
    return {"current": 14.2, "prev_close": 12.76, "change_pct": 11.3}


@pytest.fixture
def fii() -> dict[str, Any]:
    return {"date": "28-Sep-2026", "fii_net": -2_340.0, "dii_net": 1_900.0}


@pytest.fixture
def stocks() -> dict[str, dict[str, Any]]:
    return {
        "RELIANCE": {"ltp": 1_170.0, "prev_close": 1_195.0, "change_pct": -2.1},
        "TCS": {"ltp": 3_026.0, "prev_close": 3_020.0, "change_pct": 0.3},
    }


@pytest.fixture
def red_reasons() -> list[str]:
    return [
        "GIFT Nifty down 1.45% (severe)",
        "India VIX spiked 11.3% to 14.2",
        "Weak stocks: RELIANCE (-2.1%)",
    ]


def test_returns_none_when_green(gift, vix, fii, stocks) -> None:
    assert format_message("GREEN", [], gift, vix, fii, stocks, now=FIXED_NOW) is None


def test_red_title(gift, vix, fii, stocks, red_reasons) -> None:
    message = format_message("RED", red_reasons, gift, vix, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "MARKET ALERT — RED" in message
    assert message.startswith("🔴 *MARKET ALERT — RED* (29-Sep-2026 08:45 IST)")


def test_red_says_do_not_sell_everything(gift, vix, fii, stocks, red_reasons) -> None:
    message = format_message("RED", red_reasons, gift, vix, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "Do NOT sell everything" in message
    assert "Consider reducing 30–50% exposure AFTER 9:30 AM" in message


def test_data_and_signal_lines(gift, vix, fii, stocks, red_reasons) -> None:
    message = format_message("RED", red_reasons, gift, vix, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "📉 GIFT Nifty: 24,150 (-1.45%)" in message
    assert "😨 India VIX: 14.2 (+11.3%)" in message
    assert "🏦 FII Net: ₹-2,340 Cr" in message
    assert "🏛️ DII Net: ₹1,900 Cr" in message
    assert "📊 Portfolio (2 stocks): avg -0.9%" in message
    assert "⚠️ *Signals detected:*" in message
    assert "  • India VIX spiked 11.3% to 14.2" in message
    assert message.endswith("_This is an alert, not financial advice._")


def test_yellow_uses_softer_language(gift, fii, stocks) -> None:
    message = format_message("YELLOW", ["GIFT Nifty down 0.70% (mild)"], gift, None, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert message.startswith("🟡 *MARKET ALERT — YELLOW*")
    assert "Monitor closely. Wait 15–30 min after open" in message
    assert "Do NOT sell everything" not in message


def test_skips_vix_line_when_vix_missing(gift, fii, stocks) -> None:
    message = format_message("YELLOW", ["GIFT Nifty down 1.45% (severe)"], gift, None, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "India VIX" not in message
    assert "GIFT Nifty: 24,150" in message


def test_skips_lines_for_missing_fields() -> None:
    gift = {"change_pct": -1.4, "source": "upstox"}  # no ltp
    fii = {"dii_net": None}  # no fii_net
    stocks = {"RELIANCE": {"ltp": 1_170.0}}  # no change_pct

    message = format_message("YELLOW", ["GIFT Nifty down 1.40% (severe)"], gift, {}, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "GIFT Nifty:" not in message
    assert "India VIX" not in message
    assert "FII Net" not in message
    assert "DII Net" not in message
    assert "Portfolio (" not in message
    assert "  • GIFT Nifty down 1.40% (severe)" in message


def test_all_data_missing_still_formats() -> None:
    message = format_message("RED", [], None, None, None, None, now=FIXED_NOW)

    assert message is not None
    assert "MARKET ALERT — RED" in message
    assert "Signals detected" not in message
    assert "Do NOT sell everything" in message


def test_yahoo_proxy_is_labelled(gift) -> None:
    proxy = {**gift, "source": "yahoo:^NSEI"}

    message = format_message("YELLOW", [], proxy, None, None, None, now=FIXED_NOW)

    assert message is not None
    assert "📉 GIFT Nifty (Nifty 50 proxy): 24,150 (-1.45%)" in message


def test_uses_whatsapp_markup_not_markdown(gift, vix, fii, stocks, red_reasons) -> None:
    message = format_message("RED", red_reasons, gift, vix, fii, stocks, now=FIXED_NOW)

    assert message is not None
    assert "**" not in message
    assert "*Suggested action:*" in message


def test_data_failure_message() -> None:
    message = format_data_failure_message(["GIFT Nifty", "India VIX"], now=FIXED_NOW)

    assert message.startswith("⚪ *PRE-MARKET CHECK INCOMPLETE* (29-Sep-2026 08:45 IST)")
    assert "Could not fetch: GIFT Nifty, India VIX." in message
