from dataclasses import dataclass, field
from typing import Literal


Severity = Literal["high", "medium", "low", "info"]


@dataclass(slots=True)
class ReviewComment:
    path: str
    content: str
    existing_code: str
    severity: Severity = "medium"
    category: str = ""
    start_line: int | None = None
    end_line: int | None = None
    line_resolved: bool = False
    resolve_reason: str = ""


@dataclass(slots=True)
class ReviewResult:
    summary: str
    score: int | None = None
    risk_level: str = ""
    merge_advice: str = ""
    comments: list[ReviewComment] = field(default_factory=list)
    raw_text: str = ""
    parse_error: str = ""
