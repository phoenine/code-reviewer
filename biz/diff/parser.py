import re

from biz.model.diff import Diff


def _count_changed_lines(diff_text: str) -> tuple[int, int]:
    additions = len(re.findall(r"^\+(?!\+\+)", diff_text or "", re.MULTILINE))
    deletions = len(re.findall(r"^-(?!--)", diff_text or "", re.MULTILINE))
    return additions, deletions


def parse_gitlab_change(change: dict) -> Diff:
    diff_text = change.get("diff", "") or ""
    additions = change.get("additions")
    deletions = change.get("deletions")
    if additions is None or deletions is None:
        additions, deletions = _count_changed_lines(diff_text)
    warnings = list(change.get("warnings") or [])
    if change.get("too_large"):
        warnings.append("GitLab marked this file diff as too large; it may be incomplete.")
    if change.get("collapsed"):
        warnings.append("GitLab marked this file diff as collapsed; it may be incomplete.")
    if not diff_text and not change.get("binary") and not change.get("deleted_file"):
        warnings.append("GitLab did not return diff content for this file; it may be incomplete.")

    return Diff(
        old_path=change.get("old_path") or change.get("new_path") or "",
        new_path=change.get("new_path") or change.get("old_path") or "",
        diff=diff_text,
        additions=int(additions or 0),
        deletions=int(deletions or 0),
        is_new=bool(change.get("new_file")),
        is_deleted=bool(change.get("deleted_file")),
        is_binary=bool(change.get("binary")),
        source="gitlab",
        warnings=warnings,
        raw=change,
    )


def parse_github_file(file_change: dict) -> Diff:
    diff_text = file_change.get("patch") or file_change.get("diff") or ""
    additions = file_change.get("additions")
    deletions = file_change.get("deletions")
    if additions is None or deletions is None:
        additions, deletions = _count_changed_lines(diff_text)

    filename = file_change.get("filename") or file_change.get("new_path") or ""
    previous_filename = file_change.get("previous_filename") or file_change.get("old_path")
    status = file_change.get("status") or ""
    warnings = list(file_change.get("warnings") or [])
    if not diff_text and status not in {"removed", "added"} and not file_change.get("binary"):
        warnings.append(
            "GitHub did not return a patch for this modified file; the diff may be too large."
        )

    return Diff(
        old_path=previous_filename or filename,
        new_path=filename,
        diff=diff_text,
        additions=int(additions or 0),
        deletions=int(deletions or 0),
        is_new=status == "added",
        is_deleted=status == "removed",
        is_binary=not diff_text and bool(file_change.get("sha")),
        source="github",
        warnings=warnings,
        raw=file_change,
    )


def parse_changes(changes: list[dict], source: str) -> list[Diff]:
    if source == "gitlab":
        return [parse_gitlab_change(change) for change in changes]
    if source == "github":
        return [parse_github_file(change) for change in changes]
    raise ValueError(f"Unsupported diff source: {source}")
