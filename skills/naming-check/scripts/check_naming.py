"""命名规范检查（对齐 skill naming-check）

链路：扫描 backend/app（AST：函数/类/模块常量命名 + 泛化命名黑名单 + 单字母参数 + 文件名）
      + frontend/src（composables/stores/.vue 文件名 + 泛化命名黑名单）
      → 与棘轮基线比对（存量只准减不准增，新增即红）
      → 输出 PASS/FAIL + RESULT → 退出码反映成败。

用法：python skills/naming-check/scripts/check_naming.py [repo_root]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Windows 控制台中文兜底
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined, union-attr]

# ---------------- 规则名 ----------------
RULE_PY_FILE_NAME = "py-file-name"  # backend/app 文件必须 snake_case
RULE_FUNC_NAME = "func-name-style"  # 函数/方法必须 snake_case（dunder 除外）
RULE_CLASS_NAME = "class-name-style"  # 类必须 PascalCase
RULE_CONST_NAME = "const-name-style"  # 模块级常量禁止 camelCase/混合大小写
RULE_PY_GENERIC = "py-generic-name"  # 后端泛化/无意义命名黑名单
RULE_PY_SINGLE_LETTER = "py-single-letter"  # 后端单字母参数（循环/坐标白名单除外）
RULE_FE_COMPOSABLE = "fe-composable-name"  # composables/*.ts 必须 useXxx
RULE_FE_VUE_NAME = "fe-vue-name"  # 所有 .vue 必须 PascalCase
RULE_FE_STORE = "fe-store-name"  # stores/*.ts 必须 camelCase
RULE_FE_GENERIC = "fe-generic-name"  # 前端泛化/无意义命名黑名单

# ---------------- 泛化命名黑名单（语义空洞，anti-shit-code §1.3 的屎山早期信号） ----------------
GENERIC_NAME_RE = re.compile(
    r"^(?:"
    r"foo\d*|bar\d*|baz\d*|asdf|qwerty|zxcv|xxx|yyy|zzz|a{3,}|"
    r"temp\d*|tmp\d*|func\d*|fn\d*|test\d*|var\d*|obj\d*|thing\d*|stuff|"
    r"data1\d*|info1\d*|list1\d*|result1\d*|value1\d*|"
    r"do_something|do_something_else|do_everything|handle_stuff|process_data|process_things|"
    r"my_func|my_function|new_func|old_func|callback1\d*"
    r")$",
    re.IGNORECASE,
)

# 前端声明处泛化命名（const/let/var/function 后紧跟黑名单词）
FE_GENERIC_DECL_RE = re.compile(
    r"\b(?:const|let|var|function)\s+("
    r"temp\d*|tmp\d*|foo\d*|bar\d*|baz\d*|asdf|qwerty|xxx|yyy|zzz|a{3,}|"
    r"func\d*|fn\d*|test\d*|var\d*|obj\d*|thing\d*|stuff|"
    r"data1\d*|list1\d*|result1\d*|value1\d*|"
    r"doSomething|doEverything|handleStuff|processData|processThings|myFunc|newFunc|oldFunc"
    r")\b",
    re.IGNORECASE,
)

# 单字母参数白名单：循环变量 / 数学坐标 / 占位 / 数学对偶 a,b / 查询 q
SINGLE_LETTER_ALLOW = {"_", "i", "j", "k", "n", "x", "y", "z", "a", "b", "q"}

SNAKE_RE = re.compile(r"^_?[a-z][a-z0-9_]*$")
UPPER_SNAKE_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
PASCAL_RE = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")
CAMEL_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")
DUNDER_RE = re.compile(r"^__.+__$")

# 棘轮基线：(相对路径, 规则名) -> 允许的最大违规数。清零后请删除对应条目并收紧。
BASELINE: dict[tuple[str, str], int] = {
    (
        "frontend/src/api/approvals.ts",
        RULE_FE_GENERIC,
    ): 1,  # `const obj` 兼容包装，触碰时改名 rawPage
}


def find_repo_root(start: Path) -> Path | None:
    """从脚本目录向上找到含 backend/app 的仓库根。"""
    for candidate in [start, *start.parents]:
        if (candidate / "backend" / "app").is_dir():
            return candidate
    return None


def is_bad_module_const(name: str) -> bool:
    """模块级赋值命名判定：dunder（__all__）/ snake 变量 / 全大写常量 / PascalCase 类型别名
    均放行（含单下划线前缀的私有形式，如 _LUA_RESERVE、_SessionFactory），
    拦截 camelCase（myVar）与混合大小写下划线（Max_Lines）这类四不像。"""
    if DUNDER_RE.fullmatch(name):
        return False
    if SNAKE_RE.fullmatch(name):
        return False
    if UPPER_SNAKE_RE.fullmatch(name):
        return False
    return not PASCAL_RE.fullmatch(name)


def scan_python(root: Path) -> list[tuple[str, str, int, str]]:
    """扫描 backend/app：返回 (相对路径, 规则, 行号, 命名) 违规列表。"""
    violations: list[tuple[str, str, int, str]] = []
    app_dir = root / "backend" / "app"
    for py in sorted(app_dir.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        # 文件名必须 snake_case（__init__.py 除外）
        stem = py.stem
        if stem != "__init__" and not SNAKE_RE.fullmatch(stem):
            violations.append((rel, RULE_PY_FILE_NAME, 1, py.name))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue  # 语法错误交给 py_compile / ruff，不在这里重复报
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if DUNDER_RE.fullmatch(name):
                    continue
                if not SNAKE_RE.fullmatch(name):
                    violations.append((rel, RULE_FUNC_NAME, node.lineno, name))
                elif GENERIC_NAME_RE.fullmatch(name):
                    violations.append((rel, RULE_PY_GENERIC, node.lineno, name))
                for arg in node.args.args + node.args.kwonlyargs:
                    pname = arg.arg
                    if len(pname) == 1 and pname not in SINGLE_LETTER_ALLOW:
                        violations.append(
                            (
                                rel,
                                RULE_PY_SINGLE_LETTER,
                                node.lineno,
                                f"{name}({pname})",
                            )
                        )
            elif isinstance(node, ast.ClassDef):
                name = node.name
                if not PASCAL_RE.fullmatch(name):
                    violations.append((rel, RULE_CLASS_NAME, node.lineno, name))
                elif GENERIC_NAME_RE.fullmatch(name):
                    violations.append((rel, RULE_PY_GENERIC, node.lineno, name))
        # 模块级常量命名（只看顶层赋值）
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.target is not None:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and is_bad_module_const(target.id):
                    violations.append((rel, RULE_CONST_NAME, node.lineno, target.id))
    return violations


def scan_frontend(root: Path) -> list[tuple[str, str, int, str]]:
    """扫描 frontend/src：文件名规则 + 泛化命名声明黑名单。"""
    violations: list[tuple[str, str, int, str]] = []
    src = root / "frontend" / "src"
    if not src.is_dir():
        return violations

    composables = src / "composables"
    if composables.is_dir():
        for f in sorted(composables.glob("*.ts")):
            if f.name.endswith(".test.ts"):
                continue
            stem = f.name[:-3]
            if not re.fullmatch(r"use[A-Z][A-Za-z0-9]*", stem):
                violations.append(
                    (f.relative_to(root).as_posix(), RULE_FE_COMPOSABLE, 1, f.name)
                )

    stores = src / "stores"
    if stores.is_dir():
        for f in sorted(stores.glob("*.ts")):
            if f.name.endswith(".test.ts") or f.name == "index.ts":
                continue
            stem = f.name[:-3]
            if not CAMEL_RE.fullmatch(stem):
                violations.append(
                    (f.relative_to(root).as_posix(), RULE_FE_STORE, 1, f.name)
                )

    for vue in sorted(src.rglob("*.vue")):
        stem = vue.stem
        if not PASCAL_RE.fullmatch(stem):
            violations.append(
                (vue.relative_to(root).as_posix(), RULE_FE_VUE_NAME, 1, vue.name)
            )

    for fe_file in sorted(src.rglob("*.ts")) + sorted(src.rglob("*.vue")):
        if "/node_modules/" in str(fe_file):
            continue
        rel = fe_file.relative_to(root).as_posix()
        try:
            text = fe_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            m = FE_GENERIC_DECL_RE.search(line)
            if m:
                violations.append((rel, RULE_FE_GENERIC, lineno, m.group(1)))
    return violations


def apply_ratchet(
    violations: list[tuple[str, str, int, str]],
) -> tuple[list[tuple[str, str, int, str]], list[str]]:
    """棘轮比对：返回 (新增违规, 收紧提示)。基线内存量不判红，只记数。"""
    per_key: dict[tuple[str, str], list[tuple[str, str, int, str]]] = {}
    for v in violations:
        per_key.setdefault((v[0], v[1]), []).append(v)

    new_violations: list[tuple[str, str, int, str]] = []
    tighten_hints: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    for key, items in per_key.items():
        seen_keys.add(key)
        allowed = BASELINE.get(key, 0)
        if len(items) > allowed:
            new_violations.extend(items[allowed:] if allowed else items)
        if key in BASELINE and len(items) < allowed:
            tighten_hints.append(
                f"  {key[0]} [{key[1]}] 现存 {len(items)} < 基线 {allowed}，请收紧 BASELINE"
            )
    for key in BASELINE:
        if key not in seen_keys:
            tighten_hints.append(f"  {key[0]} [{key[1]}] 已清零，请从 BASELINE 删除")
    return new_violations, tighten_hints


def main() -> int:
    start = (
        Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve()
    )
    root = find_repo_root(start)
    if root is None:
        print("FAIL: 未找到仓库根（需含 backend/app）")
        return 1

    all_violations = scan_python(root) + scan_frontend(root)
    new_violations, tighten_hints = apply_ratchet(all_violations)

    baselined = len(all_violations) - len(new_violations)

    print("=== 命名检查（naming-check）===")
    if all_violations:
        print(
            f"共发现 {len(all_violations)} 处命名信号，其中基线内存量 {baselined} 处，新增 {len(new_violations)} 处："
        )
        for rel, rule, lineno, name in sorted(all_violations):
            tag = "NEW " if (rel, rule, lineno, name) in set(new_violations) else "BASE"
            print(f"  [{tag}] {rel}:{lineno}  {rule:<20} {name}")
    else:
        print("未发现命名违规。")
    if tighten_hints:
        print("=== 棘轮收紧提示（债务减少，请同步收紧基线）===")
        for hint in tighten_hints:
            print(hint)

    print()
    if new_violations:
        print(f"FAIL: 新增命名违规 {len(new_violations)} 处（存量只准减不准增）")
        print(
            f"RESULT: {len(all_violations)} signals, {len(new_violations)} NEW violations, {baselined} baselined"
        )
        return 1
    print("PASS: 命名检查通过")
    print(
        f"RESULT: {len(all_violations)} signals, 0 NEW violations, {baselined} baselined"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
