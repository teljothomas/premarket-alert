"""Shared helpers: tolerant number parsing, percent change and time limits."""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MISSING_MARKERS = {"", "-", "--", "na", "n/a", "nan", "none", "null"}


def to_float(value: Any) -> float | None:
    """Convert an API value to a float, tolerating strings like ``"1,234.50"``.

    Args:
        value: A number, a numeric string (commas and ``₹`` allowed), or
            anything else.

    Returns:
        The finite float value, or None if the value is missing or unparseable.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("₹", "")
        if text.lower() in _MISSING_MARKERS:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Compute the percentage change from ``previous`` to ``current``.

    Args:
        current: Latest value.
        previous: Reference value (usually the previous close).

    Returns:
        Change in percent rounded to 2 decimals, or None if an input is
        missing or ``previous`` is zero.
    """
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def norm_key(key: Any) -> str:
    """Normalise a column name for matching, e.g. ``"Net Value"`` -> ``"netvalue"``.

    Args:
        key: Column or dictionary key.

    Returns:
        Lower-case key with everything except letters and digits removed.
    """
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def to_records(frame: Any) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame (or list of dicts) to dicts with normalised keys.

    Args:
        frame: DataFrame-like object with ``to_dict``, or a list of mappings.

    Returns:
        One dict per row, keyed by :func:`norm_key`; empty if unusable.
    """
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
    elif isinstance(frame, list):
        rows = frame
    else:
        return []
    return [{norm_key(k): v for k, v in row.items()} for row in rows if isinstance(row, Mapping)]


def gift_label(gift: Mapping[str, Any] | None) -> str:
    """Return the display name for the GIFT Nifty signal.

    Args:
        gift: Result of ``fetch_gift_nifty`` (may be None).

    Returns:
        ``"GIFT Nifty"``, or a label flagging the Nifty 50 fallback proxy.
    """
    source = str((gift or {}).get("source") or "")
    return "GIFT Nifty (Nifty 50 proxy)" if source.startswith("yahoo") else "GIFT Nifty"


def run_with_timeout(name: str, timeout: float, func: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Run ``func`` in a daemon thread and stop waiting after ``timeout`` seconds.

    The NSE client libraries do not expose request timeouts, so one stalled
    call could otherwise blow the run's time budget. A timed-out thread keeps
    running as a daemon and is discarded when the process exits.

    Args:
        name: Label used in log messages.
        timeout: Maximum seconds to wait.
        func: Callable to run.
        *args: Positional arguments for ``func``.
        **kwargs: Keyword arguments for ``func``.

    Returns:
        ``func``'s return value, or None if it timed out or raised.
    """
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - a fetcher must never crash the run
            logger.exception("%s failed unexpectedly", name)

    started = time.monotonic()
    worker = threading.Thread(target=target, name=name, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.error("%s timed out after %.0fs; continuing without it", name, timeout)
        return None
    logger.debug("%s finished in %.1fs", name, time.monotonic() - started)
    return outcome.get("value")
