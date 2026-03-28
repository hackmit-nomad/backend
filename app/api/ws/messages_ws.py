"""
WebSocket API for messaging (replaces HTTP under /messages/conversations).

See `openapi-mvp-v3.yaml` for the contract.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import get_user_id_from_access_token
from app.services.messaging import MessagingError
from app.services import messaging as messaging_svc
from app.ws.connection_manager import manager

router = APIRouter(tags=["Messages"])


def _err(call_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "id": call_id or "", "code": code, "message": message}


async def _dispatch_action(user_id: str, action: str, payload: dict[str, Any]) -> Any:
    p = payload or {}

    if action == "list_conversations":
        return await asyncio.to_thread(messaging_svc.list_conversations, user_id, p.get("q"))

    if action == "create_conversation":
        return await asyncio.to_thread(
            messaging_svc.create_conversation,
            user_id,
            p.get("participants") or [],
            bool(p.get("isGroup", False)),
            p.get("groupName"),
            p.get("groupIcon"),
        )

    if action == "update_conversation":
        cid = p.get("conversationId")
        if not cid:
            raise MessagingError(400, "BAD_REQUEST", "conversationId required")
        return await asyncio.to_thread(
            messaging_svc.update_conversation,
            str(cid),
            user_id,
            p.get("groupName"),
            p.get("groupIcon"),
        )

    if action == "delete_conversation":
        cid = p.get("conversationId")
        if not cid:
            raise MessagingError(400, "BAD_REQUEST", "conversationId required")
        await asyncio.to_thread(messaging_svc.delete_conversation, str(cid), user_id)
        return None

    if action == "list_messages":
        cid = p.get("conversationId")
        if not cid:
            raise MessagingError(400, "BAD_REQUEST", "conversationId required")
        return await asyncio.to_thread(messaging_svc.list_messages, str(cid), user_id)

    if action == "send_message":
        cid = p.get("conversationId")
        content = p.get("content")
        if not cid or content is None:
            raise MessagingError(400, "BAD_REQUEST", "conversationId and content required")
        return await asyncio.to_thread(messaging_svc.send_message, str(cid), user_id, str(content))

    if action == "delete_message":
        cid = p.get("conversationId")
        mid = p.get("messageId")
        if not cid or not mid:
            raise MessagingError(400, "BAD_REQUEST", "conversationId and messageId required")
        await asyncio.to_thread(messaging_svc.delete_message, str(cid), str(mid), user_id)
        return None

    raise MessagingError(400, "UNKNOWN_ACTION", f"Unknown action: {action}")


@router.websocket("/ws/messages")
async def messages_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT access token"),
) -> None:
    await websocket.accept()
    user_id: str | None = None

    if token:
        try:
            user_id = get_user_id_from_access_token(token)
        except ValueError as e:
            await websocket.send_json(_err(None, "UNAUTHORIZED", str(e)))
            await websocket.close(code=4401)
            return

    try:
        while user_id is None:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(_err(None, "BAD_REQUEST", "Invalid JSON"))
                continue
            if data.get("type") != "auth":
                await websocket.send_json(
                    _err(None, "UNAUTHORIZED", "Send {type:auth,token} or use ?token=")
                )
                continue
            t = data.get("token")
            if not t:
                await websocket.send_json(_err(None, "UNAUTHORIZED", "token required"))
                await websocket.close(code=4401)
                return
            try:
                user_id = get_user_id_from_access_token(str(t))
            except ValueError as e:
                await websocket.send_json(_err(None, "UNAUTHORIZED", str(e)))
                await websocket.close(code=4401)
                return

        await manager.register(user_id, websocket)
        await websocket.send_json({"type": "ready", "userId": user_id})

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(_err(None, "BAD_REQUEST", "Invalid JSON"))
                continue

            if data.get("type") != "call":
                await websocket.send_json(_err(None, "BAD_REQUEST", "Expected type:call"))
                continue

            call_id = str(data.get("id") or uuid.uuid4())
            action = data.get("action")
            payload = data.get("payload")
            if not action:
                await websocket.send_json(_err(call_id, "BAD_REQUEST", "action required"))
                continue
            if payload is not None and not isinstance(payload, dict):
                await websocket.send_json(_err(call_id, "BAD_REQUEST", "payload must be object"))
                continue

            try:
                result = await _dispatch_action(user_id, str(action), payload if isinstance(payload, dict) else {})
                await websocket.send_json({"type": "result", "id": call_id, "ok": True, "data": result})
            except MessagingError as e:
                await websocket.send_json(
                    {
                        "type": "error",
                        "id": call_id,
                        "code": e.code,
                        "message": e.message,
                        "httpStatus": e.http_status,
                    }
                )
            except Exception:
                await websocket.send_json(_err(call_id, "INTERNAL", "Unexpected server error"))

    except WebSocketDisconnect:
        pass
    finally:
        if user_id:
            await manager.unregister(user_id, websocket)
