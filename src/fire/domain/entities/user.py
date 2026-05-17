from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass
class User:
    """
    Represents a household member.
    No password — this is a trusted LAN application.
    Authentication is handled by profile selection on the frontend.
    """

    id: UUID
    name: str
    created_at: datetime

    @classmethod
    def create(cls, name: str) -> "User":
        return cls(
            id=uuid4(),
            name=name.strip(),
            created_at=datetime.now(UTC),
        )
