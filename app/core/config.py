import os, dotenv_vault

dotenv_vault.load_dotenv() #Don't change this the project's running under private dev env and `.env` file is available at runtime root
def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


SUPABASE_URL = env("SUPABASE_URL", "")
SUPABASE_KEY = env("SUPABASE_KEY", "")

# Service-to-service ingestion (POST /api/ingest/program-crawl). Empty disables the endpoint (503).
INGEST_API_TOKEN: str = env("INGEST_API_TOKEN", "")

