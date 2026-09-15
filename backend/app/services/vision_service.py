"""VLM 瑕疵检测单出口（对齐 FR-1.2 + 执行步骤 A + 电商开发文档 工具表）

链路：预检（类型/大小→2004；NSFW/PII→2003）→ VLM(OpenAI 兼容 image_url)
      → {category, confidence, bbox?, desc, safe_pass} → 置信<阈值转人工。
单出口口径：业务只认 inspect_image()/probe()，换 Qwen3-VL 只改 Settings，
             禁止业务文件出现 URL/模型名/阈值字面量。
降级红线：VLM 不可用 → 规则 stub（文件名关键词）+ degraded=True，绝不 500；
           预检不通过才抛 BusinessError（2003/2004），调用方转 fail() 信封。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record

# ---------------- 常量 ----------------

CATEGORIES: tuple[str, ...] = (
    "污渍",
    "破洞",
    "脱线",
    "色差",
    "开线",
    "尺寸不符",
    "吊牌异常",
    "无瑕疵",
)

# stub 关键词 → 类别（VLM 未接时的确定性降级，供单测/演示/E2E 不中断）
_STUB_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("污", "污渍"),
    ("渍", "污渍"),
    ("破", "破洞"),
    ("洞", "破洞"),
    ("脱线", "脱线"),
    ("色差", "色差"),
    ("开线", "开线"),
    ("尺寸", "尺寸不符"),
    ("吊牌", "吊牌异常"),
)

# NSFW/PII 预检关键词（演示版：命中即拦截走人工；生产换审核网关）
_UNSAFE_KEYWORDS: tuple[str, ...] = ("nsfw", "色情", "赌", "毒", "人脸", "身份证", "face")


class VisionUnavailableError(Exception):
    """VLM 不可用（调用方转 stub 降级，不冒泡 500）。"""


@dataclass(frozen=True)
class VisionResult:
    """单张检测结果（need_human 由阈值判定，调用方直接转人工卡）。"""

    category: str
    confidence: float
    desc: str
    need_human: bool
    degraded: bool = False
    safe_pass: bool = True
    bbox: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """转可序列化字典（endpoint/SSE/chat 上下文同源）。"""
        return {
            "category": self.category,
            "confidence": self.confidence,
            "desc": self.desc,
            "need_human": self.need_human,
            "degraded": self.degraded,
            "safe_pass": self.safe_pass,
            "bbox": dict(self.bbox),
        }


# ---------------- 预检 ----------------


def precheck(*, filename: str, content_type: str, size: int) -> None:
    """类型/大小预检：非法 1001，超 10M 报 2004（FR-1.2 超限码）。"""
    allowed = set(settings.IMAGE_ALLOWED_TYPES)
    if content_type not in allowed:
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅支持 JPG/PNG/WEBP 图片", 400)
    if size <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请至少选择一个文件", 400)
    if size > settings.IMAGE_MAX_BYTES:
        raise BusinessError(ErrorCode.IMAGE_TOO_LARGE, "图片过大，请压缩后重试", 400)
    _ = filename


def safe_precheck(*, filename: str) -> dict[str, object]:
    """NSFW/PII 预检 stub：命中关键词 → safe_pass=False（调用方转 2003+人工）。

    生产替换点：此处换审核网关调用，签名 {safe_pass, reason} 不变。
    """
    name = (filename or "").lower()
    hit = next((k for k in _UNSAFE_KEYWORDS if k.lower() in name), "")
    if hit:
        return {"safe_pass": False, "reason": f"命中预检关键词 {hit}，已转人工复核"}
    return {"safe_pass": True, "reason": ""}


def _need_human(confidence: float) -> bool:
    """置信 <0.6 转人工（阈值走 Settings 热更）。"""
    return confidence < settings.VLM_CONFIDENCE_THRESHOLD


# ---------------- stub 降级 ----------------


def stub_inspect(*, filename: str) -> VisionResult:
    """规则降级：文件名关键词 → 类别 0.85；无命中 → 无瑕疵 0.55（必转人工复核）。

    0.55 的用意：演示不断流，但按阈值自动进人工，符合“不硬答”红线。
    """
    name = filename or ""
    for keyword, category in _STUB_KEYWORDS:
        if keyword in name:
            return VisionResult(
                category=category,
                confidence=0.85,
                desc=f"检测到疑似{category}（规则降级，文件名命中 {keyword}）",
                need_human=False,
                degraded=True,
            )
    return VisionResult(
        category="无瑕疵",
        confidence=0.55,
        desc="未发现明显瑕疵（规则降级），已转人工复核确认",
        need_human=True,
        degraded=True,
    )


# ---------------- VLM 在线（真图链路） ----------------


def _chat_url() -> str:
    return settings.VLM_BASE_URL.rstrip("/") + "/chat/completions"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.VLM_API_KEY.get_secret_value()}"}


async def _post_json(
    url: str, payload: dict[str, object], headers: dict[str, str]
) -> httpx.Response:
    """唯一的 VLM POST 出口（测试在此打桩；trust_env=False 防代理劫持本机网关）。"""
    async with httpx.AsyncClient(timeout=settings.VLM_TIMEOUT_SECONDS, trust_env=False) as client:
        return await client.post(url, json=payload, headers=headers)


def _downscale_image(raw: bytes) -> str:
    """真图预处理（同步，调用方走 to_thread）：RGB→最长边缩放→JPEG→data URL。

    图片损坏/不可解码抛 VisionUnavailableError，调用方转 stub 降级，绝不 500。
    """
    import base64
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((settings.VLM_MAX_EDGE, settings.VLM_MAX_EDGE))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=settings.VLM_JPEG_QUALITY)
    except Exception as exc:
        raise VisionUnavailableError(f"图片解码失败：{exc.__class__.__name__}") from exc
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _vlm_prompt() -> str:
    """结构化指令：只输出 JSON（类别 8 选 1 + 置信度 + 一句话描述 + 可选框）。"""
    cats = "、".join(CATEGORIES)
    return (
        "你是服装售后质检员。看这张买家上传的售后图，只输出一行 JSON："
        '{"category":"类别","confidence":0-1置信度,"desc":"一句话描述","bbox":[x,y,w,h]或null}。'
        f"类别只能是：{cats}。bbox 为瑕疵区相对坐标 0-1（无明确区域填 null）。"
        "不要输出 JSON 之外的任何文字。"
    )


def _clamp_confidence(raw: object, default: float = 0.55) -> float:
    """置信度钳制（纯函数）：非法/缺失回 default（默认 0.55 必转人工，不硬答）。"""
    confidence = (
        float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default
    )
    return max(0.0, min(1.0, round(confidence, 2)))


def _parse_vlm_result(text: str) -> VisionResult:
    """解析 VLM 结构化输出（纯函数可单测）：完整 JSON → 截断 JSON 字段正则 → 关键词兜底。

    小模型常输出截断 JSON（desc 写一半），字段级正则保证类别/置信度可回收；
    兜底置信度 0.55（必转人工复核，不硬答）；bbox 非法直接丢弃不断流。
    """
    import json as _json
    import re as _re

    body: object = None
    match = _re.search(r"\{.*\}", text or "", _re.DOTALL)
    if match:
        try:
            body = _json.loads(match.group(0))
        except ValueError:
            body = None
    if isinstance(body, dict):
        category = str(body.get("category", ""))
        if category not in CATEGORIES:
            category = next((c for c in CATEGORIES if c in str(body)), "无瑕疵")
        confidence = _clamp_confidence(body.get("confidence", 0.55))
        bbox: dict[str, float] = {}
        raw_box = body.get("bbox")
        if isinstance(raw_box, list) and len(raw_box) == 4:
            try:
                x, y, w, h = (max(0.0, min(1.0, float(v))) for v in raw_box)
                bbox = {"x": x, "y": y, "w": w, "h": h}
            except (TypeError, ValueError):
                bbox = {}
        return VisionResult(
            category=category,
            confidence=confidence,
            desc=str(body.get("desc", f"VLM 检测：{category}"))[:200] or f"VLM 检测：{category}",
            need_human=_need_human(confidence),
            degraded=False,
            bbox=bbox,
        )
    # 截断 JSON：逐字段回收（类别 8 选 1 精确匹配 + 置信度数字）
    field_cat = _re.search(r'"category"\s*:\s*"([^"]+)"', text or "")
    if field_cat and field_cat.group(1) in CATEGORIES:
        field_conf = _re.search(r'"confidence"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text or "")
        confidence = _clamp_confidence(float(field_conf.group(1)) if field_conf else 0.55)
        field_desc = _re.search(r'"desc"\s*:\s*"([^"]*)', text or "")
        return VisionResult(
            category=field_cat.group(1),
            confidence=confidence,
            desc=(field_desc.group(1)[:200] if field_desc else f"VLM 检测：{field_cat.group(1)}"),
            need_human=_need_human(confidence),
            degraded=False,
        )
    category = next((c for c in CATEGORIES if c in (text or "")), "")
    if category:
        return VisionResult(
            category=category,
            confidence=0.55,
            desc=f"VLM 文本兜底：{category}（已转人工复核）",
            need_human=True,
            degraded=False,
        )
    raise VisionUnavailableError("VLM 响应无可用信号")


def _ollama_url() -> str:
    """Ollama 原生地址（VLM_BASE_URL 去 /v1 后缀 + /api/chat，网关直连时同理）。"""
    base = settings.VLM_BASE_URL.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    return root + "/api/chat"


async def _vlm_call_openai(*, filename: str, data_url: str | None, started: float) -> VisionResult:
    """OpenAI 兼容分支（/v1/chat/completions + image_url + think 开关）。"""
    if data_url:
        user_content: object = [
            {"type": "text", "text": _vlm_prompt()},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    else:
        user_content = f"{_vlm_prompt()}文件名参考：{filename}"
    payload: dict[str, object] = {
        "model": settings.VLM_MODEL,
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": settings.VLM_MAX_TOKENS,
        "stream": False,
        # Ollama 思考模型关 thinking 直出结论（qwen3-vl 实测：开 thinking 只产 reasoning
        # 且 content 为空；OpenAI 官方端点若报未知参数 400，走网关兼容层即可）。
        "think": settings.VLM_THINK,
    }
    try:
        resp = await _post_json(_chat_url(), payload, _headers())
    except (httpx.HTTPError, OSError) as exc:
        raise VisionUnavailableError(f"VLM 不可达：{exc.__class__.__name__}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code >= 400:
        record("vlm", {"ok": False, "latency_ms": latency_ms})
        raise VisionUnavailableError(f"VLM 返回 HTTP {resp.status_code}")
    try:
        message = resp.json()["choices"][0]["message"]
        text = str(message.get("content", ""))
        # 思考模型经兼容层可能把结论落在 reasoning 段：合并解析
        for key in ("reasoning_content", "reasoning"):
            extra = message.get(key)
            if isinstance(extra, str) and extra.strip():
                text = f"{text}\n{extra}"
                break
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise VisionUnavailableError("VLM 响应结构异常") from exc
    return _parse_vlm_result(text)


async def _vlm_call_ollama(*, data_url: str | None, started: float) -> VisionResult:
    """Ollama 原生分支（/api/chat + images + think 开关，思考模型必经此路）。

    无真图字节时直接抛错走 stub（原生协议无纯文本检测意义，不浪费调用）。
    """
    if not data_url:
        raise VisionUnavailableError("Ollama 原生协议需要真图字节")
    payload: dict[str, object] = {
        "model": settings.VLM_MODEL,
        "stream": False,
        "think": settings.VLM_THINK,
        "messages": [
            {
                "role": "user",
                "content": _vlm_prompt(),
                "images": [data_url.split(",", 1)[1]],
            }
        ],
    }
    try:
        resp = await _post_json(_ollama_url(), payload, _headers())
    except (httpx.HTTPError, OSError) as exc:
        raise VisionUnavailableError(f"VLM 不可达：{exc.__class__.__name__}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code >= 400:
        record("vlm", {"ok": False, "latency_ms": latency_ms})
        raise VisionUnavailableError(f"VLM 返回 HTTP {resp.status_code}")
    try:
        text = str(resp.json()["message"]["content"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise VisionUnavailableError("VLM 响应结构异常") from exc
    result = _parse_vlm_result(text)
    record(
        "vlm",
        {
            "ok": True,
            "latency_ms": latency_ms,
            "model": settings.VLM_MODEL,
            "protocol": "ollama",
            "category": result.category,
        },
    )
    return result


async def _vlm_call(*, filename: str, image: bytes | None) -> VisionResult:
    """在线 VLM 分发：openai 兼容分支默认；ollama 原生分支给思考模型（协议走 Settings）。

    阻塞的 PIL 缩放走 to_thread；任何上游失败一律 VisionUnavailableError → stub。
    """
    import asyncio

    if not settings.VLM_ENABLED:
        raise VisionUnavailableError("VLM_ENABLED=false")
    data_url: str | None = None
    if image:
        data_url = await asyncio.to_thread(_downscale_image, image)
    started = time.perf_counter()
    if settings.VLM_PROTOCOL == "ollama":
        return await _vlm_call_ollama(data_url=data_url, started=started)
    result = await _vlm_call_openai(filename=filename, data_url=data_url, started=started)
    record(
        "vlm",
        {
            "ok": True,
            "model": settings.VLM_MODEL,
            "protocol": "openai",
            "has_image": data_url is not None,
            "category": result.category,
        },
    )
    return result


async def inspect_image(
    *, filename: str, content_type: str, size: int, image: bytes | None = None
) -> VisionResult:
    """检测主入口：预检 → 在线 VLM（真图）→ 失败转 stub；NSFW 命中抛 2003。

    image 为上传字节（端点透传）；None 时走文件名文本提示（兼容纯文本模型与历史单测）。
    预检 2003/2004 以 BusinessError 抛出（端点转 fail）；其余一律返回结果。
    """
    precheck(filename=filename, content_type=content_type, size=size)
    safe = safe_precheck(filename=filename)
    if not bool(safe["safe_pass"]):
        raise BusinessError(ErrorCode.UNSAFE_CONTENT, f"{safe['reason']}", 400)
    try:
        return await _vlm_call(filename=filename, image=image)
    except VisionUnavailableError as exc:
        record("vlm", {"ok": False, "degraded": str(exc)[:120]})
        return stub_inspect(filename=filename)


# ---------------- LLM 上下文（chat_service 复用，阈值/方案同源） ----------------

# 瑕疵类别 → 售后方案{退/换/补/修}（拼进 LLM 上下文，模型只做措辞不做定级）
VISION_SUGGEST: dict[str, str] = {
    "污渍": "建议换货或退货，时效 48 小时内发出新品",
    "破洞": "建议换货，时效 48 小时内发出新品，旧件拍照留存后寄回",
    "脱线": "建议维修或换货，时效 3 天内给出维修方案",
    "色差": "建议退换货，时效 7 天无理由内优先换货",
    "开线": "建议换货，时效 48 小时内发出新品",
    "尺寸不符": "建议换货（免费换尺码），时效 7 天内完成",
    "吊牌异常": "建议补发吊牌或换货，时效 3 天内处理",
    "无瑕疵": "未见明显瑕疵，已转人工复核确认，请安抚等待",
}


def sanitize_inspections(raw: object, max_count: int = 9) -> list[dict[str, object]]:
    """清洗前端透传的检测结果（类别白名单 + 置信度钳 0-1 + need_human 重算）。

    不信任前端 need_human：按 Settings 阈值重算，阈值热更即时生效。
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, object]] = []
    for item in raw[:max_count]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "无瑕疵"))
        if category not in CATEGORIES:
            category = "无瑕疵"
        raw_confidence: object = item.get("confidence", 0.0)
        if isinstance(raw_confidence, bool):
            confidence = 1.0 if raw_confidence else 0.0
        elif isinstance(raw_confidence, (int, float, str)):
            try:
                confidence = float(raw_confidence)
            except ValueError:
                confidence = 0.0
        else:
            confidence = 0.0
        confidence = max(0.0, min(1.0, round(confidence, 2)))
        cleaned.append(
            {
                "category": category,
                "confidence": confidence,
                "desc": str(item.get("desc", ""))[:200],
                "need_human": confidence < settings.VLM_CONFIDENCE_THRESHOLD,
                "degraded": bool(item.get("degraded", False)),
                "safe_pass": True,
                "bbox": {},
            }
        )
    return cleaned


