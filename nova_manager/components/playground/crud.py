from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy.orm import Session

from nova_manager.core.base_crud import BaseCRUD
from nova_manager.components.playground.models import PlaygroundSessions


class PlaygroundSessionsCRUD(BaseCRUD):
    """CRUD operations for playground session records."""

    def __init__(self, db: Session):
        super().__init__(PlaygroundSessions, db)

    def create_session(
        self,
        organisation_id: str,
        app_id: str,
        personalisation_id: UUIDType,
        user_id: UUIDType,
        sdk_key: str,
        session_marker: str,
        expires_at: datetime | None = None,
    ) -> PlaygroundSessions:
        session = PlaygroundSessions(
            organisation_id=organisation_id,
            app_id=app_id,
            personalisation_id=personalisation_id,
            user_id=user_id,
            sdk_key=sdk_key,
            session_marker=session_marker,
            expires_at=expires_at,
        )

        self.db.add(session)
        self.db.flush()
        self.db.refresh(session)
        return session

    def get_by_personalisation(self, personalisation_id: UUIDType) -> PlaygroundSessions | None:
        return (
            self.db.query(PlaygroundSessions)
            .filter(PlaygroundSessions.personalisation_id == personalisation_id)
            .first()
        )
