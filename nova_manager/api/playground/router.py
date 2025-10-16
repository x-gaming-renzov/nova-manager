from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from nova_manager.api.playground.request_response import (
    PlaygroundPersonalisationUpdate,
    PlaygroundSessionResponse,
)
from nova_manager.api.personalisations.request_response import (
    PersonalisationDetailedResponse,
)
from nova_manager.components.auth.dependencies import require_playground_session
from nova_manager.components.personalisations.models import Personalisations
from nova_manager.core.security import SDKAuthContext
from nova_manager.database.session import get_db
from nova_manager.service.playground import (
    PlaygroundConfigurationError,
    PlaygroundService,
)

router = APIRouter()


@router.post("/session", response_model=PlaygroundSessionResponse)
async def create_playground_session(
    db: Session = Depends(get_db),
):
    service = PlaygroundService(db)

    try:
        result = service.create_session()
    except PlaygroundConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    session = result["session"]
    personalisation = result["personalisation"]
    user = result["user"]

    return PlaygroundSessionResponse(
        session_id=session.pid,
        token=result["token"],
        sdk_key=result["sdk_key"],
        user_id=user.pid,
        personalisation_id=personalisation.pid,
        expires_at=session.expires_at,
        personalisation=_serialize_personalisation(personalisation),
    )


@router.get(
    "/personalisation",
    response_model=PersonalisationDetailedResponse,
)
async def get_playground_personalisation(
    auth: SDKAuthContext = Depends(require_playground_session),
    db: Session = Depends(get_db),
):
    service = PlaygroundService(db)
    session_id = _parse_uuid(auth.playground_session_id)

    personalisation = service.get_session_personalisation(session_id)
    if not personalisation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    return _serialize_personalisation(personalisation)


@router.patch(
    "/personalisation",
    response_model=PersonalisationDetailedResponse,
)
async def update_playground_personalisation(
    update: PlaygroundPersonalisationUpdate,
    auth: SDKAuthContext = Depends(require_playground_session),
    db: Session = Depends(get_db),
):
    service = PlaygroundService(db)
    session_id = _parse_uuid(auth.playground_session_id)
    personalisation_id = _parse_uuid(auth.personalisation_id)

    session = service.get_session(session_id)
    if not session or session.personalisation_id != personalisation_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Playground session mismatch")

    personalisations_crud = service.personalisations_crud
    personalisation = personalisations_crud.get_detailed_personalisation(personalisation_id)

    if not personalisation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Personalisation not found")

    updated = personalisations_crud.update_personalisation(personalisation, update)

    updated = service.ensure_session_rule(updated, session.session_marker)

    detailed = personalisations_crud.get_detailed_personalisation(updated.pid)
    if not detailed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Personalisation not found")

    return _serialize_personalisation(detailed)


def _serialize_personalisation(
    personalisation: Personalisations,
) -> PersonalisationDetailedResponse:
    return PersonalisationDetailedResponse.model_validate(
        personalisation,
        from_attributes=True,
    )


def _parse_uuid(value: str | UUID | None) -> UUID:
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session metadata missing")
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
