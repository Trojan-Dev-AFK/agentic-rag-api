from pydantic import BaseModel, ConfigDict

from app.db.models import ProcessingStatus
from app.schemas.common import FormattedDatetime


class UploadResponse(BaseModel):
    message: str
    document_id: str
    status: ProcessingStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: ProcessingStatus
    created_at: FormattedDatetime


