from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/messages", tags=["Messages"])


@router.get("/conversations")
def list_conversations(q: str | None = Query(default=None), user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    cp = (
        supabase.table("chat_participants")
        .select("chatId")
        .eq("userId", user_id)
        .execute()
        .data
    ) or []
    chat_ids = [r["chatId"] for r in cp]
    if not chat_ids:
        return {"items": []}

    chats = supabase.table("chats").select("*").in_("id", chat_ids).execute().data or []
    items: list[dict[str, Any]] = []
    for c in chats:
        last_msg = (
            supabase.table("messages")
            .select("*")
            .eq("chatId", c["id"])
            .is_("deletedAt", "null")
            .order("createdAt", desc=True)
            .limit(1)
            .execute()
            .data
        )
        last = last_msg[0] if last_msg else None

        participants = (
            supabase.table("chat_participants")
            .select("userId")
            .eq("chatId", c["id"])
            .execute()
            .data
        ) or []
        participant_ids = [p["userId"] for p in participants]

        convo = {
            "id": c["id"],
            "participants": participant_ids,
            "isGroup": c.get("type") == "group",
            "groupName": c.get("groupName"),
            "lastMessage": last.get("content") if last else "",
            "lastTimestamp": last.get("createdAt") if last else c.get("createdAt"),
            "unread": 0,
        }
        if not q or q.lower() in convo["lastMessage"].lower():
            items.append(convo)

    return {"items": items, "total": len(items)}


class CreateConversationRequest(BaseModel):
    participants: list[str]
    isGroup: bool = False
    groupName: str | None = None


@router.post("/conversations", status_code=201)
def create_conversation(body: CreateConversationRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    chat_type = "group" if body.isGroup else "direct"
    chat_resp = (
        supabase.table("chats")
        .insert({"type": chat_type, "createdAt": now, "groupName": body.groupName})
        .execute()
    )
    if not chat_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    chat = chat_resp.data[0]

    participants = list(dict.fromkeys([user_id, *body.participants]))
    for pid in participants:
        supabase.table("chat_participants").upsert({"chatId": chat["id"], "userId": pid, "joinedAt": now}).execute()

    return {
        "id": chat["id"],
        "participants": participants,
        "isGroup": body.isGroup,
        "groupName": body.groupName,
        "lastMessage": "",
        "lastTimestamp": now,
        "unread": 0,
    }


class UpdateConversationRequest(BaseModel):
    groupName: str | None = None


@router.patch("/conversations/{conversationId}")
def update_conversation(
    conversationId: str,
    body: UpdateConversationRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _assert_is_participant(conversationId, user_id)
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if payload:
        supabase.table("chats").update(payload).eq("id", conversationId).execute()
    chat = supabase.table("chats").select("*").eq("id", conversationId).single().execute().data
    if not chat:
        raise HTTPException(status_code=404, detail="Conversation not found")

    participants = (
        supabase.table("chat_participants").select("userId").eq("chatId", conversationId).execute().data
    ) or []
    participant_ids = [p["userId"] for p in participants]
    last_msg = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", conversationId)
        .is_("deletedAt", "null")
        .order("createdAt", desc=True)
        .limit(1)
        .execute()
        .data
    )
    last = last_msg[0] if last_msg else None
    return {
        "id": conversationId,
        "participants": participant_ids,
        "isGroup": chat.get("type") == "group",
        "groupName": chat.get("groupName"),
        "lastMessage": last.get("content") if last else "",
        "lastTimestamp": last.get("createdAt") if last else chat.get("createdAt"),
        "unread": 0,
    }


@router.delete("/conversations/{conversationId}", status_code=204)
def delete_conversation(conversationId: str, user_id: str = Depends(get_current_user_id)) -> None:
    _assert_is_participant(conversationId, user_id)
    supabase.table("messages").delete().eq("chatId", conversationId).execute()
    supabase.table("chat_participants").delete().eq("chatId", conversationId).execute()
    supabase.table("chats").delete().eq("id", conversationId).execute()
    return None


@router.get("/conversations/{conversationId}/messages")
def list_messages(conversationId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _assert_is_participant(conversationId, user_id)
    msgs = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", conversationId)
        .is_("deletedAt", "null")
        .order("createdAt", desc=False)
        .execute()
        .data
    ) or []
    mapped = [_msg_to_api(m) for m in msgs]
    return {"items": mapped, "total": len(mapped)}


class CreateMessageRequest(BaseModel):
    content: str


@router.post("/conversations/{conversationId}/messages", status_code=201)
def send_message(conversationId: str, body: CreateMessageRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _assert_is_participant(conversationId, user_id)
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("messages")
        .insert({"chatId": conversationId, "senderId": user_id, "content": body.content, "createdAt": now, "updatedAt": now})
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to send message")
    return _msg_to_api(resp.data[0])


@router.delete("/conversations/{conversationId}/messages/{messageId}", status_code=204)
def delete_message(conversationId: str, messageId: str, user_id: str = Depends(get_current_user_id)) -> None:
    _assert_is_participant(conversationId, user_id)
    supabase.table("messages").delete().eq("id", messageId).eq("chatId", conversationId).execute()
    return None


def _assert_is_participant(chat_id: str, user_id: str) -> None:
    exists = (
        supabase.table("chat_participants")
        .select("chatId")
        .eq("chatId", chat_id)
        .eq("userId", user_id)
        .execute()
        .data
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Conversation not found")


def _msg_to_api(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": m["id"],
        "senderId": m.get("senderId"),
        "content": m.get("content") or "",
        "timestamp": m.get("createdAt"),
    }

