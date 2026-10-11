import os
from os import getenv
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"), override=True)


DATABASE_URL = getenv("DATABASE_URL") or ""
REDIS_URL = getenv("REDIS_URL") or "redis://localhost:6379/0"
JWT_SECRET_KEY = getenv("JWT_SECRET_KEY") or ""
OPENAI_API_KEY = getenv("OPENAI_API_KEY") or ""
CLICKHOUSE_HOST = getenv("CLICKHOUSE_HOST") or "localhost"
CLICKHOUSE_PORT = int(getenv("CLICKHOUSE_PORT") or "8123")
CLICKHOUSE_USER = getenv("CLICKHOUSE_USER") or "default"
CLICKHOUSE_PASSWORD = getenv("CLICKHOUSE_PASSWORD") or ""
# Distinguishes environments that otherwise share the same org/app ids (and
# therefore the same SDK key) so their ClickHouse analytics don't collide.
NOVA_ENV = getenv("NOVA_ENV") or "production"


def rq_queue_name(nova_env: str) -> str:
    """Job queue for an environment.

    Environments share one Redis, so on a shared queue either worker could take the other's
    jobs. Production keeps "default" so jobs already queued when this ships are still consumed.
    """
    if nova_env == "production":
        return "default"
    return f"default-{nova_env}"


RQ_QUEUE_NAME = rq_queue_name(NOVA_ENV)

# Sync export (/api/v1/sync): largest page a caller may ask for, and how many seconds of the
# newest writes are withheld so an insert still in flight cannot land behind a caller's cursor.
SYNC_EXPORT_MAX_LIMIT = int(getenv("SYNC_EXPORT_MAX_LIMIT") or "10000")
SYNC_WATERMARK_LAG_SECONDS = int(getenv("SYNC_WATERMARK_LAG_SECONDS") or "30")
BREVO_API_KEY = getenv("BREVO_API_KEY") or ""
SDK_BACKEND_URL = getenv("SDK_BACKEND_URL") or ""
ALLOWED_ORIGINS = [o.strip() for o in (getenv("ALLOWED_ORIGINS") or "*").split(",")]

# Shared secret gating the API docs (/docs, /redoc, /openapi.json), self-service
# /register, and the destructive admin cleanup endpoint. Set per environment;
# when unset the gated surfaces fail closed (deny) rather than fall open.
NOVA_ADMIN_KEY = getenv("NOVA_ADMIN_KEY") or ""

NOTICE_SERVICE_URL = getenv("NOTICE_SERVICE_URL") or "http://localhost:8001"
NOTICE_SERVICE_SECRET = getenv("NOTICE_SERVICE_SECRET") or ""

ORG_INVITE_TEMPLATE_ID = int(getenv("ORG_INVITE_TEMPLATE_ID") or "2")
PASSWORD_RESET_TEMPLATE_ID = int(getenv("PASSWORD_RESET_TEMPLATE_ID") or "3")
WELCOME_TEMPLATE_ID = int(getenv("WELCOME_TEMPLATE_ID") or "4")
