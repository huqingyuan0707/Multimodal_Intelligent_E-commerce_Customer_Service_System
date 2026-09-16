"""新增大二进制拦截（治「历史体积只增不减」：加密二进制无增量压缩空间，必须走 LFS）

链路：pre-commit（暂存区模式）+ CI large-files job（--range 模式）→ 扫新增/修改文件 →
二进制且超 100KB 且未被 LFS 接管即 FAIL。放行条件（任一）：纯文本；二进制 ≤100KB；
`git lfs track` 已接管该路径（入库的是 ~130B 指针）。
用法：
  python scripts/check_large_files.py
  python scripts/check_large_files.py --range <BASE>..<HEAD>
退出码：0=通过，1=ERROR。对齐 AGENTS.md §6「新约定优先写成可执行检查」。
"""

from __future__ import annotations

import argparse
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIMIT_BYTES = 102400  # 100KB：design.pen（~490KB）必拦，小图标放行
SAMPLE_BYTES = 8192  # git 同口径：首 8KB 含 NUL 即二进制


def git_out(*args: str) -> bytes:
    """调 git 取原始字节（-z + 显式 UTF-8 解码，中文路径不经系统 locale 中转）。"""
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True,
        check=True,
    )
    return out.stdout


def candidates(range_ref: str | None) -> list[str]:
    """候选清单：新增/修改的文件（删除不占新增体积，不管）。"""
    if range_ref:
        raw = git_out("diff", "--name-only", "-z", "--diff-filter=AM", range_ref)
    else:
        raw = git_out("diff", "--cached", "--name-only", "-z", "--diff-filter=AM")
    return [p for p in raw.decode("utf-8", errors="replace").split("\0") if p]


def lfs_managed(path: str) -> bool:
    """该路径是否已被 LFS 接管（.gitattributes filter=lfs，入库即指针）。"""
    out = git_out("check-attr", "filter", "--", path).decode("utf-8", errors="replace")
    return out.strip().endswith("filter: lfs")


def check(path: str, ref: str) -> str | None:
    """单个文件是否违规：返回违规说明，通过返回 None（读 git 对象，不依赖工作区）。"""
    if lfs_managed(path):
        return None
    size = int(git_out("cat-file", "-s", f"{ref}:{path}").decode().strip())
    if size <= LIMIT_BYTES:
        return None
    sample = subprocess.run(
        ["git", "cat-file", "-p", f"{ref}:{path}"], capture_output=True, check=True
    ).stdout[:SAMPLE_BYTES]
    if b"\0" not in sample:
        return None
    return f"{path}（{size // 1024}KB）：新增大二进制请走 LFS（git lfs track 同类 pattern 后重加），勿直入库"


def main() -> int:
    parser = argparse.ArgumentParser(description="新增大二进制拦截")
    parser.add_argument(
        "--range", default=None, help="CI 模式：扫描 <BASE>..<HEAD> 变更"
    )
    args = parser.parse_args()

    ref = "HEAD" if args.range else ""
    bad = [msg for p in candidates(args.range) if (msg := check(p, ref))]
    for msg in bad:
        print(f"[ERROR] {msg}")
    scope = args.range or "暂存区"
    print(f"\nRESULT: {'FAIL' if bad else 'PASS'}（{scope}，ERROR {len(bad)}）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
