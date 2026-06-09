import abc
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse

import yaml
from jinja2 import StrictUndefined, Template, UndefinedError

from biz.llm.factory import Factory
from biz.diff.resolver import resolve_line_numbers
from biz.model.diff import Diff
from biz.model.review_comment import ReviewResult
from biz.model.review_context import ReviewContext
from biz.utils.log import logger
from biz.utils.review_result_parser import parse_review_result
from biz.utils.token_util import count_tokens, truncate_text_by_tokens


ALLOWED_REVIEW_STYLES = {
    "professional",
    "concise",
    "strict",
    "sarcastic",
    "gentle",
    "humorous",
}


class BaseReviewer(abc.ABC):
    """Base class for code review"""

    def __init__(self, prompt_key: str):
        self.client = Factory().getClient()
        self.prompt_key = prompt_key
        self.prompts = self._load_prompts(
            prompt_key, self._normalize_review_style(os.getenv("REVIEW_STYLE"))
        )

    @staticmethod
    def _prompt_templates_file() -> Path:
        return Path(__file__).resolve().parents[2] / "conf" / "prompt_templates.yml"

    @classmethod
    @lru_cache(maxsize=1)
    def _load_prompt_config(cls) -> Dict[str, Any]:
        prompt_templates_file = cls._prompt_templates_file()
        with open(prompt_templates_file, "r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    @staticmethod
    def _normalize_review_style(style: str | None) -> str:
        if style in ALLOWED_REVIEW_STYLES:
            return style
        return "professional"

    @staticmethod
    def _render_template(template_str: str, style: str) -> str:
        return Template(template_str, undefined=StrictUndefined).render(style=style)

    def _load_prompts(self, prompt_key: str, style="professional") -> Dict[str, Any]:
        """Load prompt configuration"""
        try:
            config = self._load_prompt_config()
            prompts = config[prompt_key]
            base_prompts = config.get("base_prompt")

            system_parts = []
            if base_prompts and prompt_key != "base_prompt":
                system_parts.append(
                    self._render_template(base_prompts["system_prompt"], style)
                )
            system_parts.append(self._render_template(prompts["system_prompt"], style))
            system_prompt = "\n\n".join(part for part in system_parts if part)
            user_prompt = self._render_template(prompts["user_prompt"], style)

            logger.info(f"Loaded code review prompt: {prompt_key}")
            return {
                "system_message": {"role": "system", "content": system_prompt},
                "user_message": {"role": "user", "content": user_prompt},
            }
        except (FileNotFoundError, KeyError, yaml.YAMLError, UndefinedError) as e:
            logger.error(f"Failed to load prompt configuration: {e}")
            raise Exception(f"Prompt configuration loading failed: {e}")

    def call_llm(self, messages: List[Dict[str, Any]]) -> str:
        """Call LLM to perform code review"""
        logger.info(f"Sending code review request to AI, messages: {messages}")
        review_result = self.client.completions(messages=messages)
        logger.info(f"Received AI response: {review_result}")
        return review_result

    @abc.abstractmethod
    def review_code(self, *args, **kwargs) -> str:
        """Abstract method, subclasses must implement"""
        pass


class CodeReviewer(BaseReviewer):
    """Code Diff level review"""

    def __init__(self, project_context: dict | None = None):
        super().__init__(self.resolve_prompt_key(project_context))

    @classmethod
    def resolve_prompt_key(cls, project_context: dict | None = None) -> str:
        """Select code review prompt based on GitLab/GitHub project information"""
        config = cls._load_prompt_config()
        routing = config.get("prompt_routing", {})
        default_prompt = routing.get("default", "code_review_prompt_generic")
        if not isinstance(project_context, dict) or not project_context:
            return default_prompt

        candidates = cls._project_candidates(project_context)
        projects = {
            cls._normalize_route_path(str(k)): v
            for k, v in routing.get("projects", {}).items()
        }
        for candidate in candidates:
            if candidate in projects:
                return projects[candidate]

        groups = {
            cls._normalize_route_path(str(k)): v
            for k, v in routing.get("groups", {}).items()
        }
        path_candidates = [c for c in candidates if "/" in c]
        for path in path_candidates:
            for group, prompt_key in groups.items():
                if path == group or path.startswith(group + "/"):
                    return prompt_key
        return default_prompt

    @staticmethod
    def _normalize_route_path(value: str) -> str:
        normalized = value.strip().strip("/").lower()
        parsed = urlparse(normalized)
        if parsed.scheme and parsed.netloc and parsed.path:
            normalized = parsed.path.strip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        return normalized

    @staticmethod
    def _project_candidates(project_context: dict) -> list[str]:
        def add_candidate(candidate: str, result: list[str]) -> None:
            normalized = CodeReviewer._normalize_route_path(candidate)
            if not normalized:
                return
            result.append(normalized)
            if normalized.endswith(".git"):
                result.append(normalized[:-4])
            tail = normalized.split("/")[-1]
            if tail.endswith(".git"):
                tail = tail[:-4]
            if tail:
                result.append(tail)

        values = []
        for key in (
            "name",
            "path",
            "path_with_namespace",
            "full_name",
            "full_path",
            "html_url",
            "web_url",
        ):
            value = project_context.get(key)
            if value:
                values.append(str(value))

        candidates: list[str] = []
        for value in values:
            add_candidate(value, candidates)
            parsed = urlparse(value)
            if parsed.scheme and parsed.netloc and parsed.path:
                add_candidate(parsed.path, candidates)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)))
        except ValueError:
            return default

    @staticmethod
    def render_diffs_for_prompt(diffs: list[Diff]) -> str:
        sections = []
        for diff in diffs:
            sections.append(
                "\n".join(
                    [
                        f"File: {diff.path}",
                        f"Old Path: {diff.old_path}",
                        f"New Path: {diff.new_path}",
                        f"Additions: {diff.additions} lines, Deletions: {diff.deletions} lines",
                        "Diff:",
                        "```diff",
                        diff.diff,
                        "```",
                    ]
                )
            )
        return "\n\n".join(sections)

    @staticmethod
    def _render_file_context_for_prompt(file_context) -> str:
        sections = [f"File: {file_context.path}"]
        if file_context.error:
            sections.append(f"Context read failure: {file_context.error}")
            return "\n".join(sections)
        if not file_context.blocks:
            sections.append("No context blocks extracted.")
            return "\n".join(sections)

        for block in file_context.blocks:
            sections.extend(
                [
                    f"Lines {block.start_line}-{block.end_line}:",
                    "```text",
                    block.content,
                    "```",
                ]
            )
        return "\n".join(sections)

    @classmethod
    def render_context_for_prompt(cls, review_context: ReviewContext | None) -> str:
        if not review_context or not review_context.files:
            return ""

        sections = [
            "Supplementary Context (for understanding surrounding logic; "
            "comments should still be based primarily on the diff):"
        ]
        for file_context in review_context.files:
            sections.append(cls._render_file_context_for_prompt(file_context))
        return "\n".join(sections)

    @classmethod
    def render_review_input_with_budget(
        cls,
        diffs: list[Diff],
        review_context: ReviewContext | None,
        max_tokens: int,
    ) -> str:
        available_tokens = max(
            max_tokens - cls._env_int("REVIEW_PROMPT_RESERVED_TOKENS", 1000),
            1,
        )
        context_ratio = max(
            0.0, min(cls._env_float("REVIEW_CONTEXT_TOKEN_RATIO", 0.30), 1.0)
        )
        diff_ratio = max(
            0.0, min(cls._env_float("REVIEW_DIFF_TOKEN_RATIO", 0.65), 1.0)
        )
        diff_budget = max(int(available_tokens * diff_ratio), 1)
        base_context_budget = max(int(available_tokens * context_ratio), 0)

        diff_text = cls.render_diffs_for_prompt(diffs)
        diff_tokens = count_tokens(diff_text)
        if diff_tokens > diff_budget:
            diff_text = (
                truncate_text_by_tokens(diff_text, diff_budget)
                + "\n\n[Diff truncated due to token budget limit]"
            )
            # When the diff already exceeds budget, no tokens go to context.
            context_budget = 0
        else:
            # Diff-first; unused diff budget can roll over to context.
            unused_diff_budget = max(diff_budget - diff_tokens, 0)
            context_budget = base_context_budget + unused_diff_budget

        context_text = ""
        if review_context and review_context.files:
            if context_budget <= 0:
                context_text = (
                    "Supplementary context omitted due to token budget limit."
                )
            else:
                context_sections = [
                    "Supplementary Context (for understanding surrounding logic; "
                    "comments should still be based primarily on the diff):"
                ]
                remaining_context_budget = context_budget
                for file_context in review_context.files:
                    file_context_text = cls._render_file_context_for_prompt(
                        file_context
                    )
                    file_context_tokens = count_tokens(file_context_text)
                    if file_context_tokens <= remaining_context_budget:
                        context_sections.append(file_context_text)
                        remaining_context_budget -= file_context_tokens
                        continue
                    if remaining_context_budget > 0:
                        context_sections.append(
                            truncate_text_by_tokens(
                                file_context_text, remaining_context_budget
                            )
                        )
                        context_sections.append(
                            "Supplementary context truncated due to token budget limit."
                        )
                    else:
                        context_sections.append(
                            f"File: {file_context.path}\n"
                            "Supplementary context omitted due to token budget limit."
                        )
                    break
                context_text = "\n".join(context_sections)

        review_input = "\n\n".join(
            part for part in [diff_text, context_text] if part
        )
        if count_tokens(review_input) > max_tokens:
            truncated = truncate_text_by_tokens(review_input, max_tokens)
            if truncated.strip():
                return truncated
            return truncate_text_by_tokens(
                cls.render_diffs_for_prompt(diffs), max_tokens
            )
        return review_input

    def review_and_strip_code(self, changes_text: str, commits_text: str = "") -> str:
        """
        Review and determine if changes_text exceeds REVIEW_MAX_TOKENS tokens,
        truncate changes_text if it does. Call review_code method and return the
        review result. If the result is in markdown format, strip the leading and
        trailing ``` markers.
        """
        review_max_tokens = int(os.getenv("REVIEW_MAX_TOKENS", 10000))
        if not changes_text:
            logger.info("Code is empty, diffs_text = %s", str(changes_text))
            return "Code is empty"

        tokens_count = count_tokens(changes_text)
        if tokens_count > review_max_tokens:
            changes_text = truncate_text_by_tokens(changes_text, review_max_tokens)

        review_result = self.review_code(changes_text, commits_text).strip()
        if review_result.startswith("```markdown") and review_result.endswith("```"):
            return review_result[11:-3].strip()
        return review_result

    def review_diffs(
        self,
        diffs: list[Diff],
        commits_text: str = "",
        review_context: ReviewContext | None = None,
    ) -> ReviewResult:
        review_max_tokens = int(os.getenv("REVIEW_MAX_TOKENS", 10000))
        changes_text = self.render_review_input_with_budget(
            diffs,
            review_context,
            review_max_tokens,
        )
        if not changes_text:
            return ReviewResult(summary="Code is empty", raw_text="")

        tokens_count = count_tokens(changes_text)
        if tokens_count > review_max_tokens:
            changes_text = truncate_text_by_tokens(changes_text, review_max_tokens)

        raw_result = self.review_code(changes_text, commits_text).strip()
        result = parse_review_result(raw_result)
        if result.parse_error:
            result.score = self.parse_review_score(raw_result)
            return result

        result.comments = resolve_line_numbers(result.comments, diffs)
        return result

    def review_code(self, diffs_text: str, commits_text: str = "") -> str:
        """Review code and return the result"""
        messages = [
            self.prompts["system_message"],
            {
                "role": "user",
                "content": self.prompts["user_message"]["content"].format(
                    diffs_text=diffs_text, commits_text=commits_text
                ),
            },
        ]
        return self.call_llm(messages)

    @staticmethod
    def parse_review_score(review_text: str) -> int | None:
        """Parse the AI review result and return the score. Returns None if no score found."""
        if not review_text:
            return None
        match = re.search(r"总分[:：]\s*(\d+)分?", review_text)
        return int(match.group(1)) if match else None
