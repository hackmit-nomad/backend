from fastapi import Header, HTTPException
from postgrest.exceptions import APIError

from app.db.supabase import supabase


def _lookup_profile_id(candidate: str) -> str | None:
    value = (candidate or "").strip()
    if not value:
        return None

    # Some deployments store profile/auth linkage with different column names.
    for column in ("id", "userId", "authUserId", "auth_user_id"):
        try:
            rows = (
                supabase.table("profiles")
                .select("id")
                .eq(column, value)
                .limit(1)
                .execute()
                .data
            ) or []
        except APIError:
            continue
        if rows and rows[0].get("id"):
            return str(rows[0]["id"])
    return None


def get_current_user_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str:
    """
    Resolve current user from JWT passed as:
    Authorization: Bearer <access_token>
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization must be: Bearer <token>")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        user_resp = supabase.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user = getattr(user_resp, "user", None)
    if not user or not getattr(user, "id", None):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    auth_user_id = str(user.id)
    resolved_profile_id = _lookup_profile_id(auth_user_id)
    if not resolved_profile_id:
        # First authenticated call after signup: ensure app profile exists.
        try:
            supabase.table("profiles").upsert({"id": auth_user_id}).execute()
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Failed to initialize user profile") from exc
        resolved_profile_id = auth_user_id

    # Optional pass-through header from frontend is allowed, but cannot override token identity.
    if x_user_id and x_user_id != resolved_profile_id:
        raise HTTPException(status_code=401, detail="Token subject does not match X-User-Id")

    return resolved_profile_id


def get_user_id_from_access_token(token: str) -> str:
    """Validate JWT access token and return Supabase user id (for WebSocket query auth)."""
    if not token or not token.strip():
        raise ValueError("Missing token")
    try:
        user_resp = supabase.auth.get_user(token.strip())
    except Exception as exc:
        raise ValueError("Invalid or expired token") from exc
    user = getattr(user_resp, "user", None)
    if not user or not getattr(user, "id", None):
        raise ValueError("Invalid token payload")
    return str(user.id)

