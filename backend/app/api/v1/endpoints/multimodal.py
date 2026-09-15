"""多模态端点（FR-1 图文售后 + 语音，对齐 API 规范 §4.10）

链路：POST /multimodal/images（存→预检→VLM）→ {file_id, url, inspection}；
      POST /multimodal/speech/transcribe（存→ASR）→ {text, confidence}；
      GET /multimodal/speech/tts-config + POST /multimodal/speech/synthesize；
      GET /multimodal/media/{file_id} 租户内回读。
薄封装红线：解析→调 service→ok()/fail()，预检/Disk/VLM 全在 service，
             本文件不出现阈值/模型名/URL 字面量，不直写 db。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.core.rbac import get_current_user
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import media_store, speech_service, vision_service

router = APIRouter(prefix="/multimodal", tags=["multimodal"])


class SynthesizeRequest(BaseModel):
    """TTS 合成入参（端点私有 DTO；voice 空=默认晓晓）。"""

    text: str = ""
    voice: str = ""


@router.post("/images")
async def upload_image(
    file: UploadFile | None = None,
    session_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """图文上传：落对象存储 → NSFW/PII 预检 → VLM 真图检测，一次返回卡片所需全量。"""
    _ = db
    if file is None or not (file.filename or "").strip():
        return fail(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    raw = await file.read()
    saved = await asyncio.to_thread(
        media_store.save_upload,
        tenant=user.tenant,
        kind="image",
        session_id=(session_id or "").strip(),
        filename=file.filename or "upload.jpg",
        raw=raw,
    )
    try:
        result = await vision_service.inspect_image(
            filename=file.filename or "upload.jpg",
            content_type=file.content_type or "image/jpeg",
            size=len(raw),
            image=raw,
        )
    except BusinessError as exc:
        return fail(exc.code, exc.msg, exc.http_status)
    return ok(
        {"file_id": saved["file_id"], "url": saved["url"], "inspection": result.to_dict()},
        "图片检测完成" if not result.need_human else "已转人工复核确认",
    )


@router.post("/speech/transcribe")
async def transcribe_speech(
    file: UploadFile | None = None,
    session_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """语音转写：落盘 → ASR → {text, confidence}，低置信 need_confirm 回问确认。"""
    _ = db
    if file is None or not (file.filename or "").strip():
        return fail(ErrorCode.PARAM_INVALID, "请先录制一段语音", 400)
    raw = await file.read()
    saved = await asyncio.to_thread(
        media_store.save_upload,
        tenant=user.tenant,
        kind="audio",
        session_id=(session_id or "").strip(),
        filename=file.filename or "voice.webm",
        raw=raw,
    )
    try:
        out = await speech_service.transcribe(
            filename=file.filename or "voice.webm",
            content_type=file.content_type or "",
            size=len(raw),
            audio=raw,
        )
    except BusinessError as exc:
        return fail(exc.code, exc.msg, exc.http_status)
    return ok(
        {"file_id": saved["file_id"], "url": saved["url"], **out},
        "转写完成" if not out.get("need_confirm") else "转写置信较低，请确认后发送",
    )


@router.get("/speech/tts-config")
async def get_tts_config(
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """TTS 开关/音色（前端播放开关与下拉同源）。"""
    _ = user
    return ok(speech_service.tts_config(), "获取成功")


@router.post("/speech/synthesize")
async def synthesize_speech(
    payload: SynthesizeRequest,
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """TTS 合成 stub：回文本 + 音色，前端 WebSpeech 播放 + 波形。"""
    _ = user
    try:
        out = speech_service.synthesize(text=payload.text, voice=payload.voice)
    except BusinessError as exc:
        return fail(exc.code, exc.msg, exc.http_status)
    return ok(out, "合成成功")


@router.get("/media/{file_id}", response_model=None)
async def read_media(
    file_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """媒体回读（租户隔离：只搜本租户目录，跨租户同 404）。"""
    path = await asyncio.to_thread(media_store.resolve_path, tenant=user.tenant, file_id=file_id)
    if path is None:
        return fail(ErrorCode.NOT_FOUND, "文件不存在或已过期", 404)
    return FileResponse(str(path))
