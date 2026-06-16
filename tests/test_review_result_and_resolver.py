import unittest

from biz.diff.resolver import resolve_line_numbers
from biz.model.diff import Diff
from biz.model.review_comment import ReviewComment, ReviewResult
from biz.utils.code_reviewer import CodeReviewer
from biz.utils.review_renderer import render_review_markdown
from biz.utils.review_result_parser import parse_review_result


TEST_DIFF = """@@ -10,4 +10,4 @@ def handle():
     ctx = request.context
-    log.info("old")
+    log.info("new")
     return ctx
"""


class ReviewResultAndResolverTest(unittest.TestCase):
    def test_parse_review_result_accepts_json_code_fence(self):
        result = parse_review_result(
            """```json
{
  "summary": "Found logging change risk",
  "score": 88,
  "risk_level": "medium",
  "merge_advice": "fix and merge",
  "comments": [
    {
      "path": "app.py",
      "severity": "medium",
      "category": "maintainability",
      "content": "Log content change needs verification.",
      "existing_code": "log.info(\\"new\\")"
    }
  ]
}
```"""
        )

        self.assertEqual(result.score, 88)
        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(len(result.comments), 1)
        self.assertFalse(result.parse_error)

    def test_parse_review_result_falls_back_on_invalid_json(self):
        # YAML parses "key: value" lines, so use a plain-sentence string
        # that cannot be interpreted as any structured format.
        text = "the model failed to produce structured output and fell back to prose"
        result = parse_review_result(text)

        self.assertEqual(result.summary, text)
        self.assertTrue(result.parse_error)

    def test_parse_review_result_extracts_json_from_wrapped_text(self):
        result = parse_review_result(
            """
Below is the review result:
{
  "summary": "One issue found",
  "score": 80,
  "risk_level": "medium",
  "merge_advice": "fix and merge",
  "comments": []
}
"""
        )

        self.assertFalse(result.parse_error)
        self.assertEqual(result.summary, "One issue found")
        self.assertEqual(result.score, 80)

    def test_parse_review_result_handles_nested_json_and_trailing_text(self):
        result = parse_review_result(
            """
prefix
{
  "summary": "Nested content",
  "score": 80,
  "risk_level": "medium",
  "merge_advice": "fix and merge",
  "metadata": {"note": "contains } char"},
  "comments": []
}
trailing text { "ignored": true }
"""
        )

        self.assertFalse(result.parse_error)
        self.assertEqual(result.summary, "Nested content")

    def test_parse_review_result_ignores_model_provided_input_warnings(self):
        result = parse_review_result(
            """
{
  "summary": "One issue found",
  "score": 80,
  "risk_level": "medium",
  "merge_advice": "fix and merge",
  "input_warnings": ["model supplied warning"],
  "comments": []
}
"""
        )

        self.assertEqual(result.input_warnings, [])

    def test_resolve_added_line_from_new_side(self):
        comments = [
            ReviewComment(
                path="app.py",
                content="test",
                existing_code='    log.info("new")',
            )
        ]
        diffs = [Diff(old_path="app.py", new_path="app.py", diff=TEST_DIFF)]

        result = resolve_line_numbers(comments, diffs)

        self.assertTrue(result[0].line_resolved)
        self.assertEqual(result[0].start_line, 11)
        self.assertEqual(result[0].resolve_reason, "matched new side")

    def test_resolve_deleted_line_from_old_side(self):
        comments = [
            ReviewComment(
                path="app.py",
                content="test",
                existing_code='-    log.info("old")',
            )
        ]
        diffs = [Diff(old_path="app.py", new_path="app.py", diff=TEST_DIFF)]

        result = resolve_line_numbers(comments, diffs)

        self.assertTrue(result[0].line_resolved)
        self.assertEqual(result[0].start_line, 11)
        self.assertEqual(result[0].resolve_reason, "matched old side")

    def test_resolve_missing_comment_path_is_explicit_failure(self):
        comments = [
            ReviewComment(
                path="",
                content="test",
                existing_code='    log.info("new")',
            )
        ]
        diffs = [Diff(old_path="app.py", new_path="app.py", diff=TEST_DIFF)]

        result = resolve_line_numbers(comments, diffs)

        self.assertFalse(result[0].line_resolved)
        self.assertEqual(result[0].resolve_reason, "missing comment path")

    def test_renderer_outputs_score_and_location(self):
        result = ReviewResult(
            summary="Overall risk is low.",
            score=92,
            risk_level="low",
            merge_advice="approved",
            comments=[
                ReviewComment(
                    path="app.py",
                    content="Suggest adding tests.",
                    existing_code="return ctx",
                    severity="low",
                    category="test",
                    start_line=12,
                    end_line=12,
                    line_resolved=True,
                )
            ],
        )

        markdown = render_review_markdown(result)

        self.assertIn("Total Score: 92", markdown)
        self.assertIn("`app.py:12`", markdown)

    def test_renderer_does_not_publish_raw_json_when_parse_fails(self):
        result = ReviewResult(
            summary='{"summary": "bad"',
            raw_text='{"summary": "bad"',
            parse_error="invalid json",
        )

        markdown = render_review_markdown(result)

        self.assertIn("## Review Conclusion", markdown)
        self.assertIn("Unable to parse structured issue list", markdown)
        self.assertNotEqual(markdown, result.raw_text)

    def test_renderer_does_not_publish_malformed_json_with_trailing_text(self):
        raw_text = '{"summary": "bad"\ntrailing text'
        result = parse_review_result(raw_text)

        markdown = render_review_markdown(result)

        self.assertTrue(result.parse_error)
        self.assertIn("## Review Conclusion", markdown)
        self.assertIn("Unable to parse structured issue list", markdown)
        self.assertNotEqual(markdown, raw_text)

    def test_high_comment_without_diff_evidence_is_downgraded(self):
        result = ReviewResult(
            summary="Found high risk.",
            risk_level="high",
            merge_advice="do not merge",
            comments=[
                ReviewComment(
                    path="app.py",
                    content="This may be a performance issue and needs context confirmation.",
                    existing_code="not in diff",
                    severity="high",
                    category="performance",
                    resolve_reason="existing_code not found in diff",
                )
            ],
        )

        CodeReviewer.apply_quality_gate(result)

        self.assertEqual(result.comments[0].severity, "medium")
        self.assertEqual(result.risk_level, "medium")

    def test_renderer_outputs_input_warnings(self):
        result = ReviewResult(
            summary="No specific issues found.",
            risk_level="low",
            input_warnings=["Diff truncated due to token budget limit."],
        )

        markdown = render_review_markdown(result)

        self.assertIn("## Input Completeness", markdown)
        self.assertIn("Diff truncated due to token budget limit.", markdown)


if __name__ == "__main__":
    unittest.main()
