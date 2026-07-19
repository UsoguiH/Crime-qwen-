from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import (CurrentUser, get_factory, get_session, get_vlm,
                      require_role, settings_dep)
from app.db.models import AppSetting
from app.services import audit

router = APIRouter(tags=["admin"])

ALLOWED_SETTINGS = {
    "confidence_review_threshold": float,
    "thinking_policy": str,
    "face_blur_default": bool,
    "max_frames_per_video": int,
}


async def get_setting_overrides(session: AsyncSession) -> dict:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: (r.value_json or {}).get("value") for r in rows
            if (r.value_json or {}).get("value") is not None}


class SettingPut(BaseModel):
    key: str
    value: float | int | bool | str


@router.get("/settings")
async def get_settings_view(session: AsyncSession = Depends(get_session),
                            settings: Settings = Depends(settings_dep),
                            user: CurrentUser = Depends(require_role("reviewer", "investigator"))):
    overrides = await get_setting_overrides(session)
    return {
        "model_mode": settings.model_mode,
        "model_provider": settings.model_provider,
        "model_name_fast": settings.model_name_fast,
        "model_name_thinking": settings.model_name_thinking,
        "openrouter_data_collection": settings.openrouter_data_collection,
        "openrouter_zdr": settings.openrouter_zdr,
        "report_pdf_variant": settings.report_pdf_variant,
        "effective": {
            "confidence_review_threshold": overrides.get(
                "confidence_review_threshold", settings.confidence_review_threshold),
            "thinking_policy": overrides.get("thinking_policy", "auto"),
            "face_blur_default": overrides.get("face_blur_default",
                                               settings.face_blur_default),
            "max_frames_per_video": overrides.get("max_frames_per_video", 240),
        },
        "overrides": overrides,
    }


@router.put("/settings")
async def put_setting(body: SettingPut,
                      session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(require_role("admin")),
                      factory=Depends(get_factory)):
    if body.key not in ALLOWED_SETTINGS:
        raise HTTPException(status_code=400, detail="إعداد غير معروف")
    caster = ALLOWED_SETTINGS[body.key]
    try:
        value = caster(body.value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="قيمة غير صالحة")
    row = (await session.execute(
        select(AppSetting).where(AppSetting.key == body.key))).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=body.key)
        session.add(row)
    row.value_json = {"value": value}
    row.updated_by = user.id
    await session.commit()
    await audit.append(factory, action="settings.update", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="setting",
                       object_id=body.key, detail={"value": value})
    return {"ok": True, "key": body.key, "value": value}


@router.get("/models/health")
async def models_health(vlm=Depends(get_vlm),
                        user: CurrentUser = Depends(require_role("reviewer", "investigator"))):
    return await vlm.health()
