"""零依赖契约：只用标准库，且在 `python -S`（无 site-packages）下也能导入运行。

这个包的核心卖点是「装上一个 wheel 就能跑」；如果悄悄依赖 numpy/scipy，
在小 CI 容器里就会失效，所以把它变成测试而不是文档承诺。
"""
import ast
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PKG = HERE / "eval_gate"

# 常见「顺手就会 import」的第三方包；这个包不允许出现。
FORBIDDEN = {"numpy", "scipy", "pandas", "sklearn", "statsmodels", "pydantic",
             "requests", "yaml", "jsonschema"}


def _stdlib_names() -> set[str]:
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    # Python 3.9 没有 stdlib_module_names：退化成「本地模块 + 已知标准库前缀」。
    return {"__future__", "argparse", "bisect", "collections", "contextlib",
            "copy", "datetime", "hashlib", "importlib", "io", "json", "math",
            "os", "pathlib", "random", "re", "shutil", "subprocess", "sys",
            "tempfile", "time", "types", "typing", "unittest", "warnings"}


def _top_level_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


class ZeroDependencyTests(unittest.TestCase):
    def test_no_third_party_imports(self) -> None:
        allowed = _stdlib_names() | {"eval_gate"}
        flagged = set()
        for path in PKG.rglob("*.py"):
            for name in _top_level_imports(path):
                if name in FORBIDDEN:
                    flagged.add(f"{path.name}: {name}")
                elif name not in allowed:
                    flagged.add(f"{path.name}: {name}")
        self.assertEqual(flagged, set())

    def test_import_works_without_site_packages(self) -> None:
        """`-S` 不加载 site-packages：能导入即证明没有第三方运行时依赖。"""
        result = subprocess.run(
            [sys.executable, "-S", "-c",
             "import eval_gate.cli, eval_gate.runner, eval_gate.stats; print('ok')"],
            cwd=str(HERE), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_pyproject_declares_no_dependencies(self) -> None:
        text = (HERE / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = []", text)
        self.assertNotIn('"numpy"', text)
        self.assertNotIn('"scipy"', text)


if __name__ == "__main__":
    unittest.main()
