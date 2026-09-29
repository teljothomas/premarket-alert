"""Send the alert to WhatsApp through CallMeBot's free API."""

from __future__ import annotations

import logging
import re

import requests

from src import config

logger = logging.getLogger(__name__)


def _redact(text: str, *secrets: str) -> str:
    """Remove secrets (API key, phone) from text before it is logged."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _plain(html: str) -> str:
    """Collapse CallMeBot's HTML response to a single line of text."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def send_whatsapp(message: str | None, phone: str, api_key: str, dry_run: bool = False) -> bool:
    """Send ``message`` via CallMeBot. Never raises.

    Args:
        message: Text to send; None means nothing to send.
        phone: Recipient in international format (``+`` is added if missing).
        api_key: CallMeBot API key.
        dry_run: Log the message instead of sending it.

    Returns:
        True if CallMeBot accepted the message, otherwise False.
    """
    if message is None:
        logger.info("No alert needed")
        return False
    if dry_run:
        logger.info("DRY_RUN set; message not sent:\n%s", message)
        return False
    if not phone or not api_key:
        logger.error("CallMeBot phone or API key missing; cannot send WhatsApp message")
        return False

    number = phone.strip().replace(" ", "")
    if not number.startswith("+"):
        number = "+" + number

    try:
        response = requests.get(
            config.CALLMEBOT_URL,
            params={"phone": number, "text": message, "apikey": api_key},
            timeout=config.SEND_TIMEOUT_SECONDS,
        )
        body = _redact(_plain(response.text), api_key, number)
        logger.debug("CallMeBot HTTP %s: %s", response.status_code, body[:500])
        if response.status_code == 200 and "invalid" not in body.lower():
            logger.info("WhatsApp alert sent via CallMeBot")
            return True
        logger.error("WhatsApp send failed: HTTP %s - %s", response.status_code, body[:300])
        return False
    except Exception as exc:  # noqa: BLE001 - the workflow must still complete
        # requests errors can embed the full URL, including the API key.
        logger.error("WhatsApp send failed: %s", _redact(str(exc), api_key, number))
        return False
