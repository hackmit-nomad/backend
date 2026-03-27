from fastapi import Header, HTTPException, Request


def get_current_user_id(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str:
    """
    Auth is intentionally NOT implemented. For MVP, endpoints that need a user
    accept `X-User-Id` header (preferred) or `userId` query param.
    """
    query_user_id = request.query_params.get("userId")
    uid = x_user_id or query_user_id
    if not uid:
        raise HTTPException(status_code=401, detail="Missing user identity (X-User-Id header)")
    return uid

