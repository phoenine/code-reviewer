import os
import unittest
from unittest.mock import patch

from biz.context.window import build_file_context, build_review_context
from biz.model.diff import Diff
from biz.model.review_context import ContextBlock, FileContext, ReviewContext
from biz.utils.code_reviewer import CodeReviewer


def _file_content(total_lines: int = 30) -> str:
    return "\n".join(f"line {idx}" for idx in range(1, total_lines + 1))


class ReviewContextTest(unittest.TestCase):
    def test_build_file_context_uses_hunk_new_line_window(self):
        diff = Diff(
            old_path="app.py",
            new_path="app.py",
            diff="@@ -10,1 +10,2 @@\n-old\n+new\n+newer",
        )

        context = build_file_context(
            diff,
            ref="abc123",
            file_content=_file_content(),
            context_lines=2,
            max_chars_per_file=10000,
        )

        self.assertEqual(context.path, "app.py")
        self.assertEqual(len(context.blocks), 1)
        self.assertEqual(context.blocks[0].start_line, 8)
        self.assertEqual(context.blocks[0].end_line, 13)
        self.assertIn("10|line 10", context.blocks[0].content)

    def test_build_review_context_respects_max_files(self):
        diffs = [
            Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-a\n+b"),
            Diff(old_path="b.py", new_path="b.py", diff="@@ -1 +1 @@\n-a\n+b"),
        ]

        context = build_review_context(
            diffs,
            ref="abc123",
            read_file=lambda path, ref: _file_content(),
            max_files=1,
            max_total_chars=10000,
        )

        self.assertEqual(
            [file_context.path for file_context in context.files], ["a.py"]
        )

    def test_build_review_context_disables_non_positive_max_files(self):
        diff = Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-a\n+b")

        context = build_review_context(
            [diff],
            ref="abc123",
            read_file=lambda path, ref: _file_content(),
            max_files=0,
            max_total_chars=10000,
        )

        self.assertEqual(context.files, [])

    def test_build_review_context_truncates_large_source_before_slicing(self):
        diff = Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-a\n+b")

        with patch.dict(os.environ, {"REVIEW_CONTEXT_MAX_SOURCE_CHARS": "20"}):
            context = build_review_context(
                [diff],
                ref="abc123",
                read_file=lambda path, ref: "line 1\n" + ("x" * 1000),
                max_files=1,
                max_total_chars=10000,
            )

        self.assertEqual(context.files[0].path, "a.py")
        self.assertLessEqual(
            sum(len(block.content) for block in context.files[0].blocks), 10000
        )

    def test_build_review_context_can_be_disabled(self):
        diff = Diff(old_path="a.py", new_path="a.py", diff="@@ -1 +1 @@\n-a\n+b")

        with patch.dict(os.environ, {"REVIEW_CONTEXT_ENABLED": "0"}):
            context = build_review_context(
                [diff],
                ref="abc123",
                read_file=lambda path, ref: _file_content(),
            )

        self.assertEqual(context.files, [])

    def test_render_context_for_prompt(self):
        context = ReviewContext(
            files=[
                FileContext(
                    path="app.py",
                    ref="abc123",
                    blocks=[
                        ContextBlock(start_line=1, end_line=2, content="1|a\n2|b")
                    ],
                )
            ]
        )

        rendered = CodeReviewer.render_context_for_prompt(context)

        self.assertIn("Supplementary Context", rendered)
        self.assertIn("File: app.py", rendered)
        self.assertIn("Lines 1-2", rendered)
        self.assertIn("1|a", rendered)

    def test_budget_render_keeps_diff_and_truncates_context(self):
        diff = Diff(
            old_path="app.py",
            new_path="app.py",
            diff="@@ -1 +1 @@\n-old\n+new",
        )
        context = ReviewContext(
            files=[
                FileContext(
                    path="app.py",
                    ref="abc123",
                    blocks=[
                        ContextBlock(
                            start_line=1,
                            end_line=1,
                            content="1|" + "context " * 500,
                        )
                    ],
                )
            ]
        )

        with patch.dict(
            os.environ,
            {
                "REVIEW_PROMPT_RESERVED_TOKENS": "0",
                "REVIEW_DIFF_TOKEN_RATIO": "0.50",
                "REVIEW_CONTEXT_TOKEN_RATIO": "0.10",
            },
        ):
            rendered = CodeReviewer.render_review_input_with_budget(
                [diff], context, max_tokens=220
            )

        self.assertIn("Diff:", rendered)
        self.assertIn("+new", rendered)
        self.assertIn("Supplementary Context", rendered)
        self.assertIn("token budget limit", rendered)
        self.assertNotIn("context " * 100, rendered)

    def test_budget_render_omits_context_when_diff_exceeds_budget(self):
        diff = Diff(
            old_path="app.py",
            new_path="app.py",
            diff="@@ -1 +1 @@\n"
            + "\n".join(
                f"-old {idx}\n+new {idx}" for idx in range(200)
            ),
        )
        context = ReviewContext(
            files=[
                FileContext(
                    path="app.py",
                    ref="abc123",
                    blocks=[
                        ContextBlock(
                            start_line=1, end_line=1, content="1|context"
                        )
                    ],
                )
            ]
        )

        with patch.dict(
            os.environ,
            {
                "REVIEW_PROMPT_RESERVED_TOKENS": "0",
                "REVIEW_DIFF_TOKEN_RATIO": "0.20",
                "REVIEW_CONTEXT_TOKEN_RATIO": "0.30",
            },
        ):
            rendered = CodeReviewer.render_review_input_with_budget(
                [diff], context, max_tokens=300
            )

        self.assertIn("Diff:", rendered)
        self.assertIn("Diff truncated due to token budget limit", rendered)
        self.assertIn(
            "Supplementary context omitted due to token budget limit", rendered
        )

    def test_collect_review_input_warnings_reports_missing_context_coverage(self):
        diff = Diff(
            old_path="app.py",
            new_path="app.py",
            diff="@@ -1 +1 @@\n-old\n+new",
        )

        warnings = CodeReviewer.collect_review_input_warnings("", [diff], None)

        self.assertIn(
            "Supplementary context was extracted for 0/1 changed files.",
            warnings,
        )


if __name__ == "__main__":
    unittest.main()
