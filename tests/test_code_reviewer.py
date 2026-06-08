import unittest
from unittest.mock import patch

from biz.utils.code_reviewer import BaseReviewer, CodeReviewer


class CodeReviewerTest(unittest.TestCase):
    def test_resolve_prompt_key_uses_default_for_non_dict_context(self):
        with patch.object(
            CodeReviewer,
            "_load_prompt_config",
            return_value={
                "prompt_routing": {
                    "default": "code_review_prompt_generic",
                    "projects": {},
                    "groups": {},
                }
            },
        ):
            prompt_key = CodeReviewer.resolve_prompt_key("not-a-dict")

        self.assertEqual(prompt_key, "code_review_prompt_generic")

    def test_project_candidates_include_canonical_namespace_from_url_and_git_suffix(self):
        candidates = CodeReviewer._project_candidates(
            {
                "path_with_namespace": "beet/beet-repo.git",
                "html_url": "https://gitlab.example.com/beet/beet-repo",
            }
        )

        self.assertIn("beet/beet-repo", candidates)
        self.assertIn("beet-repo", candidates)

    def test_resolve_prompt_key_matches_group_from_url_context(self):
        with patch.object(
            CodeReviewer,
            "_load_prompt_config",
            return_value={
                "prompt_routing": {
                    "default": "code_review_prompt_generic",
                    "projects": {},
                    "groups": {"beet/beet-repo": "code_review_prompt_epvs_default"},
                }
            },
        ):
            prompt_key = CodeReviewer.resolve_prompt_key(
                {"html_url": "https://gitlab.example.com/beet/beet-repo.git"}
            )

        self.assertEqual(prompt_key, "code_review_prompt_epvs_default")

    def test_project_routing_does_not_match_tail_only(self):
        with patch.object(
            CodeReviewer,
            "_load_prompt_config",
            return_value={
                "prompt_routing": {
                    "default": "code_review_prompt_generic",
                    "projects": {"team/common-utils": "team_prompt"},
                    "groups": {},
                }
            },
        ):
            prompt_key = CodeReviewer.resolve_prompt_key({"name": "common-utils"})

        self.assertEqual(prompt_key, "code_review_prompt_generic")

    def test_normalize_review_style_falls_back_to_professional(self):
        self.assertEqual(
            BaseReviewer._normalize_review_style("{{ unsafe }}"), "professional"
        )
        self.assertEqual(BaseReviewer._normalize_review_style("strict"), "strict")


if __name__ == "__main__":
    unittest.main()
