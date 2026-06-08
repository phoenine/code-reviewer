import os

from biz.model.diff import Diff
from biz.utils.log import logger


DEFAULT_SUPPORTED_EXTENSIONS = (
    ".java,.py,.ts,.tsx,.js,.html,.scss,.sql,.yaml,.yml,.sh,.go,.json"
)


def supported_extensions_from_env() -> list[str]:
    raw_extensions = os.getenv("SUPPORTED_EXTENSIONS", DEFAULT_SUPPORTED_EXTENSIONS)
    return [ext.strip() for ext in raw_extensions.split(",") if ext.strip()]


def is_supported_path(path: str, supported_extensions: list[str]) -> bool:
    return any(path.endswith(ext) for ext in supported_extensions)


def filter_diffs(
    diffs: list[Diff],
    supported_extensions: list[str] | None = None,
) -> list[Diff]:
    extensions = supported_extensions or supported_extensions_from_env()
    filtered: list[Diff] = []

    for diff in diffs:
        path = diff.path
        if diff.is_deleted:
            logger.info("Skip deleted file: %s", path)
            continue
        if diff.is_binary:
            logger.info("Skip binary file: %s", path)
            continue
        if not diff.diff:
            logger.info("Skip file without diff content: %s", path)
            continue
        if not is_supported_path(path, extensions):
            logger.info("Skip unsupported file type: %s", path)
            continue
        filtered.append(diff)

    return filtered
