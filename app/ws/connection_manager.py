"""Track active WebSocket connections per user for Supabase Realtime fan-out."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from starlette.websockets import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._by_user: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def register(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._by_user[user_id].append(websocket)

    async def unregister(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._by_user.get(user_id)
            if not conns:
                return
            try:
                conns.remove(websocket)
            except ValueError:
                pass
            if not conns:
                del self._by_user[user_id]

    async def broadcast_to_users(self, user_ids: list[str], message: dict[str, Any]) -> None:
        text = json.dumps(message, default=str)
        uid_set = set(user_ids)
        async with self._lock:
            targets: list[WebSocket] = []
            for uid in uid_set:
                targets.extend(self._by_user.get(uid, []))
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                pass


manager = ConnectionManager()
