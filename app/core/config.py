import os
from dotenv_vault import load_dotenv

load_dotenv()

def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


SUPABASE_URL = env("SUPABASE_URL", "")
SUPABASE_KEY = env("SUPABASE_KEY", "")