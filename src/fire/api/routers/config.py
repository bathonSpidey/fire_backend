from fastapi import APIRouter, Depends
from pydantic import BaseModel

from fire.api.dependencies import get_settings
from fire.config.settings import Settings

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    receipt_provider: str
    gemini_model: str
    gemini_available_models: list[str]


class UpdateModelRequest(BaseModel):
    model: str


@router.get("", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    return ConfigResponse(
        receipt_provider=settings.fire_receipt_provider,
        gemini_model=settings.gemini_model,
        gemini_available_models=settings.gemini_available_models,
    )


@router.patch("/gemini-model", response_model=ConfigResponse)
async def update_gemini_model(
    request: UpdateModelRequest,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    """
    Switch the active Gemini model at runtime.
    The change applies immediately — next upload uses the new model.
    Does not persist across restarts (set GEMINI_MODEL in .env for that).
    """
    if request.model not in settings.gemini_available_models:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Unknown model. Available: {settings.gemini_available_models}",
        )
    settings.gemini_model = request.model
    return ConfigResponse(
        receipt_provider=settings.fire_receipt_provider,
        gemini_model=settings.gemini_model,
        gemini_available_models=settings.gemini_available_models,
    )
