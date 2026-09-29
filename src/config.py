"""Configuration: secrets from environment variables plus tunable thresholds.

Thresholds are plain module-level constants so they are easy to find and edit.
Secrets are never hardcoded; :func:`load_settings` reads them from the
environment at runtime.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import pytz

IST = pytz.timezone("Asia/Kolkata")

# --- Alert thresholds (tune these) ------------------------------------------
GIFT_NIFTY_MILD_THRESHOLD: float = -0.5  # percent
GIFT_NIFTY_SEVERE_THRESHOLD: float = -1.2  # percent
VIX_SPIKE_THRESHOLD: float = 8  # percent change
FII_SELLING_THRESHOLD: float = -1000  # crore rupees (FII net)
STOCK_WEAK_THRESHOLD: float = -1.5  # percent

# --- Data sources -------------------------------------------------------------
DEFAULT_PORTFOLIO_STOCKS: str = "RELIANCE,TCS,HDFCBANK,INFY"
DEFAULT_GIFT_NIFTY_INSTRUMENT_KEY: str = "GLOBAL_INDEX|SGX NIFTY"
UPSTOX_LTP_URL: str = "https://api.upstox.com/v2/market-quote/ltp"
UPSTOX_QUOTE_URL: str = "https://api.upstox.com/v2/market-quote/quotes"
UPSTOX_BATCH_SIZE: int = 500  # max instrument_keys per market-quote request
YAHOO_CHART_URL: str = "https://{host}/v8/finance/chart/{ticker}"
YAHOO_HOSTS: tuple[str, ...] = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")  # retried in order
YAHOO_GIFT_PROXY_TICKER: str = "^NSEI"  # Nifty 50 spot
CALLMEBOT_URL: str = "https://api.callmebot.com/whatsapp.php"

# --- Time budget (the whole run must finish in under 90 seconds) --------------
HTTP_TIMEOUT_SECONDS: float = 8
GIFT_TIMEOUT_SECONDS: float = 20
VIX_TIMEOUT_SECONDS: float = 15
FII_TIMEOUT_SECONDS: float = 10
STOCKS_TIMEOUT_SECONDS: float = 30
STOCK_CALL_DELAY_SECONDS: float = 0.5
SEND_TIMEOUT_SECONDS: float = 10

# When GIFT Nifty (the primary signal) is unavailable from every source and no
# other signal fired, send a short "check incomplete" notice instead of staying
# silent, so a data outage is never mistaken for a GREEN day.
NOTIFY_ON_DATA_FAILURE: bool = True

_TRUTHY = {"1", "true", "yes", "y", "on"}


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables.

    Attributes:
        upstox_token: Upstox Analytics Token, or None to go straight to Yahoo.
        callmebot_api_key: CallMeBot API key (empty only in dry-run mode).
        callmebot_phone: WhatsApp number in international format.
        portfolio_stocks: NSE symbols to check.
        gift_instrument_key: Upstox instrument key used for GIFT Nifty.
        dry_run: Log the WhatsApp message instead of sending it.
        force_run: Run even on Saturday/Sunday (manual testing).
    """

    upstox_token: str | None
    callmebot_api_key: str
    callmebot_phone: str
    portfolio_stocks: tuple[str, ...]
    gift_instrument_key: str
    dry_run: bool = False
    force_run: bool = False


def is_truthy(value: str | None) -> bool:
    """Interpret an environment-variable string as a boolean flag.

    Args:
        value: Raw value such as ``"1"``, ``"true"`` or ``"no"``.

    Returns:
        True for 1/true/yes/y/on (case-insensitive), otherwise False.
    """
    return (value or "").strip().lower() in _TRUTHY


def parse_portfolio(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated list of NSE symbols.

    Args:
        raw: Value of ``PORTFOLIO_STOCKS``, e.g. ``"reliance, TCS"``. Empty or
            missing values fall back to :data:`DEFAULT_PORTFOLIO_STOCKS`.

    Returns:
        Upper-cased, de-duplicated symbols in their original order.
    """
    symbols: list[str] = []
    for source in (raw or "", DEFAULT_PORTFOLIO_STOCKS):
        for part in source.split(","):
            symbol = part.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        if symbols:
            break
    return tuple(symbols)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from environment variables.

    Args:
        env: Mapping to read from; defaults to ``os.environ``.

    Returns:
        The resolved settings.

    Raises:
        ConfigError: If ``CALLMEBOT_API_KEY`` or ``CALLMEBOT_PHONE`` is missing
            and ``DRY_RUN`` is not set.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    def get(name: str) -> str:
        return (source.get(name) or "").strip()

    dry_run = is_truthy(get("DRY_RUN"))
    api_key = get("CALLMEBOT_API_KEY")
    phone = get("CALLMEBOT_PHONE")
    if not dry_run:
        missing = [name for name, value in (("CALLMEBOT_API_KEY", api_key), ("CALLMEBOT_PHONE", phone)) if not value]
        if missing:
            raise ConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set DRY_RUN=1 to test without sending WhatsApp messages."
            )

    return Settings(
        upstox_token=get("UPSTOX_ANALYTICS_TOKEN") or None,
        callmebot_api_key=api_key,
        callmebot_phone=phone,
        portfolio_stocks=parse_portfolio(get("PORTFOLIO_STOCKS")),
        gift_instrument_key=get("GIFT_NIFTY_INSTRUMENT_KEY") or DEFAULT_GIFT_NIFTY_INSTRUMENT_KEY,
        dry_run=dry_run,
        force_run=is_truthy(get("FORCE_RUN")),
    )
