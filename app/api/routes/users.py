from __future__ import annotations

import math
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from postgrest.exceptions import APIError

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(tags=["Users"])


class UpdateUserRequest(BaseModel):
    name: str | None = None
    bio: str | None = None
    headline: str | None = None
    major: str | None = None
    minor: str | None = None
    year: str | None = None
    interests: list[str] | None = None
    tags: list[str] | None = None
    university: str | None = None


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return _profile_to_user(resp.data, "none")


@router.patch("/me")
def update_me(body: UpdateUserRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body.name is not None:
        payload["displayName"] = body.name
    if body.bio is not None:
        payload["bio"] = body.bio
    if body.headline is not None:
        payload["headline"] = body.headline
    if body.major is not None:
        payload["major"] = body.major
    if body.minor is not None:
        payload["minor"] = body.minor
    if body.year is not None:
        payload["year"] = body.year
    if body.university is not None:
        payload["university"] = body.university
    if body.interests is not None:
        payload["interests"] = body.interests
    if body.tags is not None:
        payload["tags"] = body.tags

    if not payload:
        current = supabase.table("profiles").select("*").eq("id", user_id).single().execute().data
        if not current:
            raise HTTPException(status_code=404, detail="User not found")
        return _profile_to_user(current, "none")

    try:
        resp = supabase.table("profiles").update(payload).eq("id", user_id).execute()
    except APIError as exc:
        # Backward-compatible path for databases that don't have profiles.tags yet.
        if "tags" in payload and "tags" in str(exc):
            fallback_payload = {k: v for k, v in payload.items() if k != "tags"}
            if not fallback_payload:
                current = supabase.table("profiles").select("*").eq("id", user_id).single().execute().data
                if not current:
                    raise HTTPException(status_code=404, detail="User not found")
                return _profile_to_user(current, "none")
            resp = supabase.table("profiles").update(fallback_payload).eq("id", user_id).execute()
        else:
            raise

    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return _profile_to_user(resp.data[0], "none")


@router.delete("/me", status_code=204)
def delete_me(user_id: str = Depends(get_current_user_id)) -> None:
    row = supabase.table("profiles").select("id").eq("id", user_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    supabase.table("profiles").delete().eq("id", user_id).execute()
    return None


@router.get("/users")
def list_users(
    q: str | None = Query(default=None),
    university: str | None = Query(default=None),
    major: str | None = Query(default=None),
    year: str | None = Query(default=None),
    connected: bool | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    query = supabase.table("profiles").select("*")

    if q:
        # Best-effort: match displayName or email
        query = query.or_(f"displayName.ilike.%{q}%,email.ilike.%{q}%")
    if university:
        query = query.eq("university", university)
    if major:
        query = query.eq("major", major)
    if year:
        query = query.eq("year", year)

    profiles_resp = query.execute()
    items = profiles_resp.data or []
    status_by_user = _connection_status_map(user_id)

    if connected is not None:
        connected_ids = {friend_id for friend_id, status in status_by_user.items() if status == "connected"}
        if connected:
            items = [p for p in items if p["id"] in connected_ids]
        else:
            items = [p for p in items if p["id"] not in connected_ids]

    return {
        "items": [_profile_to_user(p, status_by_user.get(p["id"], "none")) for p in items],
        "total": len(items),
    }


@router.get("/users/friends")
def list_friends(
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Return the current user's connections grouped by status."""
    rows = (
        supabase.table("friendships")
        .select("friendId,status")
        .eq("userId", user_id)
        .execute()
    ).data or []

    connected_ids: list[str] = []
    pending_ids: list[str] = []
    incoming_ids: list[str] = []

    for row in rows:
        fid = row.get("friendId")
        status = row.get("status")
        if not fid:
            continue
        if status == "connected":
            connected_ids.append(fid)
        elif status == "pending":
            pending_ids.append(fid)
        elif status == "incoming":
            incoming_ids.append(fid)

    def _load_profiles(ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        resp = supabase.table("profiles").select("*").in_("id", ids).execute()
        return resp.data or []

    connected_profiles = _load_profiles(connected_ids)
    pending_profiles = _load_profiles(pending_ids)
    incoming_profiles = _load_profiles(incoming_ids)

    return {
        "connected": [_profile_to_user(p, "connected") for p in connected_profiles],
        "pending": [_profile_to_user(p, "pending") for p in pending_profiles],
        "incoming": [_profile_to_user(p, "incoming") for p in incoming_profiles],
    }


def _build_feature_vector(profile: dict[str, Any], vocabulary: dict[str, int], idf: dict[str, float]) -> list[float]:
    """Build a TF-IDF weighted feature vector for a user profile.

    Features are derived from tags (weight 2x), interests (weight 1.5x),
    courses, and university — giving higher importance to skill-based matching.
    """
    vec = [0.0] * len(vocabulary)

    # Tags get highest weight (skill-based matching is most relevant)
    for tag in (profile.get("tags") or []):
        t = f"tag:{tag.lower().strip()}"
        if t in vocabulary:
            vec[vocabulary[t]] = 2.0 * idf.get(t, 1.0)

    # Interests get strong weight
    for interest in (profile.get("interests") or []):
        t = f"interest:{interest.lower().strip()}"
        if t in vocabulary:
            vec[vocabulary[t]] = 1.5 * idf.get(t, 1.0)

    # Courses
    for course in (profile.get("courses") or []):
        t = f"course:{course}"
        if t in vocabulary:
            vec[vocabulary[t]] = 1.0 * idf.get(t, 1.0)

    # University
    uni = (profile.get("university") or "").strip()
    if uni:
        t = f"uni:{uni.lower()}"
        if t in vocabulary:
            vec[vocabulary[t]] = 1.0 * idf.get(t, 1.0)

    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@router.get("/users/suggestions")
def suggest_users(
    limit: int = Query(default=10),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Return users ranked by cosine similarity across tags, interests, courses, and university.

    Uses TF-IDF weighted feature vectors with cosine similarity for matching.
    Tags and interests are weighted higher than courses/university to prioritize
    skill and personality alignment.
    """
    me_resp = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
    me_profile = me_resp.data or {}

    # All friendship edges for this user (any status).
    edges = (
        supabase.table("friendships")
        .select("friendId")
        .eq("userId", user_id)
        .execute()
    ).data or []
    excluded_ids = {user_id} | {e["friendId"] for e in edges if e.get("friendId")}

    all_resp = supabase.table("profiles").select("*").execute()
    all_profiles = all_resp.data or []
    candidates = [p for p in all_profiles if p["id"] not in excluded_ids]

    if not candidates:
        return {"items": [], "total": 0}

    # Build vocabulary from ALL profiles (including self) for proper IDF calculation
    doc_freq: Counter[str] = Counter()
    n_docs = len(all_profiles)

    for p in all_profiles:
        terms_in_doc: set[str] = set()
        for tag in (p.get("tags") or []):
            terms_in_doc.add(f"tag:{tag.lower().strip()}")
        for interest in (p.get("interests") or []):
            terms_in_doc.add(f"interest:{interest.lower().strip()}")
        for course in (p.get("courses") or []):
            terms_in_doc.add(f"course:{course}")
        uni = (p.get("university") or "").strip()
        if uni:
            terms_in_doc.add(f"uni:{uni.lower()}")
        for term in terms_in_doc:
            doc_freq[term] += 1

    # Build vocabulary index and IDF weights
    vocabulary: dict[str, int] = {term: i for i, term in enumerate(sorted(doc_freq.keys()))}
    idf: dict[str, float] = {
        term: math.log((1 + n_docs) / (1 + freq)) + 1
        for term, freq in doc_freq.items()
    }

    # Build feature vector for current user
    my_vec = _build_feature_vector(me_profile, vocabulary, idf)

    # Score each candidate by cosine similarity
    scored: list[tuple[float, dict[str, Any]]] = []
    for p in candidates:
        cand_vec = _build_feature_vector(p, vocabulary, idf)
        sim = _cosine_similarity(my_vec, cand_vec)
        scored.append((sim, p))

    # Sort by similarity descending
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    items = []
    for sim_score, p in top:
        user = _profile_to_user(p, "none")
        user["similarityScore"] = round(sim_score, 4)
        items.append(user)

    return {
        "items": items,
        "total": len(candidates),
    }


@router.get("/users/{userId}")
def get_user_profile(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("profiles").select("*").eq("id", userId).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")

    # These are not represented in the current DB schema; return empty lists for MVP.
    user = _profile_to_user(resp.data, _connection_status(me_id, userId))
    return {**user, "skills": [], "experience": []}


@router.post("/users/{userId}/connect")
def connect_user(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    if userId == me_id:
        raise HTTPException(status_code=400, detail="Cannot connect to self")

    # Check if other user already sent us a request — auto-accept.
    reverse = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []
    if reverse and reverse[0].get("status") == "incoming":
        _set_connected(me_id, userId)
        return {"userId": userId, "status": "connected"}

    # Otherwise create a pending outgoing / incoming pair.
    _upsert_edge(me_id, userId, "pending")
    _upsert_edge(userId, me_id, "incoming")
    return {"userId": userId, "status": "pending"}


@router.post("/users/{userId}/connect/accept")
def accept_connection(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    incoming = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []
    if not incoming or incoming[0].get("status") not in ("incoming", "pending"):
        raise HTTPException(status_code=404, detail="No pending request from this user")

    _set_connected(me_id, userId)
    return {"userId": userId, "status": "connected"}


@router.post("/users/{userId}/connect/reject")
def reject_connection(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _remove_both_edges(me_id, userId)
    return {"userId": userId, "status": "none"}


@router.delete("/users/{userId}/connect")
def disconnect_user(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _remove_both_edges(me_id, userId)
    return {"userId": userId, "status": "none"}


def _set_connected(user_a: str, user_b: str) -> None:
    _upsert_edge(user_a, user_b, "connected")
    _upsert_edge(user_b, user_a, "connected")


def _upsert_edge(user_a: str, user_b: str, status: str) -> None:
    existing = (
        supabase.table("friendships")
        .select("id")
        .eq("userId", user_a)
        .eq("friendId", user_b)
        .execute()
    ).data or []
    if existing:
        supabase.table("friendships").update({"status": status}).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("friendships").insert({"userId": user_a, "friendId": user_b, "status": status}).execute()


def _remove_both_edges(user_a: str, user_b: str) -> None:
    supabase.table("friendships").delete().eq("userId", user_a).eq("friendId", user_b).execute()
    supabase.table("friendships").delete().eq("userId", user_b).eq("friendId", user_a).execute()


def _connection_status_map(user_id: str) -> dict[str, str]:
    direct = (
        supabase.table("friendships").select("friendId,status").eq("userId", user_id).execute()
    ).data or []
    reverse = (
        supabase.table("friendships").select("userId,status").eq("friendId", user_id).execute()
    ).data or []

    status_by_user: dict[str, str] = {}
    for row in direct:
        friend_id = row.get("friendId")
        if friend_id:
            status_by_user[friend_id] = row.get("status") or "none"
    for row in reverse:
        friend_id = row.get("userId")
        if friend_id and friend_id not in status_by_user:
            status_by_user[friend_id] = row.get("status") or "none"
    return status_by_user


def _connection_status(me_id: str, other_id: str) -> str:
    if me_id == other_id:
        return "none"
    return _connection_status_map(me_id).get(other_id, "none")


def _profile_to_user(p: dict[str, Any], connection_status: str = "none") -> dict[str, Any]:
    return {
        "id": p["id"],
        "name": p.get("displayName") or "",
        "avatar": p.get("avatarUrl") or "",
        "university": p.get("university") or "",
        "major": p.get("major") or "",
        "minor": p.get("minor"),
        "year": p.get("year") or "",
        "bio": p.get("bio") or "",
        "headline": p.get("headline"),
        "interests": p.get("interests") or [],
        "tags": p.get("tags") or [],
        "courses": p.get("courses") or [],
        "communities": p.get("communities") or [],
        "isConnected": connection_status == "connected",
        "isOnline": bool(p.get("isOnline")) if "isOnline" in p else False,
        "profileViews": int(p.get("profileViews") or 0),
    }

