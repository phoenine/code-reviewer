import os
from collections.abc import Callable

from biz.diff.hunk import parse_hunks
from biz.model.diff import Diff
from biz.model.review_context import ContextBlock, FileContext, ReviewContext
from biz.utils.log import logger


DEFAULT_CONTEXT_LINES = 40
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_CHARS_PER_FILE = 12000
DEFAULT_MAX_TOTAL_CHARS = 50000
DEFAULT_MAX_SOURCE_CHARS = 200000


def review_context_enabled() -> bool:
    return os.getenv("REVIEW_CONTEXT_ENABLED", "1") == "1"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _line_ranges_for_diff(diff: Diff, context_lines: int) -> list[tuple[int, int]]:
    context_lines = max(context_lines, 0)
    ranges = []
    for hunk in parse_hunks(diff.diff):
        if hunk.new_count == 0:
            continue
        start = max(1, hunk.new_start - context_lines)
        end = hunk.new_start + hunk.new_count + context_lines - 1
        ranges.append((start, end))
    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def _slice_file_content(
    file_content: str,
    ranges: list[tuple[int, int]],
    max_chars: int,
) -> list[ContextBlock]:
    if not file_content or max_chars <= 0:
        return []

    lines = file_content.splitlines()
    if not lines:
        return []

    blocks: list[ContextBlock] = []
    remaining_chars = max_chars

    for start, end in ranges:
        if remaining_chars <= 0:
            break
        if start <= 0 or end <= 0 or end < start:
            continue
        actual_start = max(1, start)
        if actual_start > len(lines):
            continue
        actual_end = min(end, len(lines))
        if actual_start > actual_end:
            continue

        selected_lines = lines[actual_start - 1 : actual_end]
        content = "\n".join(
            f"{line_no}|{line}"
            for line_no, line in enumerate(selected_lines, start=actual_start)
        )
        if len(content) > remaining_chars:
            content = content[:remaining_chars]
        remaining_chars -= len(content)
        blocks.append(
            ContextBlock(
                start_line=actual_start,
                end_line=actual_end,
                content=content,
            )
        )

    return blocks


def build_file_context(
    diff: Diff,
    ref: str,
    file_content: str,
    context_lines: int | None = None,
    max_chars_per_file: int | None = None,
) -> FileContext:
    ranges = _line_ranges_for_diff(
        diff,
        context_lines
        if context_lines is not None
        else _env_int("REVIEW_CONTEXT_LINES", DEFAULT_CONTEXT_LINES),
    )
    blocks = _slice_file_content(
        file_content,
        ranges,
        max_chars_per_file
        if max_chars_per_file is not None
        else _env_int("REVIEW_CONTEXT_MAX_CHARS_PER_FILE", DEFAULT_MAX_CHARS_PER_FILE),
    )
    return FileContext(path=diff.path, ref=ref, blocks=blocks)


def build_review_context(
    diffs: list[Diff],
    ref: str,
    read_file: Callable[[str, str], str | None],
    max_files: int | None = None,
    max_total_chars: int | None = None,
) -> ReviewContext:
    if not review_context_enabled() or not ref:
        return ReviewContext()

    limit_files = max_files if max_files is not None else _env_int(
        "REVIEW_CONTEXT_MAX_FILES", DEFAULT_MAX_FILES
    )
    if limit_files <= 0:
        return ReviewContext()

    total_limit = max_total_chars if max_total_chars is not None else _env_int(
        "REVIEW_CONTEXT_MAX_TOTAL_CHARS", DEFAULT_MAX_TOTAL_CHARS
    )
    if total_limit <= 0:
        return ReviewContext()

    source_limit = _env_int("REVIEW_CONTEXT_MAX_SOURCE_CHARS", DEFAULT_MAX_SOURCE_CHARS)
    if source_limit <= 0:
        source_limit = DEFAULT_MAX_SOURCE_CHARS

    total_chars = 0
    file_contexts: list[FileContext] = []

    for diff in diffs[:limit_files]:
        if total_chars >= total_limit:
            break
        if not diff.path:
            continue
        try:
            content = read_file(diff.path, ref)
        except Exception as exc:
            logger.warning("Failed to read context for %s at %s: %s", diff.path, ref, exc)
            file_contexts.append(FileContext(path=diff.path, ref=ref, error=str(exc)))
            continue

        if not content:
            file_contexts.append(
                FileContext(path=diff.path, ref=ref, error="file content is empty")
            )
            continue
        if len(content) > source_limit:
            logger.info(
                "Truncate source content for review context: path=%s, size=%s, limit=%s",
                diff.path,
                len(content),
                source_limit,
            )
            content = content[:source_limit]

        file_context = build_file_context(diff, ref, content)
        context_chars = sum(len(block.content) for block in file_context.blocks)
        if total_chars + context_chars > total_limit:
            remaining = max(total_limit - total_chars, 0)
            file_context = build_file_context(
                diff,
                ref,
                content,
                max_chars_per_file=remaining,
            )
            file_contexts.append(file_context)
            break

        total_chars += context_chars
        file_contexts.append(file_context)

    return ReviewContext(files=file_contexts)
