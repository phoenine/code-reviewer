import unittest
from unittest.mock import patch

from biz.model.diff import Diff
from biz.utils.code_reviewer import BaseReviewer, CodeReviewer


class RecordingReviewer(CodeReviewer):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def review_code(self, diffs_text: str, commits_text: str = "") -> str:
        self.calls.append(diffs_text)
        return self.responses.pop(0)


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
        self.assertEqual(BaseReviewer._normalize_review_style("sarcastic"), "sarcastic")

    def test_split_diffs_for_review_keeps_each_oversized_file_as_own_batch(self):
        diffs = [
            Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-a\n+b"),
            Diff(old_path="b.py", new_path="b.py", diff="@@ -1 +1 @@\n-c\n+d"),
        ]

        batches = CodeReviewer.split_diffs_for_review(diffs, max_tokens=1)

        self.assertEqual(
            [[diff.path for diff in batch] for batch in batches],
            [["a.py"], ["b.py"]],
        )

    def test_review_diffs_splits_batches_and_merges_unique_comments(self):
        diffs = [
            Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-old\n+new"),
            Diff(old_path="b.py", new_path="b.py", diff="@@ -1 +1 @@\n-old\n+new"),
        ]
        reviewer = RecordingReviewer(
            [
                """{
                  "summary": "batch one",
                  "score": 80,
                  "risk_level": "medium",
                  "merge_advice": "fix and merge",
                  "comments": [
                    {
                      "path": "a.py",
                      "severity": "medium",
                      "category": "correctness",
                      "content": "a issue",
                      "existing_code": "new"
                    }
                  ]
                }""",
                """{
                  "summary": "batch two",
                  "score": 90,
                  "risk_level": "low",
                  "merge_advice": "approved",
                  "comments": [
                    {
                      "path": "a.py",
                      "severity": "medium",
                      "category": "correctness",
                      "content": "a issue",
                      "existing_code": "new"
                    },
                    {
                      "path": "b.py",
                      "severity": "low",
                      "category": "test",
                      "content": "b issue",
                      "existing_code": "new"
                    }
                  ]
                }""",
            ]
        )

        with patch.dict(
            "os.environ",
            {"REVIEW_MAX_TOKENS": "1000", "REVIEW_CHUNK_MAX_TOKENS": "1"},
        ):
            result = reviewer.review_diffs(diffs)

        self.assertEqual(len(reviewer.calls), 2)
        self.assertEqual([comment.path for comment in result.comments], ["a.py", "b.py"])
        self.assertEqual(result.score, 85)
        self.assertEqual(result.risk_level, "medium")
        self.assertIn("Changes were reviewed in 2 batches.", result.input_warnings)
        self.assertIn(
            "Review input contains 2 files, 0 additions, 0 deletions.",
            result.input_warnings,
        )
        self.assertNotIn(
            "Review input contains 1 files, 0 additions, 0 deletions.",
            result.input_warnings,
        )


if __name__ == "__main__":
    unittest.main()
