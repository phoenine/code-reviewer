import unittest
import base64
from unittest.mock import Mock, patch

from biz.platforms.github.webhook_handler import (
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


if __name__ == "__main__":
    unittest.main()
