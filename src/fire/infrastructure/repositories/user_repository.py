from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from src.fire.domain.entities.user import User
from src.fire.domain.interfaces.repositories import IUserRepository
from src.fire.infrastructure.db.models import UserORM


class UserRepository(IUserRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def save(self, user: User) -> User:
        with self._session_factory() as session:
            orm = _to_orm(user)
            session.merge(orm)
            session.commit()
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        with self._session_factory() as session:
            orm = session.get(UserORM, str(user_id))
            return _to_entity(orm) if orm else None

    async def list_all(self) -> list[User]:
        with self._session_factory() as session:
            rows = session.query(UserORM).all()
            return [_to_entity(r) for r in rows]


def _to_orm(user: User) -> UserORM:
    return UserORM(
        id=str(user.id),
        name=user.name,
        created_at=user.created_at,
    )


def _to_entity(orm: UserORM) -> User:
    return User(
        id=UUID(orm.id),
        name=orm.name,
        created_at=orm.created_at,
    )