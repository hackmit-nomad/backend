"""Sync messaging logic shared by WebSocket handlers (Supabase client is sync)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.supabase import supabase


class MessagingError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        self.http_status = http_status
        self.code = code
        self.message = message
        super().__init__(message)


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
        raise MessagingError(404, "NOT_FOUND", "Conversation not found")


def list_conversations(user_id: str, q: str | None = None) -> dict[str, Any]:
    cp = (supabase.table("chat_participants").select("chatId").eq("userId", user_id).execute().data) or []
    chat_ids = [r["chatId"] for r in cp]
    if not chat_ids:
        return {"items": [], "total": 0}

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
            supabase.table("chat_participants").select("userId").eq("chatId", c["id"]).execute().data
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


def create_conversation(
    user_id: str,
    participants: list[str],
    is_group: bool = False,
    group_name: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    chat_type = "group" if is_group else "direct"
    chat_resp = supabase.table("chats").insert({"type": chat_type, "createdAt": now, "groupName": group_name}).execute()
    if not chat_resp.data:
        raise MessagingError(500, "CREATE_FAILED", "Failed to create conversation")
    chat = chat_resp.data[0]

    all_participants = list(dict.fromkeys([user_id, *participants]))
    for pid in all_participants:
        supabase.table("chat_participants").upsert(
            {"chatId": chat["id"], "userId": pid, "joinedAt": now}
        ).execute()

    return {
        "id": chat["id"],
        "participants": all_participants,
        "isGroup": is_group,
        "groupName": group_name,
        "lastMessage": "",
        "lastTimestamp": now,
        "unread": 0,
    }


def update_conversation(conversation_id: str, user_id: str, group_name: str | None) -> dict[str, Any]:
    _assert_is_participant(conversation_id, user_id)
    payload = {}
    if group_name is not None:
        payload["groupName"] = group_name
    if payload:
        supabase.table("chats").update(payload).eq("id", conversation_id).execute()
    chat = supabase.table("chats").select("*").eq("id", conversation_id).single().execute().data
    if not chat:
        raise MessagingError(404, "NOT_FOUND", "Conversation not found")

    participants = (
        supabase.table("chat_participants").select("userId").eq("chatId", conversation_id).execute().data
    ) or []
    participant_ids = [p["userId"] for p in participants]
    last_msg = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", conversation_id)
        .is_("deletedAt", "null")
        .order("createdAt", desc=True)
        .limit(1)
        .execute()
        .data
    )
    last = last_msg[0] if last_msg else None
    return {
        "id": conversation_id,
        "participants": participant_ids,
        "isGroup": chat.get("type") == "group",
        "groupName": chat.get("groupName"),
        "lastMessage": last.get("content") if last else "",
        "lastTimestamp": last.get("createdAt") if last else chat.get("createdAt"),
        "unread": 0,
    }


def delete_conversation(conversation_id: str, user_id: str) -> None:
    _assert_is_participant(conversation_id, user_id)
    exists = supabase.table("chats").select("id").eq("id", conversation_id).single().execute().data
    if not exists:
        raise MessagingError(404, "NOT_FOUND", "Conversation not found")
    supabase.table("messages").delete().eq("chatId", conversation_id).execute()
    supabase.table("chat_participants").delete().eq("chatId", conversation_id).execute()
    supabase.table("chats").delete().eq("id", conversation_id).execute()


def list_messages(conversation_id: str, user_id: str) -> dict[str, Any]:
    _assert_is_participant(conversation_id, user_id)
    msgs = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", conversation_id)
        .is_("deletedAt", "null")
        .order("createdAt", desc=False)
        .execute()
        .data
    ) or []
    mapped = [_msg_to_api(m) for m in msgs]
    return {"items": mapped, "total": len(mapped)}


def send_message(conversation_id: str, user_id: str, content: str) -> dict[str, Any]:
    _assert_is_participant(conversation_id, user_id)
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("messages")
        .insert(
            {
                "chatId": conversation_id,
                "senderId": user_id,
                "content": content,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        .execute()
    )
    if not resp.data:
        raise MessagingError(500, "SEND_FAILED", "Failed to send message")
    return _msg_to_api(resp.data[0])


def delete_message(conversation_id: str, message_id: str, user_id: str) -> None:
    _assert_is_participant(conversation_id, user_id)
    row = (
        supabase.table("messages")
        .select("*")
        .eq("id", message_id)
        .eq("chatId", conversation_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise MessagingError(404, "NOT_FOUND", "Message not found")
    if row.get("senderId") != user_id:
        raise MessagingError(403, "FORBIDDEN", "Only message sender can delete this message")
    supabase.table("messages").update({"deletedAt": datetime.now(timezone.utc).isoformat()}).eq("id", message_id).execute()


def _msg_to_api(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": m["id"],
        "senderId": m.get("senderId"),
        "content": m.get("content") or "",
        "timestamp": m.get("createdAt"),
    }


def get_participant_user_ids_for_chat(chat_id: str) -> list[str]:
    rows = (
        supabase.table("chat_participants").select("userId").eq("chatId", chat_id).execute().data
    ) or []
    return [r["userId"] for r in rows]
