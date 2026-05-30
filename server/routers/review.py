import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.schemas.review import ReviewRequest, ReviewResponse
from server.services.review_service import run_review, run_qa_service
from server.services.history_service import create_history
from server.auth.dependencies import get_current_user
from server.models.user import User
from server.config import settings

router = APIRouter(prefix="/api", tags=["合同审查"])


@router.post("/review", response_model=ReviewResponse)
async def review_text(
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await run_review(user_input=body.text)
    history = await create_history(
        db,
        user_id=current_user.id,
        query_input=body.text,
        contract_type=result["contract_type"],
        review_output=result["review_output"],
    )
    return ReviewResponse(
        id=history.id,
        contract_type=result["contract_type"],
        branches=result["branches"],
        review_output=result["review_output"],
        error=result["error"],
        warnings=result.get("warnings", []),
    )


@router.post("/upload", response_model=ReviewResponse)
async def upload_file(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".docx", ".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 和 .pdf 文件")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    temp_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}{suffix}")

    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        result = await run_review(file_path=temp_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    history = await create_history(
        db,
        user_id=current_user.id,
        query_input=f"[文件上传] {file.filename}",
        contract_type=result["contract_type"],
        review_output=result["review_output"],
    )
    return ReviewResponse(
        id=history.id,
        contract_type=result["contract_type"],
        branches=result["branches"],
        review_output=result["review_output"],
        error=result["error"],
        warnings=result.get("warnings", []),
    )


@router.post("/qa", response_model=ReviewResponse)
async def qa_text(
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await run_qa_service(question=body.text)
    history = await create_history(
        db,
        user_id=current_user.id,
        query_input=body.text,
        contract_type=result["contract_type"],
        review_output=result["review_output"],
    )
    return ReviewResponse(
        id=history.id,
        contract_type=result["contract_type"],
        branches=result["branches"],
        review_output=result["review_output"],
        error=result["error"],
        warnings=result.get("warnings", []),
    )
