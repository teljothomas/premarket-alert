"""Entry point: ``python -m src.main``.

Fetches pre-market signals, grades them, and sends a WhatsApp alert when the
level is YELLOW or RED. Exits 0 on every path except a fatal config error.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src import config
from src.evaluate import evaluate_alert
from src.fetch_fii_dii import fetch_fii_dii
from src.fetch_gift_nifty import fetch_gift_nifty
from src.fetch_stocks import fetch_stocks
from src.fetch_vix import fetch_vix
from src.format_message import format_data_failure_message, format_message
from src.send_whatsapp import send_whatsapp
from src.utils import run_with_timeout, to_float

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

logger = logging.getLogger("premarket")


def configure_logging(level_name: str = "INFO") -> None:
    """Configure root logging to stdout.

    Args:
        level_name: Logging level name, e.g. ``"INFO"`` or ``"DEBUG"``.
    """
    # Emoji in log lines would crash a cp1252 Windows console without this.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass
    level = logging.getLevelName(level_name.strip().upper() or "INFO")
    logging.basicConfig(
        level=level if isinstance(level, int) else logging.INFO, format=LOG_FORMAT, stream=sys.stdout, force=True
    )
    # urllib3 logs full request URLs at DEBUG, which would include the CallMeBot API key.
    for noisy in ("urllib3", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _load_dotenv() -> None:
    """Load a local ``.env`` file if python-dotenv is installed (optional)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _fmt_pct(data: Mapping[str, Any] | None) -> str:
    """Format ``data['change_pct']`` for the summary line."""
    change = to_float(data.get("change_pct")) if isinstance(data, Mapping) else None
    return f"{change:+.2f}%" if change is not None else "n/a"


def run(settings: config.Settings) -> None:
    """Run one pre-market check: fetch, evaluate, format, send, summarise.

    Args:
        settings: Resolved runtime settings.
    """
    started = time.monotonic()
    logger.info("Pre-market check for %d stock(s): %s", len(settings.portfolio_stocks), ", ".join(settings.portfolio_stocks))

    gift = run_with_timeout(
        "GIFT Nifty", config.GIFT_TIMEOUT_SECONDS, fetch_gift_nifty, settings.upstox_token, settings.gift_instrument_key
    )
    vix = run_with_timeout("India VIX", config.VIX_TIMEOUT_SECONDS, fetch_vix)
    fii = run_with_timeout("FII/DII", config.FII_TIMEOUT_SECONDS, fetch_fii_dii)
    stocks = run_with_timeout(
        "Portfolio stocks",
        config.STOCKS_TIMEOUT_SECONDS,
        fetch_stocks,
        settings.portfolio_stocks,
        deadline=time.monotonic() + config.STOCKS_TIMEOUT_SECONDS - 3,
        upstox_token=settings.upstox_token,
    )

    sources = {"GIFT Nifty": gift, "India VIX": vix, "FII/DII": fii, "Portfolio stocks": stocks}
    missing = [name for name, value in sources.items() if value is None]
    if missing:
        logger.warning("Unavailable data (skipped in evaluation): %s", ", ".join(missing))

    level, reasons = evaluate_alert(gift, vix, fii, stocks)
    logger.info("Alert level: %s (%s)", level, "; ".join(reasons) or "no signals")

    message = format_message(level, reasons, gift, vix, fii, stocks)
    summary_level = level
    if message is None and gift is None and config.NOTIFY_ON_DATA_FAILURE:
        logger.warning("Primary signal missing; sending a 'check incomplete' notice instead of staying silent")
        message = format_data_failure_message(missing)
        summary_level = "UNKNOWN"

    sent = send_whatsapp(message, settings.callmebot_phone, settings.callmebot_api_key, dry_run=settings.dry_run)

    logger.info(
        "SUMMARY %s | %s | gift=%s | vix=%s | sent=%s",
        datetime.now(config.IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        summary_level,
        _fmt_pct(gift),
        _fmt_pct(vix),
        "Y" if sent else "N",
    )
    logger.info("Finished in %.1fs", time.monotonic() - started)


def main() -> int:
    """Program entry point.

    Returns:
        Process exit code: 0 normally (including skipped weekends and data
        failures), 1 only for a fatal configuration error.
    """
    _load_dotenv()
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))

    try:
        settings = config.load_settings()
    except config.ConfigError as exc:
        logger.error("Fatal configuration error: %s", exc)
        return 1

    now = datetime.now(config.IST)
    if now.weekday() >= 5 and not settings.force_run:
        logger.info("%s is a weekend; NSE is closed. Skipping.", now.strftime("%A %d-%b-%Y"))
        return 0
    if not settings.upstox_token:
        logger.warning("UPSTOX_ANALYTICS_TOKEN not set; GIFT Nifty will use the Yahoo Finance Nifty 50 proxy")

    try:
        run(settings)
    except Exception:  # noqa: BLE001 - never fail the workflow on data/runtime errors
        logger.exception("Unexpected error during pre-market check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
