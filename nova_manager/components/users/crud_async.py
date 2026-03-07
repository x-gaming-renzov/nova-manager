from uuid import UUID
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from nova_manager.components.users.models import Users
from nova_manager.components.user_experience.models import UserExperience
from sqlalchemy.orm.attributes import flag_modified


class UsersAsyncCRUD:
    """Async CRUD operations for Users"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(
        self, user_id: str, organisation_id: str, app_id: str
    ) -> Optional[Users]:
        """Get user by user_id within organization/app scope"""

        stmt = select(Users).where(
            and_(
                Users.user_id == user_id,
                Users.organisation_id == organisation_id,
                Users.app_id == app_id,
            )
        )

        result = await self.db.execute(stmt)

        return result.scalar_one_or_none()

    async def get_by_pid(
        self, pid: UUID, organisation_id: str, app_id: str
    ) -> Optional[Users]:
        """Get user by pid"""

        stmt = select(Users).where(
            and_(
                Users.pid == pid,
                Users.organisation_id == organisation_id,
                Users.app_id == app_id,
            )
        )

        result = await self.db.execute(stmt)

        return result.scalar_one_or_none()

    async def create_user(
        self,
        user_id: str,
        organisation_id: str,
        app_id: str,
        user_profile: Dict[str, Any] | None = None,
    ) -> Users:
        """Create new user record"""

        if not user_profile:
            user_profile = {}

        user = Users(
            user_id=user_id,
            organisation_id=organisation_id,
            app_id=app_id,
            user_profile=user_profile,
        )

        self.db.add(user)

        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def update_user_profile(
        self, user: Users, user_profile: Dict[str, Any]
    ) -> Users:
        """Update existing user record"""

        existing_profile = user.user_profile or {}
        existing_profile.update(user_profile)

        user.user_profile = existing_profile

        flag_modified(user, "user_profile")

        self.db.add(user)

        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def reassign_user_experiences(self, from_pid: UUID, to_pid: UUID) -> int:
        stmt = (
            update(UserExperience)
            .where(UserExperience.user_id == from_pid)
            .values(user_id=to_pid)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def delete_user(self, user: Users) -> None:
        await self.db.delete(user)
        await self.db.flush()

    async def merge_user_profiles(
        self,
        target: Users,
        source_profile: dict | None,
        additional_profile: dict | None,
    ) -> Users:
        merged = {**(source_profile or {}), **(target.user_profile or {}), **(additional_profile or {})}
        target.user_profile = merged
        flag_modified(target, "user_profile")
        self.db.add(target)
        await self.db.flush()
        return target
