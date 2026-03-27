# Backend Logic Review Report

Date: 2026-03-28  
Scope: `app/main.py`, `app/api/deps.py`, `app/api/router.py`, `app/api/routes/*.py`, `app/db/supabase.py`, `main.py`, `schema.txt`

## Executive Summary

The modular backend under `app/` is mostly coherent and maps to the schema reasonably well, but it has critical authorization and data-integrity gaps. The most serious issue is that identity is fully client-controlled via `X-User-Id`/`userId`, enabling user impersonation across protected endpoints. There are also several logic flaws in social graph handling and message deletion, plus N+1 query patterns that will degrade performance as data grows.

## Findings (Ordered by Severity)

### 1) Critical: Authentication allows full user impersonation

- **Where**: `app/api/deps.py`, all routes that depend on `get_current_user_id`
- **Issue**: User identity is accepted directly from request header/query param without cryptographic verification.
- **Impact**: Any client can act as any user by setting `X-User-Id`, including reading/updating profiles, posting, messaging, joining communities, and reading notifications.
- **Recommendation**:
  - Replace `get_current_user_id` with real auth verification (Supabase JWT validation and subject extraction).
  - Remove fallback to query parameter identity.
  - Treat current approach as development-only and gate by environment if temporarily retained.

### 2) High: Social connection model can return incorrect relationship state

- **Where**: `app/api/routes/users.py` (`connect_user`, `disconnect_user`, `list_users`)
- **Issue**:
  - Relationship logic only checks one directed record (`userId = me`, `friendId = other`) and ignores reverse row.
  - Accept flow updates only existing directed row and does not ensure symmetric/consistent state.
  - `list_users(..., connected=...)` only reads one direction, so connected users can be misclassified.
- **Impact**: UI can show wrong connection status; users may be “connected” in one direction and not the other; disconnect may leave stale reverse edges.
- **Recommendation**:
  - Enforce a canonical pair model (single undirected row with deterministic ordering) or always maintain mirrored rows transactionally.
  - Update list/filter logic to evaluate both directions.
  - Add unique constraints and tests for connect/accept/disconnect flows.

### 3) High: Message delete endpoint can remove others' messages

- **Where**: `app/api/routes/messages.py` (`delete_message`)
- **Issue**: Any participant can delete any message in a conversation (`eq("id", messageId).eq("chatId", conversationId)`), no sender/role check.
- **Impact**: Participants can erase other users' content without authorization.
- **Recommendation**:
  - Restrict delete to sender (`senderId == user_id`) or enforce role-based permissions for group admins/moderators.
  - Prefer soft-delete with audit trail in messaging systems.

### 4) Medium: Duplicate app entrypoint introduces deployment ambiguity

- **Where**: `main.py` (repo root) vs `app/main.py`
- **Issue**:
  - `main.py` defines a second FastAPI app and includes duplicated/legacy business logic.
  - It also has repeated `from app.main import app` imports.
- **Impact**: Different startup commands may serve different APIs; behavior diverges between environments; maintainability risk.
- **Recommendation**:
  - Keep a single authoritative app entrypoint (prefer `app/main.py`).
  - Remove or archive legacy root `main.py` implementation.
  - Ensure run docs use one module path only (e.g., `uvicorn app.main:app`).

### 5) Medium: Several destructive endpoints return success regardless of actual mutation

- **Where**:
  - `app/api/routes/users.py` (`delete_me`)
  - `app/api/routes/courses.py` (`delete_course`)
  - `app/api/routes/communities.py` (`delete_community`)
  - `app/api/routes/messages.py` (`delete_conversation`, `delete_message`)
  - `app/api/routes/calendar.py` (`delete_event`)
- **Issue**: Delete operations generally do not validate affected row count and still return 204.
- **Impact**: Clients cannot distinguish “not found/unauthorized” vs “deleted”; hidden data consistency problems.
- **Recommendation**:
  - Check mutation result metadata and return 404 when target row does not exist for caller scope.
  - Add endpoint-level tests for “delete nonexistent” and “delete unauthorized”.

### 6) Medium: Calendar update path can fail with unhandled errors on missing event

- **Where**: `app/api/routes/calendar.py` (`update_event`)
- **Issue**: When recomputing `startAt`/`endAt`, code queries event fields with `.single().execute().data.get(...)` before confirming row existence/ownership.
- **Impact**: Missing row can raise runtime errors (500) instead of returning clean 404.
- **Recommendation**:
  - Load event once with `id + userId` filter at start; if missing, return 404.
  - Reuse loaded record to compute merged date/time fields safely.

### 7) Medium: N+1 query patterns in high-traffic reads

- **Where**:
  - `app/api/routes/feed.py` (`_post_to_api`) for reactions and replies per post
  - `app/api/routes/communities.py` (`_community_to_api`) for membership/posts counts per community
  - `app/api/routes/messages.py` (`list_conversations`) for last message and participants per conversation
- **Issue**: List endpoints perform extra DB calls per item.
- **Impact**: Latency and DB load increase linearly with list size; can become bottleneck quickly.
- **Recommendation**:
  - Batch-fetch related data (single query per relation, then map in memory).
  - Consider materialized counters for community/post stats.
  - Add pagination defaults/limits consistently.

### 8) Low: Input validation and typing are weak in several places

- **Where**:
  - `app/api/routes/feed.py` (`react_to_post` takes untyped `dict[str, Any]`)
  - `app/api/routes/calendar.py` (date/time accepted as plain strings, no format validation)
  - Various create/update handlers lack length or enum constraints.
- **Impact**: More runtime validation branches, malformed data in persistence layer, reduced API contract clarity.
- **Recommendation**:
  - Replace untyped bodies with strict Pydantic models.
  - Use constrained/annotated types (enums, min/max lengths, format validators).

## Additional Notes

- CORS is fully open (`allow_origins=["*"]`) while credentials are allowed. This is risky for production and should be environment-scoped.
- `app/db/supabase.py` creates a global client at import time. This is acceptable for MVP but hard to swap/mocks in tests; dependency injection would improve testability.

## Suggested Prioritized Remediation Plan

1. Implement real auth verification and remove header/query identity trust.
2. Fix authorization for message deletion and social connection state consistency.
3. Consolidate to one app entrypoint and retire legacy root `main.py`.
4. Normalize 404 semantics for delete/update operations.
5. Eliminate key N+1 paths and add pagination guards.
6. Add request model validation hardening and endpoint tests.

## Testing Gaps To Add

- Auth spoofing tests for all protected endpoints.
- Social connect/disconnect state transition tests (both directions).
- Message deletion authorization tests (self vs others).
- Calendar update error-path tests (missing event, malformed date/time).
- Load-oriented tests on feed/community/message list endpoints to catch N+1 regressions.

