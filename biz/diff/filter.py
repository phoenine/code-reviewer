import os
from dataclasses import dataclass, field

from biz.model.diff import Diff
from biz.utils.log import logger


DEFAULT_SUPPORTED_EXTENSIONS = (
    ".java,.py,.ts,.tsx,.js,.html,.scss,.sql,.yaml,.yml,.sh,.go,.json"
)


@dataclass(slots=True)
class DiffFilterResult:
    diffs: list[Diff]
    total_files: int
    skipped_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def reviewed_files(self) -> int:
        return len(self.diffs)

    @property
    def skipped_files(self) -> int:
        return sum(self.skipped_by_reason.values())

    def to_warnings(self) -> list[str]:
        warnings = [
            f"Diff filter kept {self.reviewed_files}/{self.total_files} files for review."
        ]
        if self.skipped_by_reason:
            details = ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(self.skipped_by_reason.items())
            )
            warnings.append(f"Skipped files by reason: {details}.")
        return warnings


def supported_extensions_from_env() -> list[str]:
    raw_extensions = os.getenv("SUPPORTED_EXTENSIONS", DEFAULT_SUPPORTED_EXTENSIONS)
    return [ext.strip() for ext in raw_extensions.split(",") if ext.strip()]


def is_supported_path(path: str, supported_extensions: list[str]) -> bool:
    return any(path.endswith(ext) for ext in supported_extensions)


def filter_diffs(
    diffs: list[Diff],
    supported_extensions: list[str] | None = None,
) -> list[Diff]:
    return filter_diffs_with_stats(diffs, supported_extensions).diffs


def filter_diffs_with_stats(
    diffs: list[Diff],
    supported_extensions: list[str] | None = None,
) -> DiffFilterResult:
    extensions = supported_extensions or supported_extensions_from_env()
    filtered: list[Diff] = []
    skipped_by_reason: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1

    for diff in diffs:
        path = diff.path
        if diff.is_deleted:
            logger.info("Skip deleted file: %s", path)
            skip("deleted")
            continue
        if diff.is_binary:
            logger.info("Skip binary file: %s", path)
            skip("binary")
            continue
        if not diff.diff:
            logger.info("Skip file without diff content: %s", path)
            skip("empty_diff")
            continue
        if not is_supported_path(path, extensions):
            logger.info("Skip unsupported file type: %s", path)
            skip("unsupported_extension")
            continue
        filtered.append(diff)

    return DiffFilterResult(
        diffs=filtered,
        total_files=len(diffs),
        skipped_by_reason=skipped_by_reason,
    )
