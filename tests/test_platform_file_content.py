import unittest
import base64
from unittest.mock import Mock, patch

from biz.platforms.github.webhook_handler import (
    PullRequestHandler,
    PushHandler,
    _get_repository_file_content as get_github_file_content,
)


class PlatformFileContentTest(unittest.TestCase):
    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_raw_content_decodes_bytes_with_replacement(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/x-gzip"}
        response.content = b"hello\xffworld"
        mock_get.return_value = response

        content = get_github_file_content(
            "https://api.github.com", "owner/repo", "token", "src/app.py", "abc123"
        )

        self.assertEqual(content, "hello\ufffdworld")

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_json_content_ignores_blank_base64(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"content": "   "}
        mock_get.return_value = response

        content = get_github_file_content(
            "https://api.github.com", "owner/repo", "token", "src/app.py", "abc123"
        )

        self.assertIsNone(content)

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_raw_json_file_is_returned_as_text(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"key": "value"}
        response.content = b'{"key":"value"}'
        mock_get.return_value = response

        content = get_github_file_content(
            "https://api.github.com", "owner/repo", "token", "config.json", "abc123"
        )

        self.assertEqual(content, '{"key":"value"}')

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_invalid_json_content_type_falls_back_to_text(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.json.side_effect = ValueError("invalid json")
        response.content = b"{invalid"
        mock_get.return_value = response

        content = get_github_file_content(
            "https://api.github.com", "owner/repo", "token", "config.json", "abc123"
        )

        self.assertEqual(content, "{invalid")

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_contents_metadata_base64_is_decoded(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "content": base64.b64encode("hello".encode("utf-8")).decode("ascii")
        }
        mock_get.return_value = response

        content = get_github_file_content(
            "https://api.github.com", "owner/repo", "token", "README.md", "abc123"
        )

        self.assertEqual(content, "hello")

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_pull_request_changes_fetches_all_pages(self, mock_get):
        first = Mock()
        first.status_code = 200
        first.json.return_value = [
            {
                "filename": f"a{idx}.py",
                "patch": "@@ -1 +1 @@\n-a\n+b",
                "additions": 1,
                "deletions": 1,
            }
            for idx in range(100)
        ]
        second = Mock()
        second.status_code = 200
        second.json.return_value = [
            {
                "filename": "b.py",
                "patch": "@@ -1 +1 @@\n-c\n+d",
                "additions": 1,
                "deletions": 1,
            }
        ]
        mock_get.side_effect = [first, second]
        handler = PullRequestHandler(
            {
                "action": "synchronize",
                "pull_request": {"number": 12},
                "repository": {"full_name": "owner/repo"},
            },
            "token",
            "https://github.com",
        )

        changes = handler.get_pull_request_changes()

        self.assertEqual(len(changes), 101)
        self.assertEqual(changes[0]["filename"], "a0.py")
        self.assertEqual(changes[-1]["filename"], "b.py")
        self.assertEqual(
            mock_get.call_args_list[0].kwargs["params"],
            {"per_page": 100, "page": 1},
        )
        self.assertEqual(
            mock_get.call_args_list[1].kwargs["params"],
            {"per_page": 100, "page": 2},
        )

    @patch("biz.platforms.github.webhook_handler.requests.get")
    def test_github_compare_marks_large_file_list_as_incomplete(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "files": [
                {
                    "filename": f"file{idx}.py",
                    "patch": "@@ -1 +1 @@\n-a\n+b",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                }
                for idx in range(300)
            ]
        }
        mock_get.return_value = response
        handler = PushHandler(
            {
                "ref": "refs/heads/dev",
                "repository": {"full_name": "owner/repo"},
                "commits": [],
            },
            "token",
            "https://github.com",
        )

        changes = handler.repository_compare("base", "head")

        self.assertEqual(len(changes), 300)
        self.assertIn("warnings", changes[0])
        self.assertIn(
            "GitHub compare API returned 300 files; the file list may be capped.",
            changes[0]["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
