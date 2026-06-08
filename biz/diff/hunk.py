import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class HunkLine:
    type: str
    content: str


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine] = field(default_factory=list)


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_hunks(diff_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: Hunk | None = None

    for line in diff_text.splitlines():
        match = HUNK_HEADER_RE.match(line)
        if match:
            if current:
                hunks.append(current)
            current = Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or 1),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or 1),
            )
            continue

        if current is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current.lines.append(HunkLine(type="added", content=line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            current.lines.append(HunkLine(type="deleted", content=line[1:]))
        elif line.startswith(" "):
            current.lines.append(HunkLine(type="context", content=line[1:]))
        elif line == "":
            current.lines.append(HunkLine(type="context", content=""))

    if current:
        hunks.append(current)
    return hunks
