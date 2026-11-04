"""最小 JSON Schema 校验器（零依赖）。

来源（vendor，MIT）：
    agent-reliability/contracts/jsonschema_mini.py
    @ e86a865bb9c41e97faa2dc1fddc2a9cb8ab44420（上游仓见 VENDOR.md）

支持子集：type / required / properties / additionalProperties / items /
pattern / enum / const / minimum / maximum / minItems / maxItems /
minLength / maxLength / 同文档 $ref。
不实现 oneOf/anyOf/allOf/if-then-else/format——契约写复杂了应先改契约。
"""
from __future__ import annotations

import re
from typing import Any


def validate(instance: Any, schema: dict[str, Any], path: str = "$",
             root: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    if root is None:
        root = schema

    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is None:
            errors.append(f"{path}: 无法解析 $ref {schema['$ref']!r}")
            return errors
        return validate(instance, target, path, root)

    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, str):
            expected = [expected]
        if not any(_is_type(instance, t) for t in expected):
            errors.append(f"{path}: 期望类型 {expected}，实际 {type(instance).__name__}")
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 期望常量 {schema['const']!r}，实际 {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} 不在枚举 {schema['enum']} 内")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} 不匹配 pattern {schema['pattern']!r}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: 字符串长度 {len(instance)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: 字符串长度 {len(instance)} > maxLength {schema['maxLength']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: 数组长度 {len(instance)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: 数组长度 {len(instance)} > maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(validate(item, item_schema, f"{path}[{index}]", root))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, f"{path}.{key}", root))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra = sorted(set(instance) - set(props))
            if extra:
                errors.append(f"{path}: 出现未声明字段 {extra}")
        elif isinstance(additional, dict):
            for key in sorted(set(instance) - set(props)):
                errors.extend(validate(instance[key], additional, f"{path}.{key}", root))

    return errors


def _resolve_ref(ref: str, root: dict[str, Any]) -> Any:
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def _is_type(instance: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(instance, dict)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if type_name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "null":
        return instance is None
    return True
