from dataclasses import dataclass, field


@dataclass(slots=True)
class Diff:
    old_path: str
    new_path: str
    diff: str
    additions: int = 0
    deletions: int = 0
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path
