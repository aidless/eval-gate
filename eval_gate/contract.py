"""契约层：零依赖 JSONL 读写、sha256、schema 校验。"""
from __future__ import annotations

import hashlib
import json
import pathlib

from .schema import validate

SCHEMA_DIR = pathlib.Path(__file__).resolve().parent / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate_instance(instance: dict, schema_name: str) -> list[str]:
    return validate(instance, load_schema(schema_name))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: pathlib.Path | str) -> str:
    return sha256_bytes(pathlib.Path(path).read_bytes())


def read_jsonl(path: pathlib.Path | str) -> list[dict]:
    rows = []
    for lineno, line in enumerate(
            pathlib.Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} JSON 解析失败: {exc}") from exc
    return rows


def write_jsonl(path: pathlib.Path | str, rows: list[dict]) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def write_json(path: pathlib.Path | str, obj: dict) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def read_json(path: pathlib.Path | str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
