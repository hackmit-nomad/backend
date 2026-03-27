from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException

from ..db import supabase
from ..helpers import current_user_id, get_connection_status, map_profile_to_user
from ..schemas import (
    AuthResponse,
    ConnectionStatusResponse,
    LoginRequest,
    SignupRequest,
    UpdateUserRequest,
    User,
    UserProfile,
)

router = APIRouter()


@router.get("/")
def root():
    return {"message": "nomad v1.0.0"}


@router.post("/auth/signup", response_model=AuthResponse, status_code=201)
def auth_signup(body: SignupRequest):
    try:
        auth_resp = supabase.auth.sign_up({"email": body.email, "password": body.password})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = auth_resp.user
    if not user:
        raise HTTPException(status_code=400, detail="Signup failed")

    supabase.table("profiles").upsert(
        {"id": user.id, "email": body.email, "displayName": body.name}
    ).execute()
    profile = supabase.table("profiles").select("*").eq("id", user.id).single().execute().data
    return AuthResponse(
        accessToken=auth_resp.session.access_token if auth_resp.session else "",
        refreshToken=auth_resp.session.refresh_token if auth_resp.session else None,
        user=map_profile_to_user(profile or {"id": user.id, "displayName": body.name}),
    )


@router.post("/auth/login", response_model=AuthResponse)
def auth_login(body: LoginRequest):
    try:
        auth_resp = supabase.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not auth_resp.session or not auth_resp.session.user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    uid = auth_resp.session.user.id
    profile = supabase.table("profiles").select("*").eq("id", uid).single().execute().data
    return AuthResponse(
        accessToken=auth_resp.session.access_token,
        refreshToken=auth_resp.session.refresh_token,
        user=map_profile_to_user(profile or {"id": uid, "displayName": ""}),
    )


@router.post("/auth/logout", status_code=204)
def auth_logout():
    supabase.auth.sign_out()
    return None


@router.get("/me", response_model=User)
def get_me(authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    profile = supabase.table("profiles").select("*").eq("id", uid).single().execute().data
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return map_profile_to_user(profile)


@router.patch("/me", response_model=User)
def patch_me(body: UpdateUserRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in payload:
        payload["displayName"] = payload.pop("name")
    rs = supabase.table("profiles").update(payload).eq("id", uid).execute()
    if not rs.data:
        raise HTTPException(status_code=404, detail="User not found")
    return map_profile_to_user(rs.data[0])


@router.get("/users")
def list_users(
    q: Optional[str] = None,
    university: Optional[str] = None,
    major: Optional[str] = None,
    year: Optional[str] = None,
    connected: Optional[bool] = None,
    authorization: Optional[str] = Header(default=None),
):
    uid = current_user_id(authorization)
    query = supabase.table("profiles").select("*")
    if q:
        query = query.or_(f"displayName.ilike.%{q}%,email.ilike.%{q}%")
    if university:
        query = query.eq("university", university)
    if major:
        query = query.eq("major", major)
    if year:
        query = query.eq("year", year)
    rows = query.execute().data or []
    items: List[User] = []
    for row in rows:
        status = get_connection_status(uid, row["id"])
        user_obj = map_profile_to_user(row, connected=(status == "connected"))
        if connected is None or user_obj.isConnected == connected:
            items.append(user_obj)
    return {"items": items, "total": len(items)}


@router.get("/users/{userId}", response_model=UserProfile)
def get_user(userId: str, authorization: Optional[str] = Header(default=None)):
    row = supabase.table("profiles").select("*").eq("id", userId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    uid = current_user_id(authorization)
    status = get_connection_status(uid, userId)
    base = map_profile_to_user(row, connected=(status == "connected"))
    return UserProfile(**base.model_dump(), skills=[], experience=[])


@router.post("/users/{userId}/connect", response_model=ConnectionStatusResponse)
def connect_user(userId: str, authorization: Optional[str] = Header(default=None)):
    me = current_user_id(authorization)
    if not me:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if userId == me:
        return ConnectionStatusResponse(userId=userId, status="connected")
    existing = (
        supabase.table("friendships")
        .select("*")
        .or_(f"and(userId.eq.{me},friendId.eq.{userId}),and(userId.eq.{userId},friendId.eq.{me})")
        .limit(1)
        .execute()
        .data
    )
    if existing:
        row = existing[0]
        if row.get("status") == "pending" and row.get("userId") == userId:
            supabase.table("friendships").update({"status": "accepted"}).eq("id", row["id"]).execute()
            return ConnectionStatusResponse(userId=userId, status="connected")
        return ConnectionStatusResponse(userId=userId, status=get_connection_status(me, userId))
    supabase.table("friendships").insert({"userId": me, "friendId": userId, "status": "pending"}).execute()
    return ConnectionStatusResponse(userId=userId, status="pending")


@router.delete("/users/{userId}/connect", response_model=ConnectionStatusResponse)
def disconnect_user(userId: str, authorization: Optional[str] = Header(default=None)):
    me = current_user_id(authorization)
    if not me:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rel = (
        supabase.table("friendships")
        .select("id")
        .or_(f"and(userId.eq.{me},friendId.eq.{userId}),and(userId.eq.{userId},friendId.eq.{me})")
        .execute()
    )
    for row in rel.data or []:
        supabase.table("friendships").delete().eq("id", row["id"]).execute()
    return ConnectionStatusResponse(userId=userId, status="none")
