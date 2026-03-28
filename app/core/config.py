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

# Pusher realtime for messages (optional: disabled when keys are missing).
PUSHER_APP_ID: str = env("PUSHER_APP_ID", "")
PUSHER_KEY: str = env("PUSHER_KEY", "")
PUSHER_SECRET: str = env("PUSHER_SECRET", "")
PUSHER_CLUSTER: str = env("PUSHER_CLUSTER", "")
# Scheduler workflow keys.
# New split keys:
# - AGENDA_SCHEDULER_KEY for /calendar/events/agent-chat-schedule
# - CHAT_SCHEDULER_KEY for /messages/.../schedule-proposals
AGENDA_SCHEDULER_KEY: str = env("AGENDA_SCHEDULER_KEY", "")
CHAT_SCHEDULER_KEY: str = env("CHAT_SCHEDULER_KEY", "")

# Effective keys (prefer specific key, then legacy globals).
AGENDA_WORKFLOW_API_KEY: str = AGENDA_SCHEDULER_KEY
CHAT_WORKFLOW_API_KEY: str = CHAT_SCHEDULER_KEY

# OpenAI API key for resume/CV parsing and tag extraction.
OPENAI_API_KEY: str = env("OPENAI_API_KEY", "")

