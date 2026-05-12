from uuid import UUID as UUIDType
from sqlalchemy import UUID, String, ForeignKey, Enum, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nova_manager.core.models import BaseModel
from nova_manager.core.enums import UserRole


class Organisation(BaseModel):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String, nullable=False)

    apps: Mapped[list["App"]] = relationship(
        "App",
        foreign_keys="App.organisation_id",
        back_populates="organisation",
        cascade="all, delete-orphan",
    )

    auth_users: Mapped[list["AuthUser"]] = relationship(
        "AuthUser",
        foreign_keys="AuthUser.organisation_id",
        back_populates="organisation",
        cascade="all, delete-orphan",
    )


class App(BaseModel):
    __tablename__ = "apps"

    name: Mapped[str] = mapped_column(String, nullable=False)
    organisation_id: Mapped[UUIDType] = mapped_column(
        UUID, ForeignKey("organisations.pid"), nullable=False, index=True
    )  # Frequent org filtering
    analytics_backend: Mapped[str] = mapped_column(
        String, nullable=False, default="clickhouse", server_default="clickhouse"
    )

    organisation = relationship(
        "Organisation",
        foreign_keys=[organisation_id],
        back_populates="apps",
    )

    __table_args__ = (
        Index(
            "ix_apps_org_name", "organisation_id", "name"
        ),  # Org-scoped app name searches
        UniqueConstraint(
            "organisation_id", "name", name="uq_org_app_name"
        ),  # Prevent duplicate app names per org
    )


class AuthUser(BaseModel):
    __tablename__ = "auth_users"

    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(
        String, nullable=False, index=True, unique=True
    )  # Critical: email lookups
    password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.MEMBER
    )

    organisation_id: Mapped[UUIDType] = mapped_column(
        UUID, ForeignKey("organisations.pid"), nullable=False, index=True
    )  # Frequent joins

    organisation = relationship(
        "Organisation",
        foreign_keys=[organisation_id],
        back_populates="auth_users",
    )
