from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextBlock:
    start_line: int
    end_line: int
    content: str


@dataclass(slots=True)
class FileContext:
    path: str
    ref: str
    blocks: list[ContextBlock] = field(default_factory=list)
    error: str = ""


@dataclass(slots=True)
class ReviewContext:
    files: list[FileContext] = field(default_factory=list)

    def by_path(self) -> dict[str, FileContext]:
        return {file_context.path: file_context for file_context in self.files}
