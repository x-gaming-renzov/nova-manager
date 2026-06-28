"""Security gating tests for the shared NOVA_ADMIN_KEY.

Covers the two HQ concerns: the docs (HTTP Basic) and the header-gated surfaces
(/register, /cleanup). Exercises the dependencies directly so no app import / DB
is needed. Key property: both fail closed when the key is unset.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from nova_manager.core import admin_key as ak

KEY = "s3cret-key"


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    monkeypatch.setattr(ak, "NOVA_ADMIN_KEY", KEY)


# --- header gate (X-Nova-Admin-Key): /register, /cleanup ---------------------
@pytest.mark.asyncio
async def test_header_correct_key_passes():
    await ak.require_admin_key(KEY)  # no raise


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", "wrong"])
async def test_header_bad_key_rejected(bad):
    with pytest.raises(HTTPException) as exc:
        await ak.require_admin_key(bad)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_header_fails_closed_when_key_unset(monkeypatch):
    monkeypatch.setattr(ak, "NOVA_ADMIN_KEY", "")
    with pytest.raises(HTTPException) as exc:
        await ak.require_admin_key(KEY)  # even a non-empty candidate is denied
    assert exc.value.status_code == 401


# --- docs gate (HTTP Basic; password == key) --------------------------------
@pytest.mark.asyncio
async def test_docs_correct_password_passes():
    await ak.require_docs_access(HTTPBasicCredentials(username="anyone", password=KEY))


@pytest.mark.asyncio
async def test_docs_bad_password_challenges():
    with pytest.raises(HTTPException) as exc:
        await ak.require_docs_access(HTTPBasicCredentials(username="anyone", password="nope"))
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"


@pytest.mark.asyncio
async def test_docs_missing_credentials_challenges():
    with pytest.raises(HTTPException) as exc:
        await ak.require_docs_access(None)
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"
