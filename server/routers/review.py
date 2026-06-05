from __future__ import annotations
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.schemas.review import ReviewRequest, ReviewResponse, StreamReviewRequest
from server.services.review_service import run_review, run_qa_service
from server.services.stream_service import stream_review, stream_qa
from server.services.history_service import create_history
from server.auth.dependencies import get_current_user
from server.models.user import User
from server.config import settings

router = APIRouter(prefix="/api", tags=["合同审查"])


# ── SSE 辅助 ────────────────────────────────────────────────────────────

async def _sse_wrap(generator):
    """将事件 dict 生成器包装为 SSE 文本流。"""
    async for event in generator:
        line = f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        yield line


# ── 阻塞端点（保留向后兼容）─────────────────────────────────────────────


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


# ── SSE 流式端点 ────────────────────────────────────────────────────────

@router.post("/review/stream")
async def review_stream(
    body: StreamReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """合同审查 SSE 流式端点 — 检索完成后逐 token 返回审查报告。"""
    return StreamingResponse(
        _sse_wrap(stream_review(
            user_input=body.text,
            file_path="",
            user_id=current_user.id,
            db=db,
            thread_id=body.thread_id,
        )),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/qa/stream")
async def qa_stream(
    body: StreamReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """法律咨询 SSE 流式端点 — 检索完成后逐 token 返回咨询结果。"""
    return StreamingResponse(
        _sse_wrap(stream_qa(
            user_input=body.text,
            user_id=current_user.id,
            db=db,
            thread_id=body.thread_id,
        )),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/upload/stream")
async def upload_stream(
    file: UploadFile,
    thread_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """文件上传 SSE 流式端点 — 解析文件后流式审查。"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".docx", ".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 和 .pdf 文件")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    temp_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}{suffix}")

    content = await file.read()
    with open(temp_path, "wb") as f:
        f.write(content)

    async def _cleanup_wrapper():
        try:
            async for event in stream_review(
                user_input="",
                file_path=temp_path,
                user_id=current_user.id,
                db=db,
                thread_id=thread_id,
            ):
                yield event
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    return StreamingResponse(
        _sse_wrap(_cleanup_wrapper()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
