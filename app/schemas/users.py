"""Request / response schemas for user management endpoints."""

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import UserRole
from app.schemas.common import FormattedDatetime


class UserCreate(BaseModel):
    """Payload for creating a new user inside the admin's company."""

    username: str = Field(description="Unique login username.")
    password: str = Field(description="Plain-text password. Bcrypt-hashed before storage; never returned in responses.")
    role: UserRole = Field(
        default=UserRole.EMPLOYEE, description="Role to assign: `admin` or `employee`. Defaults to `employee`."
    )
    company_id: str = Field(
        description="UUID of the company this user belongs to. Must match the requesting admin's company."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "john.smith",
                "password": "SecurePass123!",
                "role": "employee",
                "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            }
        }
    )


class UserUpdate(BaseModel):
    """Payload for updating an existing user. All fields are optional."""

    password: str | None = Field(default=None, description="New plain-text password. Hashed before storage.")
    role: UserRole | None = Field(default=None, description="New role: `admin` or `employee`.")
    company_id: str | None = Field(
        default=None, description="Transfer user to another company UUID. Must match the admin's own company."
    )

    model_config = ConfigDict(json_schema_extra={"example": {"role": "admin"}})


class UserResponse(BaseModel):
    """User data returned by the API. Passwords are never included."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "username": "john.smith",
                "role": "employee",
                "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "company_name": "Acme Corp",
                "created_at": "15:03:2026 14:22:00.000",
            }
        },
    )

    id: str = Field(description="UUID of the user.")
    username: str = Field(description="Unique login username.")
    role: UserRole = Field(description="Role: `admin` or `employee`.")
    company_id: str | None = Field(default=None, description="Company UUID the user belongs to.")
    company_name: str | None = Field(default=None, description="Human-readable company name.")
    created_at: FormattedDatetime = Field(
        description="Account creation timestamp formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
