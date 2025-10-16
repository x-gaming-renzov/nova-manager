from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, ForeignKey, String, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nova_manager.core.models import BaseModel


class PlaygroundSessions(BaseModel):
    __tablename__ = "playground_sessions"

    organisation_id: Mapped[str] = mapped_column(String, nullable=False)
    app_id: Mapped[str] = mapped_column(String, nullable=False)
    personalisation_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personalisations.pid"), nullable=False, index=True
    )
    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.pid"), nullable=False, index=True
    )
    sdk_key: Mapped[str] = mapped_column(String, nullable=False)
    session_marker: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
