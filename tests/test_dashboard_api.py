import os
import tempfile
import unittest
import warnings

from flask import Flask

warnings.filterwarnings("ignore", category=ResourceWarning)

from biz.api import init_app
from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.service.review_service import ReviewService


class DashboardApiTest(unittest.TestCase):
    def setUp(self):
        self._old_db_file = ReviewService.DB_FILE
        self.tmpdir = tempfile.TemporaryDirectory()
        ReviewService.DB_FILE = os.path.join(self.tmpdir.name, "data.db")
        self.assertTrue(ReviewService.init_db())
        self._seed_data()

        app = Flask(__name__)
        init_app(app)
        self.client = app.test_client()

    def tearDown(self):
        ReviewService.DB_FILE = self._old_db_file
        self.tmpdir.cleanup()

    def _seed_data(self):
        ReviewService.insert_mr_review_log(
            MergeRequestReviewEntity(
                project_name="alpha",
                author="yangfan",
                source_branch="feature/a",
                target_branch="main",
                updated_at=1700000000,
                commits=[{"message": "add dashboard api"}],
                score=88,
                url="http://gitlab.local/alpha/-/merge_requests/1",
                review_result="MR review result",
                url_slug="alpha!1",
                webhook_data={},
                additions=120,
                deletions=15,
                last_commit_id="commit-1",
            )
        )
        ReviewService.insert_push_review_log(
            PushReviewEntity(
                project_name="beta",
                author="lisa",
                branch="develop",
                updated_at=1700000100,
                commits=[{"message": "fix reviewer"}],
                score=76,
                review_result="Push review result",
                url_slug="beta@develop",
                webhook_data={},
                additions=45,
                deletions=8,
            )
        )

    def test_summary_returns_real_aggregated_values(self):
        response = self.client.get("/api/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total_reviews"], 2)
        self.assertEqual(data["active_projects"], 2)
        self.assertEqual(data["active_members"], 2)
        self.assertEqual(data["average_score"], 82.0)
        self.assertEqual(data["recent_reviews"][0]["type"], "push")
        self.assertEqual(data["recent_reviews"][0]["project_name"], "beta")

    def test_summary_previous_period_keeps_author_and_project_filters(self):
        ReviewService.insert_mr_review_log(
            MergeRequestReviewEntity(
                project_name="alpha",
                author="yangfan",
                source_branch="feature/previous",
                target_branch="main",
                updated_at=1699999900,
                commits=[{"message": "previous matching review"}],
                score=90,
                url="http://gitlab.local/alpha/-/merge_requests/0",
                review_result="Previous matching result",
                url_slug="alpha!0",
                webhook_data={},
                additions=10,
                deletions=1,
                last_commit_id="commit-previous-match",
            )
        )
        ReviewService.insert_push_review_log(
            PushReviewEntity(
                project_name="beta",
                author="lisa",
                branch="develop",
                updated_at=1699999900,
                commits=[{"message": "previous unrelated review"}],
                score=70,
                review_result="Previous unrelated result",
                url_slug="beta@develop",
                webhook_data={},
                additions=5,
                deletions=2,
            )
        )

        response = self.client.get(
            "/api/dashboard/summary"
            "?author=yangfan&project_name=alpha&start=1700000000&end=1700000200"
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total_reviews"], 1)
        self.assertEqual(data["previous"]["total_reviews"], 1)
        self.assertEqual(data["previous"]["active_projects"], 1)
        self.assertEqual(data["previous"]["active_members"], 1)

    def test_reviews_support_type_filter_keyword_and_pagination(self):
        response = self.client.get(
            "/api/dashboard/reviews?type=mr&keyword=dashboard&page=1&page_size=10"
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["items"][0]["type"], "mr")
        self.assertEqual(data["items"][0]["project_name"], "alpha")
        self.assertEqual(data["items"][0]["source_branch"], "feature/a")

    def test_filter_options_returns_distinct_real_values(self):
        response = self.client.get("/api/dashboard/filter-options")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["authors"], ["lisa", "yangfan"])
        self.assertEqual(data["project_names"], ["alpha", "beta"])

    def test_members_returns_author_aggregates(self):
        response = self.client.get("/api/dashboard/members")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["summary"]["active_members"], 2)
        members = {item["author"]: item for item in data["items"]}
        self.assertEqual(members["yangfan"]["review_count"], 1)
        self.assertEqual(members["yangfan"]["average_score"], 88.0)
        self.assertEqual(members["yangfan"]["additions"], 120)
        self.assertEqual(members["lisa"]["deletions"], 8)


if __name__ == "__main__":
    unittest.main()
