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

    @patch.dict(os.environ, {"PUSH_REVIEW_ENABLED": "1"})
    @patch("biz.queue.worker.CodeReviewer")
    @patch("biz.queue.worker.PushHandler")
    def test_gitlab_push_passes_filter_stats_to_reviewer(
        self, mock_handler_cls, mock_reviewer_cls
    ):
        handler = Mock()
        handler.get_push_commits.return_value = [
            {"message": "review", "author": "dev", "timestamp": "", "url": "#"}
        ]
        handler.get_push_changes.return_value = [
            {"new_path": "ok.py", "diff": "@@ -1 +1 @@\n-a\n+b"},
            {"new_path": "note.txt", "diff": "@@ -1 +1 @@\n-a\n+b"},
        ]
        mock_handler_cls.return_value = handler
        reviewer = Mock()
        reviewer.review_diffs.return_value.score = 100
        reviewer.review_diffs.return_value.parse_error = ""
        reviewer.review_diffs.return_value.risk_level = "low"
        reviewer.review_diffs.return_value.merge_advice = "approved"
        reviewer.review_diffs.return_value.summary = "ok"
        reviewer.review_diffs.return_value.comments = []
        reviewer.review_diffs.return_value.input_warnings = []
        mock_reviewer_cls.return_value = reviewer
        webhook_data = {
            "project": {"name": "alpha"},
            "project_id": 1,
            "user_username": "dev",
            "ref": "refs/heads/main",
            "after": "abc123",
        }

        with patch.object(worker.event_manager["push_reviewed"], "send"):
            worker.handle_push_event(
                webhook_data, "token", "https://gitlab.local", "gitlab"
            )

        _, _, kwargs = reviewer.review_diffs.mock_calls[0]
        self.assertIn(
            "Diff filter kept 1/2 files for review.",
            kwargs["input_warnings"],
        )
        self.assertIn(
            "Skipped files by reason: unsupported_extension=1.",
            kwargs["input_warnings"],
        )


if __name__ == "__main__":
    unittest.main()
