"""Request / response schemas for authentication endpoints."""

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import UserRole
from app.schemas.common import FormattedDatetime


class TokenResponse(BaseModel):
    """Returned on successful login."""

    access_token: str = Field(
        description="Signed JWT bearer token. Include in subsequent requests as `Authorization: Bearer <token>`."
    )
    token_type: str = Field(default="bearer", description="Always `bearer`.")
    expires_in: int = Field(description="Token lifetime in seconds.")
    role: UserRole = Field(description="Role of the authenticated user: `super_admin`, `admin`, or `employee`.")
    company_id: str | None = Field(
        default=None, description="UUID of the company the user belongs to. `null` for `super_admin`."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "role": "admin",
                "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            }
        }
    )


class LogoutResponse(BaseModel):
    """Returned on successful logout."""

    message: str = Field(description="Confirmation message.")

    model_config = ConfigDict(json_schema_extra={"example": {"message": "Successfully logged out"}})


class MeResponse(BaseModel):
    """Profile of the currently authenticated user."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "username": "jane.doe",
                "role": "admin",
                "company_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "company_name": "Acme Corp",
                "created_at": "01:01:2026 09:00:00.000",
            }
        },
    )

    id: str = Field(description="UUID of the user.")
    username: str = Field(description="Unique login username.")
    role: UserRole = Field(description="Role: `super_admin`, `admin`, or `employee`.")
    company_id: str | None = Field(default=None, description="Company UUID; `null` for `super_admin`.")
    company_name: str | None = Field(default=None, description="Human-readable company name; `null` for `super_admin`.")
    created_at: FormattedDatetime = Field(
        description="Account creation timestamp formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
