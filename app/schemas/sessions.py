"""Request / response schemas for token session endpoints."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import FormattedDatetime


class SessionResponse(BaseModel):
    """A single JWT token session record."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "user_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "jti": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "issued_at": "31:05:2026 09:00:00.000",
                "expires_at": "31:05:2026 10:00:00.000",
                "revoked_at": None,
                "logout_at": None,
                "ip_address": "192.168.1.10",
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            }
        },
    )

    id: str = Field(description="UUID of the session record.")
    user_id: str = Field(description="UUID of the user this session belongs to.")
    jti: str = Field(description="JWT ID — the unique identifier embedded in the token claim.")
    issued_at: FormattedDatetime = Field(
        description="When the token was created, formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
    expires_at: FormattedDatetime = Field(
        description="When the token expires, formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    )
    revoked_at: FormattedDatetime | None = Field(
        default=None, description="When the token was revoked, or `null` if still valid."
    )
    logout_at: FormattedDatetime | None = Field(
        default=None, description="When the user explicitly logged out, or `null` if still active."
    )
    ip_address: str | None = Field(default=None, description="IP address of the client that created this session.")
    user_agent: str | None = Field(default=None, description="User-Agent header from the login request.")
