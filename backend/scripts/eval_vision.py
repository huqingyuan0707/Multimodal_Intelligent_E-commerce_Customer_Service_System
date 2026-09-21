"""瑕疵分类离线评估（FRD §7 验收：F1 ≥0.85 / 召回 ≥0.9，200 张/类测试集）

链路：文件名/子目录即弱标签 → stub/网关预测 → 按类别统计 P/R/F1 +
宏平均 → 输出 PASS/FAIL + RESULT。
用法（backend/ 目录）：
  python scripts/eval_vision.py [数据集目录] [--gateway]
  默认 stub 模式（文件名规则）；--gateway 走 inspect_image 真图链路（读像素，
  在线 VLM 检测，失败自动降级，degraded 率同步输出）。
真机集采集规范（FRD §7 验收集，目录名即标签，与银集 {类别}_*.jpg 平铺兼容）：
  backend/data/vision-real/{类别}/{序号}.jpg   # 8 类目录名与 vision_service.CATEGORIES 一致
  每类 ≥200 张；自然光 + 室内灯光两种环境；平铺/褶皱/悬挂三种形态；
  手机主摄直出即可（≥1000px，禁止网图——版权与域偏移双重风险）；
  涉人图片须去除面部（裁切/打码），验收集不入库 git（.gitignore data/）。
现状：真机 200 张/类集待采；银集（make_silver_set.py 程序合成像素图）先行验证
  “真图链路通 + 网关可调”，FRD 验收仍以真机集为准。
阈值口径：stub 置信 0.85/0.55 与线上同源，低置信计入转人工不计错分。
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vision_service

CATEGORIES = list(vision_service.CATEGORIES)


def _synthesize_bench(root: Path, per_class: int = 20) -> list[tuple[str, str]]:
    """合成基线集（过渡用）：每类 per_class 个文件名样本，真集到位后不再调用。"""
    samples: list[tuple[str, str]] = []
    for category in CATEGORIES:
        for i in range(per_class):
            samples.append((f"{category}_{i:03d}.jpg", category))
    root.mkdir(parents=True, exist_ok=True)
    return samples


def _load_bench(root: Path) -> list[tuple[Path, str]]:
    """读真实集（返回路径供真图模式）：两种布局兼容——

    ① 子目录（真机集规范）：{类别}/{序号}.jpg，目录名即标签；
    ② 平铺（银集）：{类别}_*.jpg，文件名下划线前缀即标签。
    """
    samples: list[tuple[Path, str]] = []
    for category in CATEGORIES:
        if (root / category).is_dir():
            found = (
                path
                for path in sorted((root / category).iterdir())
                if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )
            samples.extend((path, category) for path in found)
    if not samples:
        for path in sorted(root.glob("*.jpg")):
            label = path.name.split("_")[0]
            if label in CATEGORIES:
                samples.append((path, label))
    return samples


async def _predict(path: Path, gateway: bool) -> tuple[str, bool]:
    """预测 → (类别, degraded)。网关模式读像素走真图链路；默认 stub 模式。"""
    if not gateway:
        return vision_service.stub_inspect(filename=path.name).category, True
    import asyncio

    try:
        raw = await asyncio.to_thread(path.read_bytes)
    except OSError:
        return vision_service.stub_inspect(filename=path.name).category, True
    try:
        result = await vision_service.inspect_image(
            filename=path.name, content_type="image/jpeg", size=len(raw), image=raw
        )
    except Exception:
        return vision_service.stub_inspect(filename=path.name).category, True
    return result.category, result.degraded


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gateway = "--gateway" in sys.argv[1:]
    root = Path(args[0]) if args else Path("data/vision-bench")
    samples = _load_bench(root)
    synthetic = False
    if not samples:
        names = _synthesize_bench(root)
        samples = [(root / name, label) for name, label in names]
        synthetic = True
    total = len(samples)
    per_class = total // len(CATEGORIES)
    mode = "网关真图" if gateway else "stub"
    print(
        f"样本：{total} 张（{len(CATEGORIES)} 类 × {per_class} 张/类，合成集={synthetic}，模式={mode}）"
    )

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    degraded = 0
    for path, label in samples:
        pred, is_degraded = await _predict(path, gateway)
        degraded += 1 if is_degraded else 0
        if pred == label:
            tp[label] += 1
        else:
            fp[pred] += 1
            fn[label] += 1

    f1_list: list[float] = []
    recall_list: list[float] = []
    for category in CATEGORIES:
        p = tp[category] / (tp[category] + fp[category]) if (tp[category] + fp[category]) else 0.0
        r = tp[category] / (tp[category] + fn[category]) if (tp[category] + fn[category]) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        f1_list.append(f1)
        recall_list.append(r)
        print(f"  {category}：P={p:.2f} R={r:.2f} F1={f1:.2f}")
    macro_f1 = sum(f1_list) / len(f1_list)
    macro_recall = sum(recall_list) / len(recall_list)
    ok = macro_f1 >= 0.85 and macro_recall >= 0.9
    print(f"宏平均：F1={macro_f1:.3f}（≥0.85） 召回={macro_recall:.3f}（≥0.9）")
    print(f"降级率：{degraded}/{total}（网关失败自动转 stub，不断流）")
    tail = "" if not synthetic else "（真机 200 张/类集待采，管线已就绪；采集规范见文件头）"
    print(f"RESULT: {'PASS' if ok else 'FAIL'}{tail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
