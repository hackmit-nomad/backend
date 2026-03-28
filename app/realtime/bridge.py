"""
Subscribe to Supabase Realtime postgres_changes on `messages` and fan out to WebSocket clients.

Requires Realtime enabled for `public.messages` in Supabase. Runs subscription in a daemon thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.db.supabase import supabase
from app.services.messaging import get_participant_user_ids_for_chat
from app.ws.connection_manager import manager

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def _schedule_broadcast(message: dict[str, Any], user_ids: list[str]) -> None:
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast_to_users(user_ids, message), _loop)


def _on_postgres_payload(payload: Any) -> None:
    try:
        if isinstance(payload, dict):
            record = payload.get("record") or {}
            old = payload.get("old_record") or {}
        else:
            record = getattr(payload, "record", None) or {}
            old = getattr(payload, "old_record", None) or {}
        chat_id = record.get("chatId") or old.get("chatId")
        if not chat_id:
            return
        user_ids = get_participant_user_ids_for_chat(str(chat_id))
        if not user_ids:
            return
        normalized: dict[str, Any]
        if isinstance(payload, dict):
            normalized = payload
        else:
            normalized = {"record": record, "old_record": old}
        _schedule_broadcast(
            {
                "type": "realtime",
                "event": "postgres_changes",
                "table": "messages",
                "payload": normalized,
            },
            user_ids,
        )
    except Exception:
        logger.exception("Realtime bridge handler failed")


def _subscribe_sync() -> None:
    ch = supabase.channel("nomad-messages-bridge")
    # supabase-py versions differ: try common signatures
    try:
        ch.on_postgres_changes("*", _on_postgres_payload, schema="public", table="messages")
    except TypeError:
        try:
            ch.on_postgres_changes(
                event="*",
                schema="public",
                table="messages",
                callback=_on_postgres_payload,
            )
        except TypeError:
            ch.on_postgres_changes("INSERT", _on_postgres_payload, schema="public", table="messages")
    ch.subscribe()


def start_realtime_bridge(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop

    def _run() -> None:
        try:
            _subscribe_sync()
            logger.info("Supabase Realtime subscribed to public.messages")
        except Exception as exc:
            logger.warning(
                "Supabase Realtime bridge not started (%s). Enable Realtime on `messages` or check supabase-py.",
                exc,
            )

    threading.Thread(target=_run, name="supabase-realtime-bridge", daemon=True).start()
