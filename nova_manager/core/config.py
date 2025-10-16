import json
import os
from os import getenv
from typing import Any

from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"), override=True)


DATABASE_URL = getenv("DATABASE_URL") or ""
REDIS_URL = getenv("REDIS_URL") or "redis://localhost:6379/0"
JWT_SECRET_KEY = getenv("JWT_SECRET_KEY") or ""
OPENAI_API_KEY = getenv("OPENAI_API_KEY") or ""
GCP_PROJECT_ID = getenv("GCP_PROJECT_ID") or ""
GOOGLE_APPLICATION_CREDENTIALS = getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
BIGQUERY_LOCATION = getenv("BIGQUERY_LOCATION") or "US"
BREVO_API_KEY = getenv("BREVO_API_KEY") or ""
SDK_BACKEND_URL = getenv("SDK_BACKEND_URL") or ""


def _load_json_env(name: str, default: Any) -> Any:
	value = getenv(name)
	if not value:
		return default

	try:
		return json.loads(value)
	except json.JSONDecodeError:
		return default

ORG_INVITE_TEMPLATE_ID = int(getenv("ORG_INVITE_TEMPLATE_ID") or "2")
PASSWORD_RESET_TEMPLATE_ID = int(getenv("PASSWORD_RESET_TEMPLATE_ID") or "3")
WELCOME_TEMPLATE_ID = int(getenv("WELCOME_TEMPLATE_ID") or "4")

PLAYGROUND_ENABLED = (getenv("PLAYGROUND_ENABLED") or "false").lower() == "true"
PLAYGROUND_ORGANISATION_ID = getenv("PLAYGROUND_ORGANISATION_ID") or ""
PLAYGROUND_APP_ID = getenv("PLAYGROUND_APP_ID") or ""
PLAYGROUND_SDK_KEY = getenv("PLAYGROUND_SDK_KEY") or ""
PLAYGROUND_EXPERIENCE_NAME = getenv("PLAYGROUND_EXPERIENCE_NAME") or ""
PLAYGROUND_BASE_PERSONALISATION_NAME = getenv("PLAYGROUND_BASE_PERSONALISATION_NAME") or ""
PLAYGROUND_PERSONALISATION_NAME_PREFIX = (
	getenv("PLAYGROUND_PERSONALISATION_NAME_PREFIX") or "Playground"
)
PLAYGROUND_TOKEN_TTL_MINUTES = int(getenv("PLAYGROUND_TOKEN_TTL_MINUTES") or "1440")
PLAYGROUND_DEFAULT_USER_PROFILE = _load_json_env(
	"PLAYGROUND_DEFAULT_USER_PROFILE", {"country": "United States"}
)
