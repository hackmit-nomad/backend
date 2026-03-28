from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/messages", tags=["Messages"])

"""
message:sent
@description Emitted when a new chat message is sent
@params Message message, string chatId
@returns void emitted

message:updated
@description Emitted when a chat message is updated
@params Message message, string chatId
@returns void emitted

message:deleted
@description Emitted when a chat message is deleted
@params string messageId, string chatId
@returns void emitted
"""

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
            "groupIcon": c.get("groupIcon"),
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
    groupIcon: str | None = None


@router.post("/conversations", status_code=201)
def create_conversation(body: CreateConversationRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    participant_ids = list(dict.fromkeys([p for p in body.participants if p]))
    if not participant_ids:
        raise HTTPException(status_code=400, detail="At least one participant is required")

    # Auto-upgrade to group if multiple members are requested.
    is_group = bool(body.isGroup or len(participant_ids) > 1)
    chat_type = "group" if is_group else "direct"
    insert_payload = {"type": chat_type, "createdAt": now, "groupName": body.groupName, "groupIcon": body.groupIcon}
    try:
        chat_resp = supabase.table("chats").insert(insert_payload).execute()
    except Exception:
        # Backward-compatible fallback when DB schema has no groupIcon column yet.
        fallback_payload = {"type": chat_type, "createdAt": now, "groupName": body.groupName}
        chat_resp = supabase.table("chats").insert(fallback_payload).execute()
    if not chat_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    chat = chat_resp.data[0]

    participants = list(dict.fromkeys([user_id, *participant_ids]))
    for pid in participants:
        supabase.table("chat_participants").upsert({"chatId": chat["id"], "userId": pid, "joinedAt": now}).execute()

    return {
        "id": chat["id"],
        "participants": participants,
        "isGroup": is_group,
        "groupName": chat.get("groupName"),
        "groupIcon": chat.get("groupIcon"),
        "lastMessage": "",
        "lastTimestamp": now,
        "unread": 0,
    }


class UpdateConversationRequest(BaseModel):
    groupName: str | None = None
    groupIcon: str | None = None


@router.patch("/conversations/{conversationId}")
def update_conversation(
    conversationId: str,
    body: UpdateConversationRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _assert_is_participant(conversationId, user_id)
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if payload:
        try:
            supabase.table("chats").update(payload).eq("id", conversationId).execute()
        except Exception:
            # Backward-compatible fallback when DB schema has no groupIcon column yet.
            payload_without_icon = {k: v for k, v in payload.items() if k != "groupIcon"}
            if payload_without_icon:
                supabase.table("chats").update(payload_without_icon).eq("id", conversationId).execute()
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
        "groupIcon": chat.get("groupIcon"),
        "lastMessage": last.get("content") if last else "",
        "lastTimestamp": last.get("createdAt") if last else chat.get("createdAt"),
        "unread": 0,
    }


@router.delete("/conversations/{conversationId}", status_code=204)
def delete_conversation(conversationId: str, user_id: str = Depends(get_current_user_id)) -> None:
    _assert_is_participant(conversationId, user_id)
    exists = supabase.table("chats").select("id").eq("id", conversationId).single().execute().data
    if not exists:
        raise HTTPException(status_code=404, detail="Conversation not found")
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
    row = (
        supabase.table("messages")
        .select("*")
        .eq("id", messageId)
        .eq("chatId", conversationId)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    if row.get("senderId") != user_id:
        raise HTTPException(status_code=403, detail="Only message sender can delete this message")
    supabase.table("messages").update({"deletedAt": datetime.now(timezone.utc).isoformat()}).eq("id", messageId).execute()
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

