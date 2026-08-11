"""
API Router for Runtime Model Settings.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.modules.settings.adapters.outbound.sqlite_settings_repository import SQLiteSettingsRepository
from app.modules.settings.application.settings_service import SettingsService

router = APIRouter(prefix="/v1/settings", tags=["Settings"])


def get_settings_service() -> SettingsService:
    repo = SQLiteSettingsRepository()
    return SettingsService(repo)


class ModelSettingsPayload(BaseModel):
    mode: str = Field(..., description="'always' or 'idle'")
    idle_timeout_sec: float = Field(..., ge=0, description="Inactivity timeout in seconds")


class ModelSettingsResponse(BaseModel):
    mode: str
    idle_timeout_sec: float
    typhoon_model_state: str = "unloaded"
    whisper_model_state: str = "unloaded"


@router.get("/model", response_model=ModelSettingsResponse)
async def get_model_settings(
    authenticated: bool = Depends(verify_api_key),
    service: SettingsService = Depends(get_settings_service),
):
    """Get the current model residency mode and idle timeout."""
    settings = service.get_model_settings()
    
    # Deferred import to avoid circular dependency during transition
    from app.asr_engine import get_engines_state
    states = get_engines_state()

    return ModelSettingsResponse(
        mode=settings.model_load_mode,
        idle_timeout_sec=settings.model_idle_timeout_sec,
        typhoon_model_state=states.get("typhoon", "unloaded"),
        whisper_model_state=states.get("whisper", "unloaded"),
    )


@router.put("/model", response_model=ModelSettingsResponse)
async def update_model_settings(
    payload: ModelSettingsPayload,
    authenticated: bool = Depends(verify_api_key),
    service: SettingsService = Depends(get_settings_service),
):
    """Change the model residency mode at runtime."""
    settings = service.update_model_settings(
        mode=payload.mode,
        idle_timeout_sec=payload.idle_timeout_sec,
    )

    from app.asr_engine import apply_model_load_mode_change, get_engines_state
    apply_model_load_mode_change(settings.model_load_mode)
    states = get_engines_state()

    return ModelSettingsResponse(
        mode=settings.model_load_mode,
        idle_timeout_sec=settings.model_idle_timeout_sec,
        typhoon_model_state=states.get("typhoon", "unloaded"),
        whisper_model_state=states.get("whisper", "unloaded"),
    )
