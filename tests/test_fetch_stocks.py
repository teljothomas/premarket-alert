"""Tests for portfolio stock fetching. Network calls are monkeypatched."""

from __future__ import annotations

from typing import Any

import pytest

from src.fetch_stocks import _extract_symbol, _parse_upstox_entry, fetch_stocks, fetch_stocks_upstox


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def test_extract_symbol_strips_exchange_prefix() -> None:
    assert _extract_symbol("NSE_EQ:HDFCBANK") == "HDFCBANK"
    assert _extract_symbol("HDFCBANK") == "HDFCBANK"  # no colon: whole thing is the symbol


def test_parse_upstox_entry_derives_prev_close_from_net_change() -> None:
    quote = _parse_upstox_entry({"last_price": 719.05, "net_change": -8.15})
    assert quote == {"ltp": 719.05, "prev_close": 727.2, "change_pct": -1.12, "source": "upstox"}


@pytest.mark.parametrize("entry", [{"last_price": 719.05}, {"net_change": -8.15}, {}])
def test_parse_upstox_entry_none_when_incomplete(entry: dict[str, Any]) -> None:
    assert _parse_upstox_entry(entry) is None


def test_fetch_stocks_upstox_matches_entries_back_to_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "NSE_EQ:HDFCBANK": {"last_price": 719.05, "net_change": -8.15},
            "NSE_EQ:RELIANCE": {"last_price": 2_945.0, "net_change": 12.0},
        }
    }
    monkeypatch.setattr("src.fetch_stocks.requests.get", lambda *a, **k: _FakeResponse(payload))

    quotes = fetch_stocks_upstox("token", ["HDFCBANK", "RELIANCE"])

    assert set(quotes) == {"HDFCBANK", "RELIANCE"}
    assert quotes["HDFCBANK"]["source"] == "upstox"


def test_fetch_stocks_upstox_skips_symbols_without_instrument_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("src.fetch_stocks.requests.get", lambda *a, **k: calls.append(k) or _FakeResponse({"data": {}}))

    quotes = fetch_stocks_upstox("token", ["NOT_A_REAL_SYMBOL"])

    assert quotes == {}
    assert calls == []  # no HTTP call made when nothing is mapped


def test_fetch_stocks_upstox_returns_empty_on_request_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr("src.fetch_stocks.requests.get", raise_error)

    assert fetch_stocks_upstox("token", ["RELIANCE"]) == {}


def test_fetch_stocks_falls_back_to_yahoo_for_unmapped_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Upstox token, nsepython unavailable: every symbol should go to the Yahoo fallback."""

    def _no_nsepython(_symbol: str) -> Any:
        raise RuntimeError("no network in tests")

    monkeypatch.setattr("nsepython.nse_eq", _no_nsepython)
    monkeypatch.setattr("src.fetch_stocks.fetch_from_yahoo", lambda ticker: {"ltp": 1.0, "prev_close": 1.0, "change_pct": 0.0, "source": ticker})

    quotes = fetch_stocks(["RELIANCE", "TCS"])

    assert quotes == {
        "RELIANCE": {"ltp": 1.0, "prev_close": 1.0, "change_pct": 0.0, "source": "RELIANCE.NS"},
        "TCS": {"ltp": 1.0, "prev_close": 1.0, "change_pct": 0.0, "source": "TCS.NS"},
    }


def test_fetch_stocks_uses_upstox_first_and_yahoo_for_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.fetch_stocks.fetch_stocks_upstox", lambda token, symbols: {"RELIANCE": {"ltp": 1.0, "prev_close": 1.0, "change_pct": 0.0, "source": "upstox"}}
    )
    monkeypatch.setattr("src.fetch_stocks.fetch_from_yahoo", lambda ticker: {"ltp": 2.0, "prev_close": 2.0, "change_pct": 0.0, "source": ticker})

    quotes = fetch_stocks(["RELIANCE", "UNMAPPEDSTOCK"], upstox_token="token")

    assert quotes is not None
    assert quotes["RELIANCE"]["source"] == "upstox"
    assert quotes["UNMAPPEDSTOCK"]["source"] == "UNMAPPEDSTOCK.NS"
