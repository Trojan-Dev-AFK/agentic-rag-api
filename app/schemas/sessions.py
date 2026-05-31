from pydantic import BaseModel, ConfigDict

from app.schemas.common import FormattedDatetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    jti: str
    issued_at: FormattedDatetime
    expires_at: FormattedDatetime
    revoked_at: FormattedDatetime | None = None
    logout_at: FormattedDatetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None
