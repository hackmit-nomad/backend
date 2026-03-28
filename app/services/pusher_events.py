from __future__ import annotations

import logging
from typing import Any

from pusher import Pusher

from app.core.config import PUSHER_APP_ID, PUSHER_CLUSTER, PUSHER_KEY, PUSHER_SECRET

logger = logging.getLogger(__name__)

_pusher_client: Pusher | None = None


def _is_configured() -> bool:
    return bool(PUSHER_APP_ID and PUSHER_KEY and PUSHER_SECRET and PUSHER_CLUSTER)


def _client() -> Pusher | None:
    global _pusher_client

    if not _is_configured():
        return None

    if _pusher_client is None:
        _pusher_client = Pusher(
            app_id=PUSHER_APP_ID,
            key=PUSHER_KEY,
            secret=PUSHER_SECRET,
            cluster=PUSHER_CLUSTER,
            ssl=True,
        )
    return _pusher_client


def publish_message_event(chat_id: str, event_name: str, payload: dict[str, Any]) -> None:
    client = _client()
    if client is None:
        return

    channel = f"CONVERSATION-{chat_id}"
    try:
        client.trigger(channels=[channel], event_name=event_name, data=payload)
    except Exception:
        logger.exception("Failed to publish Pusher event %s for chat %s", event_name, chat_id)
