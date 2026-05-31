"""Request / response schemas for company endpoints."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import FormattedDatetime


class CompanyCreate(BaseModel):
    """Payload for creating a new company. Super Admin only."""

    name: str = Field(description="Unique company name.")
    industry: str | None = Field(default=None, description="Industry sector (e.g. `Healthcare`, `Finance`).")
    description: str | None = Field(default=None, description="Optional free-text description of the company.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Acme Corp",
                "industry": "Finance",
                "description": "Global financial services provider.",
            }
        }
    )


class CompanyUpdate(BaseModel):
    """Payload for updating an existing company. All fields are optional."""

    name: str | None = Field(default=None, description="New unique company name.")
    industry: str | None = Field(default=None, description="Updated industry sector.")
    description: str | None = Field(default=None, description="Updated description.")

    model_config = ConfigDict(json_schema_extra={"example": {"industry": "FinTech"}})


class CompanyResponse(BaseModel):
    """Company data returned by the API."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": "Acme Corp",
                "industry": "Finance",
                "description": "Global financial services provider.",
                "created_at": "01:01:2026 09:00:00.000",
            }
        },
    )

    id: str = Field(description="UUID of the company.")
    name: str = Field(description="Unique company name.")
    industry: str | None = Field(default=None, description="Industry sector.")
    description: str | None = Field(default=None, description="Free-text description.")
    created_at: FormattedDatetime = Field(
        description="Creation timestamp formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
