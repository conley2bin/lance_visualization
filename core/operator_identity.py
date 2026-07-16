"""Operator name/key mapping used by visualization."""

from __future__ import annotations

import re
from typing import Any


OPERATOR_KEY_TO_NAME = {
    "s01": "车映彤",
    "s02": "孙轲",
    "s03": "李锦淏",
    "s04": "邢清娴",
}
OPERATOR_NAME_TO_KEY = {name: key for key, name in OPERATOR_KEY_TO_NAME.items()}


def _coerce_operator_token(raw_value: Any) -> str:
    if isinstance(raw_value, dict):
        for key in ("operators_name", "operator_name", "name", "operator_id", "operator", "id"):
            candidate = raw_value.get(key)
            if candidate not in (None, ""):
                return _coerce_operator_token(candidate)
        for candidate in raw_value.values():
            if candidate not in (None, "") and not isinstance(candidate, (dict, list, tuple)):
                return _coerce_operator_token(candidate)
        return ""
    if isinstance(raw_value, (list, tuple)):
        for candidate in raw_value:
            if candidate not in (None, "") and not isinstance(candidate, (dict, list, tuple)):
                return _coerce_operator_token(candidate)
        return ""
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def normalize_operator_key(raw_value: Any) -> str:
    token = _coerce_operator_token(raw_value)
    if not token:
        return "unknown"
    if token in OPERATOR_KEY_TO_NAME:
        return token
    if token in OPERATOR_NAME_TO_KEY:
        return OPERATOR_NAME_TO_KEY[token]
    lowered = token.lower()
    prefixed = re.fullmatch(r"s(\d+)", lowered)
    if prefixed:
        return f"s{int(prefixed.group(1)):02d}"
    if re.fullmatch(r"\d+", token):
        return f"s{int(token):02d}"
    return token


def normalize_operator_name(raw_value: Any) -> str:
    token = _coerce_operator_token(raw_value)
    if not token:
        return "unknown"
    if token in OPERATOR_NAME_TO_KEY:
        return token
    if token in OPERATOR_KEY_TO_NAME:
        return OPERATOR_KEY_TO_NAME[token]
    return OPERATOR_KEY_TO_NAME.get(normalize_operator_key(token), token)
