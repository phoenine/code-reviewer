import os
import unittest
from unittest.mock import Mock, patch

from biz.queue import worker


class WorkerPushTest(unittest.TestCase):
    @patch.dict(os.environ, {"PUSH_REVIEW_ENABLED": "0"})
    @patch("biz.queue.worker.PushHandler")
    def test_gitlab_push_does_not_emit_review_event_when_push_review_disabled(
        self, mock_handler_cls
    ):
        handler = Mock()
        handler.get_push_commits.return_value = [
            {"message": "skip review", "author": "dev", "timestamp": "", "url": "#"}
        ]
        mock_handler_cls.return_value = handler
        webhook_data = {
            "project": {"name": "alpha"},
            "user_username": "dev",
            "ref": "refs/heads/main",
        }

        with patch.object(worker.event_manager["push_reviewed"], "send") as mock_send:
            worker.handle_push_event(webhook_data, "token", "https://gitlab.local", "gitlab")

        mock_send.assert_not_called()
        handler.get_push_changes.assert_not_called()

    @patch.dict(os.environ, {"PUSH_REVIEW_ENABLED": "0"})
    @patch("biz.queue.worker.GithubPushHandler")
    def test_github_push_does_not_emit_review_event_when_push_review_disabled(
        self, mock_handler_cls
    ):
        handler = Mock()
        handler.get_push_commits.return_value = [
            {"message": "skip review", "author": "dev", "timestamp": "", "url": "#"}
        ]
        mock_handler_cls.return_value = handler
        webhook_data = {
            "repository": {"name": "alpha"},
            "sender": {"login": "dev"},
            "ref": "refs/heads/main",
        }

        with patch.object(worker.event_manager["push_reviewed"], "send") as mock_send:
            worker.handle_github_push_event(
                webhook_data, "token", "https://github.com", "github_com"
            )

        mock_send.assert_not_called()
        handler.get_push_changes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
