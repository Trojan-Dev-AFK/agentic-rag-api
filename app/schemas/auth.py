from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import UserRole
from app.schemas.common import FormattedDatetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: UserRole
    company_id: Optional[str] = None


class LogoutResponse(BaseModel):
    message: str


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: UserRole
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    created_at: FormattedDatetime
