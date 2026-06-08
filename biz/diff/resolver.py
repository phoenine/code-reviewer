from dataclasses import dataclass

from biz.diff.hunk import Hunk, parse_hunks
from biz.model.diff import Diff
from biz.model.review_comment import ReviewComment


@dataclass(slots=True)
class IndexedLine:
    line_num: int
    content: str


def _normalize_line(line: str) -> str:
    if line.startswith(("+", "-")):
        line = line[1:]
    return line.strip()


def _target_lines(existing_code: str) -> list[str]:
    lines = [_normalize_line(line) for line in existing_code.splitlines()]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _extract_side_lines(hunk: Hunk, new_side: bool) -> list[IndexedLine]:
    old_line = hunk.old_start
    new_line = hunk.new_start
    indexed: list[IndexedLine] = []

    for line in hunk.lines:
        if line.type == "context":
            indexed.append(
                IndexedLine(
                    line_num=new_line if new_side else old_line,
                    content=_normalize_line(line.content),
                )
            )
            old_line += 1
            new_line += 1
        elif line.type == "added":
            if new_side:
                indexed.append(
                    IndexedLine(line_num=new_line, content=_normalize_line(line.content))
                )
            new_line += 1
        elif line.type == "deleted":
            if not new_side:
                indexed.append(
                    IndexedLine(line_num=old_line, content=_normalize_line(line.content))
                )
            old_line += 1

    return indexed


def _match_consecutive(
    indexed_lines: list[IndexedLine], target_lines: list[str]
) -> tuple[int, int] | None:
    if not indexed_lines or not target_lines or len(target_lines) > len(indexed_lines):
        return None

    target_len = len(target_lines)
    for idx in range(len(indexed_lines) - target_len + 1):
        candidate = indexed_lines[idx : idx + target_len]
        if [line.content for line in candidate] == target_lines:
            return candidate[0].line_num, candidate[-1].line_num
    return None


def resolve_comment(comment: ReviewComment, diff: Diff) -> bool:
    if comment.line_resolved:
        return True
    if not comment.existing_code:
        comment.resolve_reason = "missing existing_code"
        return False

    target_lines = _target_lines(comment.existing_code)
    if not target_lines:
        comment.resolve_reason = "empty existing_code"
        return False

    hunks = parse_hunks(diff.diff)
    if not hunks:
        comment.resolve_reason = "diff has no hunks"
        return False

    for hunk in hunks:
        match = _match_consecutive(_extract_side_lines(hunk, new_side=True), target_lines)
        if match:
            comment.start_line, comment.end_line = match
            comment.line_resolved = True
            comment.resolve_reason = "matched new side"
            return True

    for hunk in hunks:
        match = _match_consecutive(_extract_side_lines(hunk, new_side=False), target_lines)
        if match:
            comment.start_line, comment.end_line = match
            comment.line_resolved = True
            comment.resolve_reason = "matched old side"
            return True

    comment.resolve_reason = "existing_code not found in diff"
    return False


def resolve_line_numbers(
    comments: list[ReviewComment], diffs: list[Diff]
) -> list[ReviewComment]:
    diff_by_path: dict[str, Diff] = {}
    for diff in diffs:
        if diff.new_path:
            diff_by_path[diff.new_path] = diff
        if diff.old_path:
            diff_by_path[diff.old_path] = diff

    for comment in comments:
        if not comment.path:
            comment.resolve_reason = "missing comment path"
            continue
        diff = diff_by_path.get(comment.path)
        if not diff:
            comment.resolve_reason = "diff not found for path"
            continue
        resolve_comment(comment, diff)
    return comments
