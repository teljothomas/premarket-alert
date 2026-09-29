"""Tests for the graded alert logic. Pure functions only; no network calls."""

from __future__ import annotations

from typing import Any

import pytest

from src import config
from src.evaluate import GREEN, RED, YELLOW, evaluate_alert


@pytest.fixture
def neutral_gift() -> dict[str, Any]:
    return {"ltp": 24_520.0, "prev_close": 24_500.0, "change_pct": 0.08, "source": "upstox"}


@pytest.fixture
def mild_gift() -> dict[str, Any]:
    return {"ltp": 24_328.5, "prev_close": 24_500.0, "change_pct": -0.70, "source": "upstox"}


@pytest.fixture
def severe_gift() -> dict[str, Any]:
    return {"ltp": 24_150.0, "prev_close": 24_505.3, "change_pct": -1.45, "source": "upstox"}


@pytest.fixture
def calm_vix() -> dict[str, Any]:
    return {"current": 12.9, "prev_close": 13.0, "change_pct": -0.77}


@pytest.fixture
def spiked_vix() -> dict[str, Any]:
    return {"current": 14.2, "prev_close": 12.76, "change_pct": 11.3}


@pytest.fixture
def neutral_fii() -> dict[str, Any]:
    return {"date": "28-Sep-2026", "fii_net": 250.0, "dii_net": 800.0}


@pytest.fixture
def selling_fii() -> dict[str, Any]:
    return {"date": "28-Sep-2026", "fii_net": -2_340.0, "dii_net": 1_900.0}


@pytest.fixture
def neutral_stocks() -> dict[str, dict[str, Any]]:
    return {
        "RELIANCE": {"ltp": 1_200.0, "prev_close": 1_195.0, "change_pct": 0.42},
        "TCS": {"ltp": 3_010.0, "prev_close": 3_020.0, "change_pct": -0.33},
    }


@pytest.fixture
def weak_stocks() -> dict[str, dict[str, Any]]:
    return {
        "RELIANCE": {"ltp": 1_170.0, "prev_close": 1_195.0, "change_pct": -2.1},
        "TCS": {"ltp": 3_026.0, "prev_close": 3_020.0, "change_pct": 0.2},
    }


def test_red_when_gift_severe_and_vix_spiked(severe_gift, spiked_vix, neutral_fii, neutral_stocks) -> None:
    level, reasons = evaluate_alert(severe_gift, spiked_vix, neutral_fii, neutral_stocks)

    assert level == RED
    assert "GIFT Nifty down 1.45% (severe)" in reasons
    assert "India VIX spiked 11.3% to 14.2" in reasons


def test_red_when_gift_severe_and_fii_selling(severe_gift, calm_vix, selling_fii, neutral_stocks) -> None:
    level, reasons = evaluate_alert(severe_gift, calm_vix, selling_fii, neutral_stocks)

    assert level == RED
    assert "FII net sellers: ₹-2,340 Cr" in reasons


def test_yellow_when_only_mild_gift_drop(mild_gift, calm_vix, neutral_fii, neutral_stocks) -> None:
    assert evaluate_alert(mild_gift, calm_vix, neutral_fii, neutral_stocks) == (
        YELLOW,
        ["GIFT Nifty down 0.70% (mild)"],
    )


def test_yellow_when_single_severe_signal(severe_gift, calm_vix, neutral_fii, neutral_stocks) -> None:
    level, reasons = evaluate_alert(severe_gift, calm_vix, neutral_fii, neutral_stocks)

    assert level == YELLOW
    assert reasons == ["GIFT Nifty down 1.45% (severe)"]


def test_yellow_when_portfolio_stock_is_weak(neutral_gift, calm_vix, neutral_fii, weak_stocks) -> None:
    assert evaluate_alert(neutral_gift, calm_vix, neutral_fii, weak_stocks) == (
        YELLOW,
        ["Weak stocks: RELIANCE (-2.1%)"],
    )


def test_green_when_all_neutral(neutral_gift, calm_vix, neutral_fii, neutral_stocks) -> None:
    assert evaluate_alert(neutral_gift, calm_vix, neutral_fii, neutral_stocks) == (GREEN, [])


def test_handles_none_inputs() -> None:
    assert evaluate_alert(None, None, None, None) == (GREEN, [])


def test_handles_partial_and_malformed_inputs() -> None:
    gift = {"change_pct": None, "source": "upstox"}
    vix: dict[str, Any] = {}
    fii = {"fii_net": "n/a"}
    stocks = {"RELIANCE": None, "TCS": {"change_pct": None}, "INFY": "garbage"}

    assert evaluate_alert(gift, vix, fii, stocks) == (GREEN, [])  # type: ignore[arg-type]


def test_none_sources_do_not_mask_other_signals(severe_gift, spiked_vix) -> None:
    level, _ = evaluate_alert(severe_gift, spiked_vix, None, None)

    assert level == RED


def test_numeric_strings_are_parsed(severe_gift) -> None:
    level, reasons = evaluate_alert(severe_gift, None, {"fii_net": "-2,340.50"}, None)

    assert level == RED
    assert "FII net sellers: ₹-2,340 Cr" in reasons


def test_yahoo_proxy_is_labelled(severe_gift) -> None:
    proxy = {**severe_gift, "source": "yahoo:^NSEI"}

    _, reasons = evaluate_alert(proxy, None, None, None)

    assert reasons == ["GIFT Nifty (Nifty 50 proxy) down 1.45% (severe)"]


@pytest.mark.parametrize(
    ("change_pct", "expected_level"),
    [
        (config.GIFT_NIFTY_SEVERE_THRESHOLD, YELLOW),  # severe, but alone -> YELLOW
        (config.GIFT_NIFTY_MILD_THRESHOLD, YELLOW),  # boundary counts as mild
        (config.GIFT_NIFTY_MILD_THRESHOLD + 0.01, GREEN),
    ],
)
def test_gift_threshold_boundaries(change_pct: float, expected_level: str) -> None:
    level, _ = evaluate_alert({"change_pct": change_pct}, None, None, None)

    assert level == expected_level


def test_boundaries_for_severe_signals() -> None:
    at_severe_gift = {"change_pct": config.GIFT_NIFTY_SEVERE_THRESHOLD}
    at_vix_spike = {"current": 15.0, "change_pct": config.VIX_SPIKE_THRESHOLD}
    at_fii_threshold = {"fii_net": config.FII_SELLING_THRESHOLD}

    assert evaluate_alert(at_severe_gift, at_vix_spike, None, None)[0] == RED  # both inclusive
    assert evaluate_alert(at_severe_gift, None, at_fii_threshold, None)[0] == YELLOW  # FII is strict <
