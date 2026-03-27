from fastapi import Header, HTTPException

from app.db.supabase import supabase


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

    resolved_user_id = str(user.id)

    # Optional pass-through header from frontend is allowed, but cannot override token identity.
    if x_user_id and x_user_id != resolved_user_id:
        raise HTTPException(status_code=401, detail="Token subject does not match X-User-Id")

    return resolved_user_id

