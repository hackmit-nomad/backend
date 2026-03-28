from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.core.config import CHAT_WORKFLOW_API_KEY
from app.db.supabase import supabase
from app.services.pusher_events import publish_message_event

router = APIRouter(prefix="/messages", tags=["Messages"])
PROPOSAL_NOTIFICATION_TYPE = "calendar_proposal"
NOMAD_AGENT_ID = "00000000-0000-0000-0000-00000000a1a1"
logger = logging.getLogger(__name__)


def _debug_log(message: str) -> None:
    # Ensure visibility even when logger config suppresses app-level INFO logs.
    logger.warning(message)
    print(message, flush=True)

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


class UpdateMessageRequest(BaseModel):
    content: str


class CreateScheduleProposalsRequest(BaseModel):
    prompt: str | None = None


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
    message = _msg_to_api(resp.data[0])
    publish_message_event(
        conversationId,
        event_name="new-message",
        payload={
            "id": message["id"],
            "content": message["content"],
            "senderId": message["senderId"],
            "timestamp": message["timestamp"],
        },
    )
    return message


@router.patch("/conversations/{conversationId}/messages/{messageId}")
def update_message(
    conversationId: str,
    messageId: str,
    body: UpdateMessageRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
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
    if not row or row.get("deletedAt"):
        raise HTTPException(status_code=404, detail="Message not found")
    if row.get("senderId") != user_id:
        raise HTTPException(status_code=403, detail="Only message sender can update this message")

    updated_at = datetime.now(timezone.utc).isoformat()
    updated = (
        supabase.table("messages")
        .update({"content": body.content, "updatedAt": updated_at})
        .eq("id", messageId)
        .eq("chatId", conversationId)
        .execute()
        .data
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update message")

    message = _msg_to_api(updated[0])
    publish_message_event(
        conversationId,
        event_name="upd-message",
        payload={
            "id": message["id"],
            "content": message["content"],
            "senderId": message["senderId"],
            "timestamp": message["timestamp"],
        },
    )
    return message


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
    publish_message_event(
        conversationId,
        event_name="del-message",
        payload={"id": messageId},
    )
    return None


@router.post("/conversations/{conversationId}/schedule-proposals")
async def create_schedule_proposals(
    conversationId: str,
    body: CreateScheduleProposalsRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    _assert_is_participant(conversationId, user_id)
    if not CHAT_WORKFLOW_API_KEY:
        raise HTTPException(status_code=503, detail="CHAT_SCHEDULER_KEY not configured")
    _ensure_nomad_agent_profile()

    participants = (
        supabase.table("chat_participants")
        .select("userId")
        .eq("chatId", conversationId)
        .execute()
        .data
    ) or []
    participant_ids = [str(p["userId"]) for p in participants if p.get("userId")]
    if not participant_ids:
        raise HTTPException(status_code=404, detail="Conversation has no participants")

    messages = (
        supabase.table("messages")
        .select("senderId,content,createdAt")
        .eq("chatId", conversationId)
        .is_("deletedAt", "null")
        .order("createdAt", desc=False)
        .limit(60)
        .execute()
        .data
    ) or []
    chat_context = "\n".join(
        f'{m.get("senderId") or "unknown"} ({m.get("createdAt") or ""}): {(m.get("content") or "").strip()}'
        for m in messages
        if (m.get("content") or "").strip()
    )

    combined_agenda_payload: dict[str, list[dict[str, Any]]] = {}
    for pid in participant_ids:
        rows = (
            supabase.table("calendar_events")
            .select("id,title,date,startTime,endTime,location,type,color")
            .eq("userId", pid)
            .order("date", desc=False)
            .order("startTime", desc=False)
            .execute()
            .data
        ) or []
        combined_agenda_payload[pid] = [
            {
                "id": row.get("id"),
                "title": row.get("title") or "",
                "date": row.get("date"),
                "startTime": row.get("startTime"),
                "endTime": row.get("endTime"),
                "location": row.get("location"),
                "type": row.get("type"),
                "color": row.get("color"),
            }
            for row in rows
        ]

    try:
        raw_answer = await _call_diffy_shared_schedule_agent(
            chat_context=chat_context,
            combined_agenda=json.dumps(combined_agenda_payload),
            prompt=body.prompt,
            user_id=user_id,
        )
    except HTTPException as exc:
        _post_nomad_message(
            conversationId,
            f"I could not generate schedule proposals right now.\nReason: {exc.detail}",
        )
        raise

    generated_events = _extract_generated_events(raw_answer)
    if not generated_events:
        _post_nomad_message(
            conversationId,
            "I reviewed the conversation and agenda, but could not infer a valid proposal yet. "
            "Try adding specific time constraints in chat.",
        )
        return {"items": [], "total": 0}

    now = datetime.now(timezone.utc).isoformat()
    created_for_user = 0
    for event in generated_events:
        payload = {
            "conversationId": conversationId,
            "reason": event.get("reason"),
            "event": {
                "title": event["title"],
                "date": event["date"],
                "startTime": event["startTime"],
                "endTime": event["endTime"],
                "location": event.get("location"),
                "type": event["type"],
                "color": event.get("color"),
            },
        }
        payload_json = json.dumps(payload)
        for pid in participant_ids:
            supabase.table("notifications").insert(
                {
                    "userId": pid,
                    "type": PROPOSAL_NOTIFICATION_TYPE,
                    "fromId": user_id,
                    "content": payload_json,
                    "createdAt": now,
                    "read": False,
                }
            ).execute()
            if pid == user_id:
                created_for_user += 1

    summary_lines = [
        f"I proposed {len(generated_events)} event(s) for this chat.",
        "Open Calendar > Incoming Proposals to review and accept.",
    ]
    for event in generated_events[:3]:
        summary_lines.append(
            f"- {event.get('title') or 'Proposed Event'} on {event.get('date')} "
            f"{event.get('startTime')}-{event.get('endTime')}"
        )
    _post_nomad_message(conversationId, "\n".join(summary_lines))

    return {"items": generated_events, "total": len(generated_events), "participants": len(participant_ids), "createdForMe": created_for_user}


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


def _ensure_nomad_agent_profile() -> None:
    existing = (
        supabase.table("profiles")
        .select("id")
        .eq("id", NOMAD_AGENT_ID)
        .limit(1)
        .execute()
        .data
    ) or []
    if existing:
        return

    payload = {
        "id": NOMAD_AGENT_ID,
        "displayName": "Nomad",
        "avatarUrl": "https://api.dicebear.com/7.x/bottts/svg?seed=NomadAI",
        "headline": "AI Scheduling Assistant",
        "bio": "I help coordinate group schedules from chat context.",
        "isOnline": True,
    }
    try:
        supabase.table("profiles").upsert(payload).execute()
    except Exception:
        # Minimal fallback for stricter schemas.
        supabase.table("profiles").upsert({"id": NOMAD_AGENT_ID, "displayName": "Nomad"}).execute()


def _post_nomad_message(conversation_id: str, content: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("messages")
        .insert(
            {
                "chatId": conversation_id,
                "senderId": NOMAD_AGENT_ID,
                "content": content,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        .execute()
    )
    inserted = (resp.data or [None])[0]
    if not inserted:
        return
    message = _msg_to_api(inserted)
    publish_message_event(
        conversation_id,
        event_name="new-message",
        payload={
            "id": message["id"],
            "content": message["content"],
            "senderId": message["senderId"],
            "timestamp": message["timestamp"],
        },
    )


async def _call_diffy_shared_schedule_agent(
    *,
    chat_context: str,
    combined_agenda: str,
    prompt: str | None,
    user_id: str,
) -> str:
    workflow_url = "https://api.dify.ai/v1/workflows/run"
    headers = {
        "Authorization": f"Bearer {CHAT_WORKFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    # Keep input keys aligned with the workflow schema:
    # this scheduler flow expects only chatContext + combinedAgenda.
    effective_chat_context = chat_context
    if prompt and prompt.strip():
        effective_chat_context = f"{chat_context}\n\n[User scheduling intent]\n{prompt.strip()}"

    payload = {
        "inputs": {
            "chatContext": effective_chat_context,
            "combinedAgenda": combined_agenda,
        },
        "response_mode": "blocking",
        "user": user_id,
    }

    async with httpx.AsyncClient(timeout=45) as client:
        try:
            response = await client.post(workflow_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Diffy API transport error: {exc.__class__.__name__}: {str(exc)[:220]}",
            ) from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Diffy API error: {response.status_code} - {response.text[:700]}")

    data = response.json()
    return _extract_workflow_answer_text(data)


def _extract_workflow_answer_text(data: dict[str, Any]) -> str:
    workflow_data: Any = data.get("data")
    if isinstance(workflow_data, str):
        try:
            workflow_data = json.loads(workflow_data)
        except json.JSONDecodeError:
            pass
    if not isinstance(workflow_data, dict):
        # Some providers return the payload directly at the root.
        workflow_data = data
    if not isinstance(workflow_data, dict):
        raise HTTPException(status_code=502, detail="Diffy response missing workflow data")

    # Some workflows return data.events directly.
    data_events = workflow_data.get("events")
    if isinstance(data_events, str) and data_events.strip():
        _debug_log("chat_scheduler: using data.events as string")
        return data_events
    if isinstance(data_events, (dict, list)):
        _debug_log(f"chat_scheduler: using data.events as {type(data_events).__name__}")
        return json.dumps(data_events)

    outputs: Any = workflow_data.get("outputs")
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except json.JSONDecodeError:
            pass
    if not isinstance(outputs, dict):
        # Structured output can be directly in workflow_data.
        return json.dumps(workflow_data)

    # Match existing calendar flow behavior first: outputs.events.
    direct_events = outputs.get("events")
    if isinstance(direct_events, str) and direct_events.strip():
        _debug_log("chat_scheduler: using outputs.events as string")
        return direct_events
    if isinstance(direct_events, (dict, list)):
        _debug_log(f"chat_scheduler: using outputs.events as {type(direct_events).__name__}")
        return json.dumps(direct_events)

    preferred_keys = ["structured_outputObject", "output", "text", "answer", "result"]
    for key in preferred_keys:
        value = outputs.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        try:
            return json.dumps(value)
        except TypeError:
            continue

    for value in outputs.values():
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value)


    raise HTTPException(status_code=502, detail="Diffy API returned no usable scheduler output")


def _extract_generated_events(raw_text: str) -> list[dict[str, Any]]:
    parsed_any = _extract_json_payload(raw_text)
    candidate_list = _resolve_candidate_events(parsed_any)
    if not candidate_list:
        return []

    items: list[dict[str, Any]] = []
    dropped_missing_title = 0
    dropped_missing_date = 0
    dropped_not_dict = 0
    for candidate in candidate_list:
        if not isinstance(candidate, dict):
            dropped_not_dict += 1
            continue
        sanitized = _sanitize_generated_event(candidate)
        if not sanitized.get("title"):
            # Don't throw away useful proposals if title is omitted by the model.
            reason_hint = str(sanitized.get("reason") or "").strip()
            sanitized["title"] = reason_hint[:64] if reason_hint else "Proposed Event"
            dropped_missing_title += 1
        if not sanitized.get("date"):
            dropped_missing_date += 1
            continue
        items.append(sanitized)

    _debug_log(
        "chat_scheduler: extracted="
        f"{len(items)} dropped_not_dict={dropped_not_dict} "
        f"dropped_missing_title={dropped_missing_title} dropped_missing_date={dropped_missing_date}"
    )
    return items


def _resolve_candidate_events(parsed_any: Any) -> list[Any]:
    if isinstance(parsed_any, list):
        return parsed_any
    if not isinstance(parsed_any, dict):
        return []

    list_paths = (
        ("agenda",),
        ("events", "agenda"),
        ("events",),
        ("proposals",),
        ("items",),
        ("suggestions",),
        ("data", "events", "agenda"),
        ("data", "events"),
    )
    for path in list_paths:
        value = _get_nested(parsed_any, path)
        if isinstance(value, list):
            return value

    dict_paths = (
        ("events",),
        ("proposal",),
        ("event",),
    )
    for path in dict_paths:
        value = _get_nested(parsed_any, path)
        if isinstance(value, dict):
            return [value]

    return [parsed_any]


def _get_nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_json_payload(raw_text: str) -> Any:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    array_match = re.search(r"\[[\s\S]*\]", cleaned)
    if array_match:
        try:
            return json.loads(array_match.group())
        except json.JSONDecodeError:
            pass

    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        try:
            return json.loads(object_match.group())
        except json.JSONDecodeError:
            pass

    raise HTTPException(status_code=422, detail="Could not parse scheduler JSON from model response")


def _sanitize_generated_event(item: dict[str, Any]) -> dict[str, Any]:
    normalized_type = str(item.get("type") or item.get("eventType") or "").strip()
    if normalized_type not in {"class", "study", "social", "deadline", "custom"}:
        normalized_type = "custom"

    sanitized: dict[str, Any] = {
        "title": str(item.get("title") or item.get("name") or item.get("summary") or "").strip(),
        "date": str(item.get("date") or "").strip(),
        "startTime": str(item.get("startTime") or item.get("start") or "09:00").strip() or "09:00",
        "endTime": str(item.get("endTime") or item.get("end") or "10:00").strip() or "10:00",
        "type": normalized_type,
    }

    location = item.get("location")
    if location is not None:
        sanitized["location"] = str(location).strip()

    color = item.get("color")
    if color is not None:
        sanitized["color"] = str(color).strip()

    reason = item.get("reason")
    if reason is not None:
        sanitized["reason"] = str(reason).strip()

    return sanitized

