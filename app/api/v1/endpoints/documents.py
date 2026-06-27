from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_or_super_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.documents import DocumentResponse, UploadResponse
from app.services import documents_service

router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=202,
    responses={
        400: {"description": "Company not found."},
        403: {"description": "Forbidden — admin or super_admin role required."},
        500: {"description": "File could not be saved to storage."},
    },
)
async def upload_document(
    file: UploadFile,
    company_id: str | None = Query(
        default=None,
        description="Target company UUID. Required for super_admin; ignored for admin (always their own company).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Upload a PDF for processing (admin/super_admin only, company-scoped).

    **admin**: always uploads to their own company.
    **super_admin**: must provide ``company_id`` and can upload for any existing company.
    """
    return await documents_service.upload_document(
        file=file,
        company_id=company_id,
        db=db,
        current_user=current_user,
    )


@router.get("/", response_model=list[DocumentResponse], status_code=200)
async def list_documents(
    company_id: str | None = Query(
        default=None,
        description="Filter by company UUID. Ignored for admin (always their own company); optional for super_admin.",
    ),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    List documents.

    **admin**: always returns documents from their own company only.
    **super_admin**: returns documents for the specified ``company_id``; if omitted, returns all documents.
    """
    service_kwargs: dict = {
        "company_id": company_id,
        "db": db,
        "current_user": current_user,
    }
    if limit is not None:
        service_kwargs["limit"] = limit
    if offset is not None:
        service_kwargs["offset"] = offset
    return await documents_service.list_documents(**service_kwargs)


@router.get("/{document_id}", response_model=DocumentResponse, status_code=200)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Check the status of a specific document.

    **admin**: must belong to their own company.
    **super_admin**: can access any document.
    """
    return await documents_service.get_document(document_id=document_id, db=db, current_user=current_user)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Delete a document and all its vector chunks.

    **admin**: must belong to their own company.
    **super_admin**: can delete any document.
    """
    await documents_service.delete_document(document_id=document_id, db=db, current_user=current_user)
    return None
