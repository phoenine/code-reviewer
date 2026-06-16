import unittest

from biz.diff.filter import (
    filter_diffs,
    filter_diffs_with_stats,
    supported_extensions_from_env,
)
from biz.diff.parser import parse_changes, parse_github_file, parse_gitlab_change


class DiffParserFilterTest(unittest.TestCase):
    def test_parse_gitlab_change_counts_lines_when_missing_stats(self):
        diff = parse_gitlab_change(
            {
                "old_path": "app.py",
                "new_path": "app.py",
                "diff": "@@ -1,2 +1,2 @@\n-old\n+new\n context",
            }
        )

        self.assertEqual(diff.old_path, "app.py")
        self.assertEqual(diff.new_path, "app.py")
        self.assertEqual(diff.additions, 1)
        self.assertEqual(diff.deletions, 1)
        self.assertEqual(diff.source, "gitlab")

    def test_parse_gitlab_change_marks_incomplete_platform_diff(self):
        diff = parse_gitlab_change(
            {
                "old_path": "large.py",
                "new_path": "large.py",
                "diff": "@@ -1 +1 @@\n-old\n+new",
                "too_large": True,
                "collapsed": True,
            }
        )

        self.assertIn(
            "GitLab marked this file diff as too large; it may be incomplete.",
            diff.warnings,
        )
        self.assertIn(
            "GitLab marked this file diff as collapsed; it may be incomplete.",
            diff.warnings,
        )

    def test_parse_github_file_maps_patch_and_rename(self):
        diff = parse_github_file(
            {
                "filename": "new.py",
                "previous_filename": "old.py",
                "patch": "@@ -1 +1 @@\n-old\n+new",
                "status": "renamed",
                "additions": 1,
                "deletions": 1,
            }
        )

        self.assertEqual(diff.old_path, "old.py")
        self.assertEqual(diff.new_path, "new.py")
        self.assertEqual(diff.diff, "@@ -1 +1 @@\n-old\n+new")
        self.assertFalse(diff.is_deleted)

    def test_parse_github_file_marks_missing_patch_for_modified_file(self):
        diff = parse_github_file(
            {
                "filename": "large.py",
                "patch": "",
                "status": "modified",
                "sha": "abc123",
                "additions": 2000,
                "deletions": 10,
            }
        )

        self.assertIn(
            "GitHub did not return a patch for this modified file; the diff may be too large.",
            diff.warnings,
        )

    def test_parse_changes_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            parse_changes([], source="unknown")

    def test_default_supported_extensions_include_go_and_json(self):
        extensions = supported_extensions_from_env()

        self.assertIn(".go", extensions)
        self.assertIn(".json", extensions)

    def test_github_removed_file_is_filtered_by_status(self):
        diffs = parse_changes(
            [
                {
                    "filename": "removed.go",
                    "patch": "@@ -1 +0,0 @@\n-package main",
                    "status": "removed",
                    "additions": 0,
                    "deletions": 1,
                },
                {
                    "filename": "kept.json",
                    "patch": '@@ -1 +1 @@\n-{"a":1}\n+{"a":2}',
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                },
            ],
            source="github",
        )

        result = filter_diffs(diffs)

        self.assertEqual([diff.path for diff in result], ["kept.json"])

    def test_filter_diffs_skips_deleted_binary_empty_and_unsupported(self):
        diffs = parse_changes(
            [
                {"new_path": "ok.py", "diff": "@@ -1 +1 @@\n-a\n+b"},
                {
                    "new_path": "deleted.py",
                    "diff": "@@ -1 +0,0 @@\n-a",
                    "deleted_file": True,
                },
                {"new_path": "empty.py", "diff": ""},
                {"new_path": "note.txt", "diff": "@@ -1 +1 @@\n-a\n+b"},
            ],
            source="gitlab",
        )

        result = filter_diffs(diffs, supported_extensions=[".py"])

        self.assertEqual([diff.path for diff in result], ["ok.py"])

    def test_filter_diffs_with_stats_reports_reviewed_and_skipped_reasons(self):
        diffs = parse_changes(
            [
                {"new_path": "ok.py", "diff": "@@ -1 +1 @@\n-a\n+b"},
                {
                    "new_path": "deleted.py",
                    "diff": "@@ -1 +0,0 @@\n-a",
                    "deleted_file": True,
                },
                {"new_path": "empty.py", "diff": ""},
                {"new_path": "note.txt", "diff": "@@ -1 +1 @@\n-a\n+b"},
            ],
            source="gitlab",
        )

        result = filter_diffs_with_stats(diffs, supported_extensions=[".py"])

        self.assertEqual([diff.path for diff in result.diffs], ["ok.py"])
        self.assertEqual(result.total_files, 4)
        self.assertEqual(result.reviewed_files, 1)
        self.assertEqual(result.skipped_files, 3)
        self.assertEqual(result.skipped_by_reason["deleted"], 1)
        self.assertEqual(result.skipped_by_reason["empty_diff"], 1)
        self.assertEqual(result.skipped_by_reason["unsupported_extension"], 1)
        self.assertIn("Diff filter kept 1/4 files for review.", result.to_warnings())
        self.assertIn(
            "Skipped files by reason: deleted=1, empty_diff=1, unsupported_extension=1.",
            result.to_warnings(),
        )


if __name__ == "__main__":
    unittest.main()
