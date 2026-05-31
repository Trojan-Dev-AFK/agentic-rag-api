from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import UserRole
from app.schemas.common import FormattedDatetime


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.EMPLOYEE
    company_id: str


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[UserRole] = None
    company_id: Optional[str] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: UserRole
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    created_at: FormattedDatetime
