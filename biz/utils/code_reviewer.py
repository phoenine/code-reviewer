import abc
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List

import yaml
from jinja2 import Template

from biz.llm.factory import Factory
from biz.utils.log import logger
from biz.utils.token_util import count_tokens, truncate_text_by_tokens


class BaseReviewer(abc.ABC):
    """Base class for code review"""

    def __init__(self, prompt_key: str):
        self.client = Factory().getClient()
        self.prompt_key = prompt_key
        self.prompts = self._load_prompts(
            prompt_key, os.getenv("REVIEW_STYLE", "professional")
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
    def _render_template(template_str: str, style: str) -> str:
        return Template(template_str).render(style=style)

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
        except (FileNotFoundError, KeyError, yaml.YAMLError) as e:
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
        if not project_context:
            return default_prompt

        candidates = cls._project_candidates(project_context)
        projects = {str(k).lower(): v for k, v in routing.get("projects", {}).items()}
        for candidate in candidates:
            if candidate in projects:
                return projects[candidate]

        groups = {str(k).lower(): v for k, v in routing.get("groups", {}).items()}
        path_candidates = [c for c in candidates if "/" in c]
        for path in path_candidates:
            for group, prompt_key in groups.items():
                if path == group or path.startswith(group + "/"):
                    return prompt_key
        return default_prompt

    @staticmethod
    def _project_candidates(project_context: dict) -> list[str]:
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
            normalized = value.strip().rstrip("/").lower()
            if not normalized:
                continue
            candidates.append(normalized)
            tail = normalized.split("/")[-1]
            if tail.endswith(".git"):
                tail = tail[:-4]
            if tail:
                candidates.append(tail)
        return list(dict.fromkeys(candidates))

    def review_and_strip_code(self, changes_text: str, commits_text: str = "") -> str:
        """
        Review and determine if changes_text exceeds REVIEW_MAX_TOKENS tokens, truncate changes_text if it does.
        Call review_code method and return the review result. If the result is in markdown format,
        strip the leading and trailing ``` markers.
        :param changes_text:
        :param commits_text:
        :return:
        """
        # Truncate to REVIEW_MAX_TOKENS if too long
        review_max_tokens = int(os.getenv("REVIEW_MAX_TOKENS", 10000))
        # Log if changes is empty
        if not changes_text:
            logger.info("Code is empty, diffs_text = %s", str(changes_text))
            return "Code is empty"

        # Count tokens and truncate if over limit
        tokens_count = count_tokens(changes_text)
        if tokens_count > review_max_tokens:
            changes_text = truncate_text_by_tokens(changes_text, review_max_tokens)

        review_result = self.review_code(changes_text, commits_text).strip()
        if review_result.startswith("```markdown") and review_result.endswith("```"):
            return review_result[11:-3].strip()
        return review_result

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
