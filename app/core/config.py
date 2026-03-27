import os


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


SUPABASE_URL = "https://hcvisecwcgupinlqghgr.supabase.co"
SUPABASE_KEY = "sb_secret_QM2gtIIyrVf_i4cppw2IAw_WGzn7HuV"
