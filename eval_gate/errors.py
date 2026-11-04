"""统一的输入错误：problem + next step，不抛 traceback。

CLI 捕获 EvalGateError 后输出：

    error: <哪里错了>
    next:  <下一步该做什么>
    exit 2
"""
from __future__ import annotations


class EvalGateError(Exception):
    """可预期的输入/契约错误。调用方应把它转成「error + next」两行。"""

    def __init__(self, problem: str, hint: str = "", where: str = "") -> None:
        super().__init__(problem)
        self.problem = problem
        self.hint = hint
        self.where = where

    def render(self) -> str:
        head = f"error: {self.problem}"
        if self.where:
            head = f"error: {self.where}: {self.problem}"
        lines = [head]
        if self.hint:
            lines.append(f"next:  {self.hint}")
        return "\n".join(lines)
