from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Response

from ..db import supabase
from ..helpers import current_user_id, map_course_row, map_post_row, map_profile_to_user, now_iso
from ..schemas import (
    CalendarEvent,
    Community,
    Conversation,
    CreateCalendarEventRequest,
    CreateConversationRequest,
    CreateMessageRequest,
    Message,
    Notification,
    OnboardingCompleteRequest,
    SearchResponse,
    UpdateCalendarEventRequest,
    User,
)

router = APIRouter()


@router.get("/messages/conversations")
def list_conversations(q: Optional[str] = None):
    rows = supabase.table("chats").select("*").execute().data or []
    items = []
    for row in rows:
        cid = row["id"]
        part_rows = (
            supabase.table("chat_participants").select("userId").eq("chatId", cid).execute().data or []
        )
        participants = [p["userId"] for p in part_rows]
        last_msg = (
            supabase.table("messages")
            .select("*")
            .eq("chatId", cid)
            .order("createdAt", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        last_text = last_msg[0]["content"] if last_msg else ""
        last_ts = last_msg[0].get("createdAt") if last_msg else None
        conversation = Conversation(
            id=cid,
            participants=participants,
            isGroup=(row.get("type") == "group"),
            groupName=row.get("groupName"),
            lastMessage=last_text,
            lastTimestamp=last_ts,
            unread=0,
        )
        if not q or q.lower() in (conversation.groupName or "").lower() or q.lower() in last_text.lower():
            items.append(conversation)
    return {"items": items}


@router.post("/messages/conversations", response_model=Conversation, status_code=201)
def create_conversation(body: CreateConversationRequest):
    chat_type = "group" if body.isGroup else "direct"
    rs = supabase.table("chats").insert({"type": chat_type}).execute()
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=400, detail="Unable to create conversation")
    for uid in body.participants:
        supabase.table("chat_participants").insert({"chatId": row["id"], "userId": uid}).execute()
    return Conversation(
        id=row["id"],
        participants=body.participants,
        isGroup=body.isGroup,
        groupName=body.groupName,
        lastMessage="",
        lastTimestamp=None,
        unread=0,
    )


@router.get("/messages/conversations/{conversationId}/messages")
def list_messages(conversationId: str):
    rows = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", conversationId)
        .order("createdAt", desc=False)
        .execute()
        .data
        or []
    )
    items = [
        Message(
            id=r["id"],
            senderId=r["senderId"],
            content=r["content"],
            timestamp=r.get("createdAt") or now_iso(),
        )
        for r in rows
    ]
    return {"items": items}


@router.post("/messages/conversations/{conversationId}/messages", response_model=Message, status_code=201)
def send_message(conversationId: str, body: CreateMessageRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rs = (
        supabase.table("messages")
        .insert({"chatId": conversationId, "senderId": uid, "content": body.content})
        .execute()
    )
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=400, detail="Unable to send message")
    return Message(
        id=row["id"],
        senderId=row["senderId"],
        content=row["content"],
        timestamp=row.get("createdAt") or now_iso(),
    )


@router.get("/calendar/events")
def list_events(start: Optional[str] = None, end: Optional[str] = None):
    rows = supabase.table("user_term_plans").select("*").execute().data or []
    items = []
    for row in rows:
        event = CalendarEvent(
            id=row["id"],
            title=row.get("title") or "Untitled",
            date=(row.get("termCode") or "1970-01-01")[:10],
            startTime=row.get("startTime") or "09:00",
            endTime=row.get("endTime") or "10:00",
            location=row.get("location"),
            type=row.get("type") or "custom",
            color=row.get("color") or "#4f46e5",
        )
        if start and event.date < start[:10]:
            continue
        if end and event.date > end[:10]:
            continue
        items.append(event)
    return {"items": items}


@router.post("/calendar/events", response_model=CalendarEvent, status_code=201)
def create_event(body: CreateCalendarEventRequest):
    rs = (
        supabase.table("user_term_plans")
        .insert(
            {
                "termCode": body.date,
                "title": body.title,
                "startTime": body.startTime,
                "endTime": body.endTime,
                "location": body.location,
                "type": body.type,
                "status": "active",
            }
        )
        .execute()
    )
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=400, detail="Unable to create event")
    return CalendarEvent(
        id=row["id"],
        title=row.get("title") or body.title,
        date=body.date,
        startTime=body.startTime,
        endTime=body.endTime,
        location=body.location,
        type=body.type,
        color=row.get("color") or "#4f46e5",
    )


