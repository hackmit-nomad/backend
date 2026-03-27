from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/calendar", tags=["Calendar"])


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
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if payload.get("date") or payload.get("startTime"):
        date = payload.get("date") or supabase.table("calendar_events").select("date").eq("id", eventId).single().execute().data.get("date")
        start_time = payload.get("startTime") or supabase.table("calendar_events").select("startTime").eq("id", eventId).single().execute().data.get("startTime")
        payload["startAt"] = f"{date}T{start_time}:00Z"
    if payload.get("date") or payload.get("endTime"):
        date = payload.get("date") or supabase.table("calendar_events").select("date").eq("id", eventId).single().execute().data.get("date")
        end_time = payload.get("endTime") or supabase.table("calendar_events").select("endTime").eq("id", eventId).single().execute().data.get("endTime")
        payload["endAt"] = f"{date}T{end_time}:00Z"
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()

    resp = supabase.table("calendar_events").update(payload).eq("id", eventId).eq("userId", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Event not found")
    return _row_to_api(resp.data[0])


@router.delete("/events/{eventId}", status_code=204)
def delete_event(eventId: str, user_id: str = Depends(get_current_user_id)) -> None:
    supabase.table("calendar_events").delete().eq("id", eventId).eq("userId", user_id).execute()
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

