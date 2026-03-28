from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.core.config import AGENDA_WORKFLOW_API_KEY
from app.db.supabase import supabase

router = APIRouter(prefix="/calendar", tags=["Calendar"])
PROPOSAL_NOTIFICATION_TYPE = "calendar_proposal"


class CreateCalendarEventRequest(BaseModel):
    title: str
    date: str
    startTime: str
    endTime: str
    location: str | None = None
    type: str
    color: str | None = None


class UpdateCalendarEventRequest(BaseModel):
    title: str | None = None
    date: str | None = None
    startTime: str | None = None
    endTime: str | None = None
    location: str | None = None
    type: str | None = None
    color: str | None = None


class AgentChatScheduleRequest(BaseModel):
    agenda: str
    prompt: str | None = None


class CalendarProposalEvent(BaseModel):
    title: str
    date: str
    startTime: str
    endTime: str
    location: str | None = None
    type: str
    color: str | None = None


class CalendarProposal(BaseModel):
    id: str
    conversationId: str | None = None
    fromId: str | None = None
    reason: str | None = None
    event: CalendarProposalEvent
    createdAt: str | None = None


@router.get("/events")
def list_events(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    query = supabase.table("calendar_events").select("*").eq("userId", user_id)
    if start:
        query = query.gte("startAt", start)
    if end:
        query = query.lte("endAt", end)
    rows = query.order("startAt", desc=False).execute().data or []
    mapped = [_row_to_api(r) for r in rows]
    return {"items": mapped, "total": len(mapped)}


@router.post("/events", status_code=201)
def create_event(body: CreateCalendarEventRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    start_at = f"{body.date}T{body.startTime}:00Z"
    end_at = f"{body.date}T{body.endTime}:00Z"
    resp = (
        supabase.table("calendar_events")
        .insert(
            {
                "userId": user_id,
                "title": body.title,
                "date": body.date,
                "startTime": body.startTime,
                "endTime": body.endTime,
                "startAt": start_at,
                "endAt": end_at,
                "location": body.location,
                "type": body.type,
                "color": body.color or "",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create event")
    return _row_to_api(resp.data[0])


@router.patch("/events/{eventId}")
def update_event(eventId: str, body: UpdateCalendarEventRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    current = (
        supabase.table("calendar_events")
        .select("*")
        .eq("id", eventId)
        .eq("userId", user_id)
        .single()
        .execute()
        .data
    )
    if not current:
        raise HTTPException(status_code=404, detail="Event not found")

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if payload.get("date") or payload.get("startTime"):
        date = payload.get("date") or current.get("date")
        start_time = payload.get("startTime") or current.get("startTime")
        payload["startAt"] = f"{date}T{start_time}:00Z"
    if payload.get("date") or payload.get("endTime"):
        date = payload.get("date") or current.get("date")
        end_time = payload.get("endTime") or current.get("endTime")
        payload["endAt"] = f"{date}T{end_time}:00Z"
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()

    resp = supabase.table("calendar_events").update(payload).eq("id", eventId).eq("userId", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Event not found")
    return _row_to_api(resp.data[0])


@router.delete("/events/{eventId}", status_code=204)
def delete_event(eventId: str, user_id: str = Depends(get_current_user_id)) -> None:
    row = (
        supabase.table("calendar_events")
        .select("id")
        .eq("id", eventId)
        .eq("userId", user_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    supabase.table("calendar_events").delete().eq("id", eventId).eq("userId", user_id).execute()
    return None


@router.post("/events/agent-chat-schedule")
async def agent_chat_schedule(
    body: AgentChatScheduleRequest,
    user_id: str = Depends(get_current_user_id),
) -> list[dict[str, Any]]:
    if not AGENDA_WORKFLOW_API_KEY:
        raise HTTPException(status_code=503, detail="AGENDA_SCHEDULER_KEY not configured")

    if not body.agenda.strip():
        return []

    raw_answer = await _call_diffy_schedule_agent(
        agenda=body.agenda,
        prompt=body.prompt or "Suggest additional agenda events based on the current schedule.",
        user_id=user_id,
    )
    parsed = _extract_json_array(raw_answer)
    return [_sanitize_event_request(item) for item in parsed if isinstance(item, dict)]


@router.get("/proposals")
def list_calendar_proposals(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    rows = (
        supabase.table("notifications")
        .select("*")
        .eq("userId", user_id)
        .eq("type", PROPOSAL_NOTIFICATION_TYPE)
        .eq("read", False)
        .order("createdAt", desc=True)
        .execute()
        .data
    ) or []

    items: list[dict[str, Any]] = []
    for row in rows:
        parsed = _proposal_from_notification_row(row)
        if parsed is not None:
            items.append(parsed.model_dump())
    return {"items": items, "total": len(items)}


@router.post("/proposals/{proposalId}/accept", status_code=201)
def accept_calendar_proposal(proposalId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    row = (
        supabase.table("notifications")
        .select("*")
        .eq("id", proposalId)
        .eq("userId", user_id)
        .eq("type", PROPOSAL_NOTIFICATION_TYPE)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = _proposal_from_notification_row(row)
    if proposal is None:
        raise HTTPException(status_code=422, detail="Invalid proposal payload")

    now = datetime.now(timezone.utc).isoformat()
    event = proposal.event
    start_at = f"{event.date}T{event.startTime}:00Z"
    end_at = f"{event.date}T{event.endTime}:00Z"

    resp = (
        supabase.table("calendar_events")
        .insert(
            {
                "userId": user_id,
                "title": event.title,
                "date": event.date,
                "startTime": event.startTime,
                "endTime": event.endTime,
                "startAt": start_at,
                "endAt": end_at,
                "location": event.location,
                "type": event.type,
                "color": event.color or "",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create event from proposal")

    supabase.table("notifications").update({"read": True, "readAt": now}).eq("id", proposalId).eq("userId", user_id).execute()
    return _row_to_api(resp.data[0])


@router.post("/proposals/{proposalId}/dismiss", status_code=204)
def dismiss_calendar_proposal(proposalId: str, user_id: str = Depends(get_current_user_id)) -> None:
    row = (
        supabase.table("notifications")
        .select("id")
        .eq("id", proposalId)
        .eq("userId", user_id)
        .eq("type", PROPOSAL_NOTIFICATION_TYPE)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found")
    supabase.table("notifications").update({"read": True, "readAt": datetime.now(timezone.utc).isoformat()}).eq("id", proposalId).eq("userId", user_id).execute()
    return None


def _row_to_api(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "title": r.get("title") or "",
        "date": r.get("date"),
        "startTime": r.get("startTime"),
        "endTime": r.get("endTime"),
        "location": r.get("location"),
        "type": r.get("type"),
        "color": r.get("color") or "",
    }


async def _call_diffy_schedule_agent(*, agenda: str, prompt: str, user_id: str) -> str:
    dify_base_url = "https://api.dify.ai/v1"
    workflow_url = f"{dify_base_url}/workflows/run"
    headers = {
        "Authorization": f"Bearer {AGENDA_WORKFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {
            "events": agenda,
            "prompt": prompt,
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
    answer = _extract_workflow_text_answer(data)
    if answer.strip():
        return answer
    raise HTTPException(status_code=502, detail="Diffy API returned no textual output in workflow outputs")


def _extract_workflow_text_answer(data: dict[str, Any]) -> str:
    workflow_data = data.get("data")
    if not isinstance(workflow_data, dict):
        raise HTTPException(status_code=502, detail="Diffy response missing workflow data")

    # Support both data.events and data.outputs.events formats.
    direct_events = workflow_data.get("events")
    if isinstance(direct_events, str) and direct_events.strip():
        return direct_events
    if isinstance(direct_events, (list, dict)):
        return json.dumps(direct_events)


    outputs = workflow_data.get("outputs")
    if isinstance(outputs, dict):
        output_events = outputs.get("events")
        if isinstance(output_events, str) and output_events.strip():
            return output_events
        if isinstance(output_events, (list, dict)):
            return json.dumps(output_events)

    raise HTTPException(status_code=502, detail="Diffy response missing events payload")


def _extract_json_array(raw_text: str) -> list[Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        raise HTTPException(status_code=422, detail="Could not parse event array from Diffy response")
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON array returned by Diffy") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="Diffy response was not a JSON array")
    return parsed


def _sanitize_event_request(item: dict[str, Any]) -> dict[str, Any]:
    normalized_type = str(item.get("type") or "").strip()
    if normalized_type not in {"class", "study", "social", "deadline", "custom"}:
        normalized_type = "custom"

    sanitized: dict[str, Any] = {
        "title": str(item.get("title") or "").strip(),
        "date": str(item.get("date") or "").strip(),
        "startTime": str(item.get("startTime") or "").strip(),
        "endTime": str(item.get("endTime") or "").strip(),
        "type": normalized_type,
    }

    location = item.get("location")
    if location is not None:
        sanitized["location"] = str(location).strip()

    color = item.get("color")
    if color is not None:
        sanitized["color"] = str(color).strip()

    return sanitized


def _proposal_from_notification_row(row: dict[str, Any]) -> CalendarProposal | None:
    content = row.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    event_payload = payload.get("event")
    if not isinstance(event_payload, dict):
        return None
    event_sanitized = _sanitize_event_request(event_payload)
    if not event_sanitized.get("title") or not event_sanitized.get("date"):
        return None

    return CalendarProposal(
        id=str(row.get("id")),
        conversationId=payload.get("conversationId"),
        fromId=row.get("fromId"),
        reason=payload.get("reason"),
        event=CalendarProposalEvent(
            title=event_sanitized["title"],
            date=event_sanitized["date"],
            startTime=event_sanitized["startTime"] or "09:00",
            endTime=event_sanitized["endTime"] or "10:00",
            location=event_sanitized.get("location"),
            type=event_sanitized["type"],
            color=event_sanitized.get("color"),
        ),
        createdAt=row.get("createdAt"),
    )