@router.patch("/calendar/events/{eventId}", response_model=CalendarEvent)
def update_event(eventId: str, body: UpdateCalendarEventRequest):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if "date" in payload:
        payload["termCode"] = payload.pop("date")
    rs = supabase.table("user_term_plans").update(payload).eq("id", eventId).execute()
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    return CalendarEvent(
        id=row["id"],
        title=row.get("title") or "",
        date=(row.get("termCode") or "1970-01-01")[:10],
        startTime=row.get("startTime") or "09:00",
        endTime=row.get("endTime") or "10:00",
        location=row.get("location"),
        type=row.get("type") or "custom",
        color=row.get("color") or "#4f46e5",
    )


@router.delete("/calendar/events/{eventId}", status_code=204)
def delete_event(eventId: str):
    supabase.table("user_term_plans").delete().eq("id", eventId).execute()
    return Response(status_code=204)


@router.get("/notifications")
def list_notifications():
    rows = (
        supabase.table("notifications")
        .select("*")
        .order("createdAt", desc=True)
        .execute()
        .data
        or []
    )
    items = [
        Notification(
            id=r["id"],
            type=r.get("type") or "mention",
            fromId=r.get("fromId") or "",
            content=r.get("content") or "",
            timestamp=r.get("createdAt") or now_iso(),
            read=bool(r.get("read") or False),
        )
        for r in rows
    ]
    unread = sum(1 for item in items if not item.read)
    return {"items": items, "unread": unread}


@router.post("/notifications/read-all", status_code=204)
def read_all_notifications():
    supabase.table("notifications").update({"read": True}).neq("id", "").execute()
    return Response(status_code=204)


@router.post("/notifications/{notificationId}/read", status_code=204)
def read_one_notification(notificationId: str):
    supabase.table("notifications").update({"read": True}).eq("id", notificationId).execute()
    return Response(status_code=204)


@router.get("/onboarding/options")
def onboarding_options():
    schools = supabase.table("schools").select("name").execute().data or []
    majors_rows = supabase.table("programs").select("departmentName").execute().data or []
    universities = sorted({s.get("name", "") for s in schools if s.get("name")})
    majors = sorted({m.get("departmentName", "") for m in majors_rows if m.get("departmentName")})
    interests = ["AI", "Startups", "Web Development", "Data Science", "Robotics", "Design"]
    return {"universities": universities, "majors": majors, "interests": interests}


@router.post("/onboarding/complete", response_model=User)
def complete_onboarding(body: OnboardingCompleteRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = {
        "displayName": body.fullName,
        "university": body.university,
        "major": body.majors[0] if body.majors else "",
        "minor": body.minors[0] if body.minors else None,
        "interests": body.interests,
    }
    rs = supabase.table("profiles").update(payload).eq("id", uid).execute()
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return map_profile_to_user(row)


@router.get("/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=1)):
    q_like = f"%{q}%"
    users_rows = (
        supabase.table("profiles")
        .select("*")
        .or_(f"displayName.ilike.{q_like},email.ilike.{q_like}")
        .limit(10)
        .execute()
        .data
        or []
    )
    users = [map_profile_to_user(r) for r in users_rows]
    course_rows = (
        supabase.table("courses")
        .select("*")
        .or_(f"canonicalName.ilike.{q_like},canonicalCode.ilike.{q_like}")
        .limit(10)
        .execute()
        .data
        or []
    )
    courses = [map_course_row(r) for r in course_rows]
    community_rows = (
        supabase.table("communities")
        .select("*")
        .ilike("name", q_like)
        .limit(10)
        .execute()
        .data
        or []
    )
    communities = [
        Community(
            id=r["id"],
            name=r.get("name") or "",
            description=r.get("introduction") or "",
            icon=r.get("icon") or "",
            color=r.get("color") or "#000000",
        )
        for r in community_rows
    ]
    post_rows = (
        supabase.table("posts")
        .select("*")
        .or_(f"title.ilike.{q_like},content.ilike.{q_like}")
        .limit(10)
        .execute()
        .data
        or []
    )
    posts = [map_post_row(r) for r in post_rows]
    return SearchResponse(users=users, courses=courses, communities=communities, posts=posts)
