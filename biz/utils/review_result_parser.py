import json
import re
from typing import Any

import yaml

from biz.model.review_comment import ReviewComment, ReviewResult
from biz.utils.log import logger


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, re.DOTALL)
    return match.group(1).strip() if match else stripped


def _extract_json_object(text: str) -> str:
    stripped = _strip_code_fence(text)
    start = stripped.find("{")
    if start == -1:
        return stripped

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return stripped[start:]


def _load_structured_result(text: str) -> dict:
    candidate = _extract_json_object(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Some models return JSON-looking YAML, or strings with literal newlines.
        data = yaml.safe_load(candidate)
    if not isinstance(data, dict):
        raise ValueError("review result must be a JSON object")
    return data


def _coerce_score(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_comment(item: dict) -> ReviewComment | None:
    path = str(item.get("path") or "").strip()
    content = str(item.get("content") or "").strip()
    existing_code = str(item.get("existing_code") or "").strip()
    if not path or not content or not existing_code:
        logger.warning("Skip invalid review comment: %s", item)
        return None

    return ReviewComment(
        path=path,
        content=content,
        existing_code=existing_code,
        severity=item.get("severity") or "medium",
        category=item.get("category") or "",
    )


def parse_review_result(raw_text: str) -> ReviewResult:
    text = raw_text.strip()
    if not text:
        return ReviewResult(summary="", raw_text=raw_text, parse_error="empty response")

    try:
        data = _load_structured_result(text)
    except (json.JSONDecodeError, yaml.YAMLError, ValueError, TypeError) as exc:
        return ReviewResult(summary=text, raw_text=raw_text, parse_error=str(exc))

    comments: list[ReviewComment] = []
    raw_comments = data.get("comments") or []
    if isinstance(raw_comments, list):
        for item in raw_comments:
            if isinstance(item, dict):
                comment = _parse_comment(item)
                if comment:
                    comments.append(comment)
    else:
        logger.warning("Review comments is not a list: %s", raw_comments)

    return ReviewResult(
        summary=str(data.get("summary") or "").strip(),
        score=_coerce_score(data.get("score")),
        risk_level=str(data.get("risk_level") or "").strip(),
        merge_advice=str(data.get("merge_advice") or "").strip(),
        comments=comments,
        raw_text=raw_text,
    )
