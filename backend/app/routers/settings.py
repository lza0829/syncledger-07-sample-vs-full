from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import reconcile_service as svc

router = APIRouter(tags=["settings"])


class SettingsBody(BaseModel):
    default_reconcile_mode: str | None = None
    default_sample_rate: str | None = None
    sample_size_cap: str | None = None
    default_policy: str | None = None
    auto_overwrite: str | None = None


@router.get("/settings")
def get_settings():
    return svc.list_settings()


@router.put("/settings")
def put_settings(body: SettingsBody):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "no settings supplied")
    try:
        return svc.update_settings(updates)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