def build_vision_context(inspections: list[dict[str, object]]) -> str:
    """检测结果 → LLM 上下文块（纯函数可单测）：定级 + 方案 + 时效 + 转人工标记。"""
    lines: list[str] = []
    for i, item in enumerate(inspections, 1):
        category = str(item.get("category", "无瑕疵"))
        raw: object = item.get("confidence", 0.0)
        if isinstance(raw, bool):
            confidence = 1.0 if raw else 0.0
        elif isinstance(raw, (int, float)):
            confidence = float(raw)
        else:
            try:
                confidence = float(str(raw))
            except ValueError:
                confidence = 0.0
        suggest = VISION_SUGGEST.get(category, "已转人工复核确认")
        flag = "（需转人工复核）" if bool(item.get("need_human")) else ""
        lines.append(
            f"图{i}：{category}（置信 {confidence:.2f}）{flag}；{item.get('desc', '')}；{suggest}"
        )
    return "\n".join(lines)


async def probe() -> dict[str, object]:
    """可用性巡检（供 /governance/status，加法字段，不抛异常）。"""
    base: dict[str, object] = {
        "provider": "vlm",
        "model": settings.VLM_MODEL,
        "base_url": settings.VLM_BASE_URL,
        "protocol": settings.VLM_PROTOCOL,
        "enabled": settings.VLM_ENABLED,
        "threshold": settings.VLM_CONFIDENCE_THRESHOLD,
    }
    if not settings.VLM_ENABLED:
        return {**base, "available": False, "detail": "VLM_ENABLED=false，检测走规则降级"}
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(settings.VLM_BASE_URL.rstrip("/") + "/models")
    except (httpx.HTTPError, OSError):
        return {**base, "available": False, "detail": "VLM 不可达，检测走规则降级（不中断）"}
    if resp.status_code >= 400:
        return {**base, "available": False, "detail": f"VLM 返回 HTTP {resp.status_code}"}
    return {**base, "available": True, "detail": "VLM 在线"}
