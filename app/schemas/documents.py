"""Request / response schemas for document endpoints."""

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ProcessingStatus
from app.schemas.common import FormattedDatetime


class UploadResponse(BaseModel):
    """Returned immediately after a PDF is accepted for background processing."""

    message: str = Field(description="Human-readable confirmation that the document was accepted.")
    document_id: str = Field(
        description="UUID assigned to the new document. Use this to poll `/v1/documents/{id}` for processing status."
    )
    status: ProcessingStatus = Field(description="Initial status. Always `PENDING` at upload time.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Document accepted for processing",
                "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": "PENDING",
            }
        }
    )


class DocumentResponse(BaseModel):
    """Document metadata returned by the API."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "filename": "Q3_Report_31-05-2026_14-30-45.pdf",
                "status": "COMPLETED",
                "created_at": "31:05:2026 14:30:45.000",
            }
        },
    )

    id: str = Field(description="UUID of the document.")
    filename: str = Field(description="Stored filename: `{original_stem}_{DD-MM-YYYY_HH-MM-SS}.pdf`.")
    status: ProcessingStatus = Field(description="Processing state: `PENDING` → `PROCESSING` → `COMPLETED` | `FAILED`.")
    created_at: FormattedDatetime = Field(description="Upload timestamp formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC).")
