from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.common import FormattedDatetime


class CompanyCreate(BaseModel):
    name: str
    industry: Optional[str] = None
    description: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    industry: Optional[str] = None
    description: Optional[str] = None
    created_at: FormattedDatetime
