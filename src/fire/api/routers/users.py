from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.fire.api.dependencies import get_user_repo
from src.fire.api.schemas.user import CreateUserRequest, UserResponse
from src.fire.domain.entities.user import User
from src.fire.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    user_repo: UserRepository = Depends(get_user_repo),
) -> UserResponse:
    user = await user_repo.save(User.create(name=request.name))
    return _to_response(user)


@router.get("", response_model=list[UserResponse])
async def list_users(
    user_repo: UserRepository = Depends(get_user_repo),
) -> list[UserResponse]:
    users = await user_repo.list_all()
    return [_to_response(u) for u in users]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    user_repo: UserRepository = Depends(get_user_repo),
) -> UserResponse:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_response(user)


def _to_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, name=user.name, created_at=user.created_at)
