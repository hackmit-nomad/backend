from supabase import Client, create_client

from app.core.config import SUPABASE_KEY, SUPABASE_URL


def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


class _SupabaseProxy:
    def __init__(self) -> None:
        self._client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = get_supabase()
        return self._client

    def __getattr__(self, name: str):
        return getattr(self._get_client(), name)


supabase = _SupabaseProxy()

