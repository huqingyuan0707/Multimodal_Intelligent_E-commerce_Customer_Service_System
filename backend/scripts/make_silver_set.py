"""银集生成（程序合成像素图，非真机实拍，对齐 FRD §7 真机集过渡）

链路：PIL 按类别画瑕疵（污渍斑块/破洞裂口/脱线/半幅色差/开线/尺寸双框/离位吊牌/
无瑕疵纯布）→ {类别}_{nnn}.jpg → 直接喂 scripts/eval_vision.py --gateway 复测。
用法（backend/ 目录）：python scripts/make_silver_set.py [输出目录] [每类张数]
口径：银集只验“真图链路通 + 网关可调”，FRD 验收仍以 200 张/类真机集为准。
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CATEGORIES = ["污渍", "破洞", "脱线", "色差", "开线", "尺寸不符", "吊牌异常", "无瑕疵"]


def _cloth(draw, size: int, rng: random.Random) -> None:
    """布纹底：浅灰 + 随机噪点。"""
    draw.rectangle([0, 0, size, size], fill=(218, 218, 214))
    for _ in range(400):
        x, y = rng.randrange(size), rng.randrange(size)
        v = 200 + rng.randrange(40)
        draw.point((x, y), fill=(v, v, v - 4))


def _paint(category: str, seed: int, size: int = 320):
    """按类别画瑕疵（纯函数绘图，随机种子保证可复现）。"""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    img = Image.new("RGB", (size, size), (218, 218, 214))
    draw = ImageDraw.Draw(img)
    _cloth(draw, size, rng)
    cx, cy = size // 2 + rng.randrange(-40, 40), size // 2 + rng.randrange(-40, 40)
    if category == "污渍":
        for r in (46, 34, 22):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(96, 74, 52))
    elif category == "破洞":
        draw.polygon(
            [(cx - 50, cy + 8), (cx - 10, cy - 10), (cx + 40, cy + 6), (cx + 5, cy + 18)],
            fill=(18, 18, 18),
        )
    elif category == "脱线":
        for i in range(5):
            y = cy - 30 + i * 14
            draw.line(
                [(cx - 60, y), (cx + 60, y + rng.randrange(-8, 8))], fill=(120, 120, 116), width=2
            )
        draw.line([(cx - 60, cy + 44), (cx + 58, cy + 30)], fill=(60, 60, 58), width=3)
    elif category == "色差":
        draw.rectangle([0, 0, size // 2, size], fill=(196, 178, 168))
    elif category == "开线":
        draw.line([(cx - 70, cy), (cx + 70, cy)], fill=(150, 150, 146), width=4)
        draw.line([(cx - 20, cy - 4), (cx + 30, cy + 6)], fill=(20, 20, 20), width=5)
    elif category == "尺寸不符":
        draw.rectangle([40, 60, 200, 260], outline=(70, 70, 68), width=4)
        draw.rectangle([60, 90, 150, 230], outline=(150, 60, 60), width=3)
    elif category == "吊牌异常":
        draw.line([(cx, 40), (cx + 60, 90)], fill=(90, 90, 88), width=2)
        draw.rectangle([cx + 60, 90, cx + 140, 140], outline=(60, 60, 58), width=3)
    return img


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/silver")
    per_class = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    for category in CATEGORIES:
        for i in range(per_class):
            img = _paint(category, seed=hash((category, i)) % (2**31))
            img.save(root / f"{category}_{i:03d}.jpg", quality=90)
            total += 1
    print(f"银集：{total} 张（{len(CATEGORIES)} 类 × {per_class} 张/类）→ {root}")
    print("复测：python scripts/eval_vision.py data/silver --gateway")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
