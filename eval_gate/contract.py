"""契约层：零依赖 JSONL 读写、sha256、schema 校验。

错误一律转成 EvalGateError：给出「哪里错 + 下一步做什么」，方便非作者用户自查。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from importlib import resources
from typing import Any

from .errors import EvalGateError
from .schema import validate


def load_schema(name: str) -> dict[str, Any]:
    try:
        root = resources.files("eval_gate").joinpath("schemas")
        data = root.joinpath(name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise EvalGateError(
            f"找不到内置 schema {name}",
            hint="安装包不完整：重新安装（pip install --force-reinstall eval-gate）；"
                 "源码运行时确认 eval_gate/schemas/ 存在",
        ) from exc
    data = json.loads(data)
    parsed: dict[str, Any] = data
    return parsed


def validate_instance(instance: dict[str, Any], schema_name: str) -> list[str]:
    return validate(instance, load_schema(schema_name))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: pathlib.Path | str) -> str:
    try:
        return sha256_bytes(pathlib.Path(path).read_bytes())
    except FileNotFoundError as exc:
        raise EvalGateError(
            f"文件不存在：{path}",
            hint="检查 --dataset / --predictions / --baseline-predictions 的路径；"
                 "相对路径以当前工作目录为准",
            where=str(path),
        ) from exc


def read_jsonl(path: pathlib.Path | str) -> list[dict[str, Any]]:
    target = pathlib.Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvalGateError(
            f"文件不存在：{target}",
            hint="检查路径拼写；相对路径以当前工作目录为准",
            where=str(target),
        ) from exc
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalGateError(
                f"第 {lineno} 行不是合法 JSON：{exc.msg}（第 {exc.colno} 列）",
                hint="每行必须是一个完整 JSON 对象；常见原因：尾逗号、中文引号、字符串未转义",
                where=str(target),
            ) from exc
        if not isinstance(row, dict):
            raise EvalGateError(
                f"第 {lineno} 行是 {type(row).__name__}，不是 JSON 对象",
                hint="每行写成 {id, family, ...}；数组/字符串不能直接作为一行",
                where=str(target),
            )
        rows.append(row)
    return rows


def write_jsonl(path: pathlib.Path | str, rows: list[dict[str, Any]]) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    target.write_text(body, encoding="utf-8")


def write_json(path: pathlib.Path | str, obj: dict[str, Any]) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")


def read_json_any(path: pathlib.Path | str) -> Any:
    """读取任意顶层类型的 JSON（tools 清单允许是数组）。错误同样给下一步。"""
    target = pathlib.Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalGateError(
            f"文件不存在：{target}",
            hint="检查路径拼写；相对路径以当前工作目录为准",
            where=str(target),
        ) from exc
    except json.JSONDecodeError as exc:
        raise EvalGateError(
            f"不是合法 JSON：{exc.msg}（第 {exc.colno} 列）",
            hint="工具清单可以是数组或对象；常见错误是尾逗号与中文引号",
            where=str(target),
        ) from exc


def read_json(path: pathlib.Path | str) -> dict[str, Any]:
    target = pathlib.Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalGateError(
            f"文件不存在：{target}",
            hint="确认路径；verify 需要 runs/<run_id>/run.json 与 verdict.json",
            where=str(target),
        ) from exc
    except json.JSONDecodeError as exc:
        raise EvalGateError(
            f"不是合法 JSON：{exc.msg}（第 {exc.colno} 列）",
            hint="手工改过 run.json 时最容易漏引号或逗号；无法修复就从 --out 重新跑一次",
            where=str(target),
        ) from exc
    if not isinstance(data, dict):
        raise EvalGateError(
            f"顶层是 {type(data).__name__}，不是对象",
            hint="run.json / verdict.json 顶层必须是 JSON 对象",
            where=str(target),
        )
    return data
