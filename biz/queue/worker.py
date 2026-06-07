import os
import traceback
from datetime import datetime

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.event.event_manager import event_manager
from biz.platforms.gitlab.webhook_handler import (
    filter_changes,
    MergeRequestHandler,
    PushHandler,
)
from biz.platforms.github.webhook_handler import (
    filter_changes as filter_github_changes,
    PullRequestHandler as GithubPullRequestHandler,
    PushHandler as GithubPushHandler,
)
from biz.service.review_service import ReviewService
from biz.utils.code_reviewer import CodeReviewer
from biz.utils.im import notifier
from biz.utils.log import logger


def _safe_commit_message(commit: dict) -> str:
    return (commit.get("message") or "").strip()


def _build_commits_text(commits: list[dict]) -> str:
    return ";".join(_safe_commit_message(commit) for commit in commits)


def _count_change_stats(changes: list[dict]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for item in changes:
        additions += item.get("additions", 0)
        deletions += item.get("deletions", 0)
    return additions, deletions


def _gitlab_project_context(webhook_data: dict) -> dict:
    return webhook_data.get("project", {}) or {}


def _github_project_context(webhook_data: dict) -> dict:
    repository = webhook_data.get("repository", {}) or {}
    return {
        "name": repository.get("name"),
        "path": repository.get("name"),
        "full_name": repository.get("full_name"),
        "html_url": repository.get("html_url"),
    }


def _review_changes(
    changes: list[dict], commits: list[dict], project_context: dict | None = None
) -> tuple[str, int | None]:
    review_result = CodeReviewer(project_context).review_and_strip_code(
        str(changes), _build_commits_text(commits)
    )
    score = CodeReviewer.parse_review_score(review_text=review_result)
    return review_result, score


def handle_push_event(
    webhook_data: dict, gitlab_token: str, gitlab_url: str, gitlab_url_slug: str
):
    push_review_enabled = os.environ.get("PUSH_REVIEW_ENABLED", "0") == "1"
    try:
        handler = PushHandler(webhook_data, gitlab_token, gitlab_url)
        logger.info("Push Hook event received")
        commits = handler.get_push_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            # Fetch push changes
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            changes = filter_changes(changes)
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_result, score = _review_changes(
                    changes, commits, _gitlab_project_context(webhook_data)
                )
                additions, deletions = _count_change_stats(changes)
            # Post review result as GitLab note
            handler.add_push_notes(f"Auto Review Result: \n{review_result}")

        event_manager["push_reviewed"].send(
            PushReviewEntity(
                project_name=webhook_data["project"]["name"],
                author=webhook_data["user_username"],
                branch=webhook_data.get("ref", "").replace("refs/heads/", ""),
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                review_result=review_result,
                url_slug=gitlab_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_merge_request_event(
    webhook_data: dict, gitlab_token: str, gitlab_url: str, gitlab_url_slug: str
):
    """
    Handle GitLab Merge Request Hook event
    :param webhook_data:
    :param gitlab_token:
    :param gitlab_url:
    :param gitlab_url_slug:
    :return:
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        # Parse webhook data
        handler = MergeRequestHandler(webhook_data, gitlab_token, gitlab_url)
        logger.info("Merge Request Hook event received")

        # Check if MR is a draft
        object_attributes = webhook_data.get("object_attributes", {})
        is_draft = object_attributes.get("draft") or object_attributes.get(
            "work_in_progress"
        )
        if is_draft:
            msg = f"[Notice] MR is draft, AI review skipped.\\nProject: {webhook_data['project']['name']}\\nAuthor: {webhook_data['user']['username']}\\nSource Branch: {object_attributes.get('source_branch')}\\nTarget Branch: {object_attributes.get('target_branch')}"
            notifier.send_notification(content=msg)
            logger.info("MR is draft, sending notification only, skipping AI review.")
            return

        # If review-only-protected-branches is on, check target branch
        if (
            merge_review_only_protected_branches
            and not handler.target_branch_protected()
        ):
            logger.info(
                "Merge Request target branch not match protected branches, ignored."
            )
            return

        if handler.action not in ["open", "update"]:
            logger.info(f"Merge Request Hook event, action={handler.action}, ignored.")
            return

        # Skip if last_commit_id already processed
        last_commit_id = object_attributes.get("last_commit", {}).get("id", "")
        if last_commit_id:
            project_name = webhook_data["project"]["name"]
            source_branch = object_attributes.get("source_branch", "")
            target_branch = object_attributes.get("target_branch", "")

            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, last_commit_id
            ):
                logger.info(
                    f"Merge Request with last_commit_id {last_commit_id} already exists, skipping review for {project_name}."
                )
                return

        # Only review on MR open/update
        # Fetch MR changes
        changes = handler.get_merge_request_changes()
        logger.info("changes: %s", changes)
        changes = filter_changes(changes)
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        # Count additions and deletions
        additions, deletions = _count_change_stats(changes)

        # Fetch MR commits
        commits = handler.get_merge_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        # Run code review
        review_result, score = _review_changes(
            changes, commits, _gitlab_project_context(webhook_data)
        )

        # Post review result as GitLab note
        handler.add_merge_request_notes(f"Auto Review Result: \n{review_result}")

        # dispatch merge_request_reviewed event
        event_manager["merge_request_reviewed"].send(
            MergeRequestReviewEntity(
                project_name=webhook_data["project"]["name"],
                author=webhook_data["user"]["username"],
                source_branch=webhook_data["object_attributes"]["source_branch"],
                target_branch=webhook_data["object_attributes"]["target_branch"],
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                url=webhook_data["object_attributes"]["url"],
                review_result=review_result,
                url_slug=gitlab_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
                last_commit_id=last_commit_id,
            )
        )

    except Exception as e:
        error_message = (
            f"AI Code Review unexpected error: {str(e)}\n{traceback.format_exc()}"
        )
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_github_push_event(
    webhook_data: dict, github_token: str, github_url: str, github_url_slug: str
):
    push_review_enabled = os.environ.get("PUSH_REVIEW_ENABLED", "0") == "1"
    try:
        handler = GithubPushHandler(webhook_data, github_token, github_url)
        logger.info("GitHub Push event received")
        commits = handler.get_push_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            # Fetch push changes
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            changes = filter_github_changes(changes)
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_result, score = _review_changes(
                    changes, commits, _github_project_context(webhook_data)
                )
                additions, deletions = _count_change_stats(changes)
            # Post review result as GitHub PR note
            handler.add_push_notes(f"Auto Review Result: \n{review_result}")

        event_manager["push_reviewed"].send(
            PushReviewEntity(
                project_name=webhook_data["repository"]["name"],
                author=webhook_data["sender"]["login"],
                branch=webhook_data["ref"].replace("refs/heads/", ""),
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                review_result=review_result,
                url_slug=github_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_github_pull_request_event(
    webhook_data: dict, github_token: str, github_url: str, github_url_slug: str
):
    """
    Handle GitHub Pull Request event
    :param webhook_data:
    :param github_token:
    :param github_url:
    :param github_url_slug:
    :return:
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        # Parse webhook data
        handler = GithubPullRequestHandler(webhook_data, github_token, github_url)
        logger.info("GitHub Pull Request event received")
        # If review-only-protected-branches is on, check target branch
        if (
            merge_review_only_protected_branches
            and not handler.target_branch_protected()
        ):
            logger.info(
                "Merge Request target branch not match protected branches, ignored."
            )
            return

        if handler.action not in ["opened", "synchronize"]:
            logger.info(f"Pull Request Hook event, action={handler.action}, ignored.")
            return

        # Skip if last_commit_id already processed (GitHub PR)
        github_last_commit_id = webhook_data["pull_request"]["head"]["sha"]
        if github_last_commit_id:
            project_name = webhook_data["repository"]["name"]
            source_branch = webhook_data["pull_request"]["head"]["ref"]
            target_branch = webhook_data["pull_request"]["base"]["ref"]

            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, github_last_commit_id
            ):
                logger.info(
                    f"Pull Request with last_commit_id {github_last_commit_id} already exists, skipping review for {project_name}."
                )
                return

        # Only review on PR open/update
        # Fetch PR changes
        changes = handler.get_pull_request_changes()
        logger.info("changes: %s", changes)
        changes = filter_github_changes(changes)
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        # Count additions and deletions
        additions, deletions = _count_change_stats(changes)

        # Fetch PR commits
        commits = handler.get_pull_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        # Run code review
        review_result, score = _review_changes(
            changes, commits, _github_project_context(webhook_data)
        )

        # Post review result as GitHub PR note
        handler.add_pull_request_notes(f"Auto Review Result: \n{review_result}")

        # dispatch pull_request_reviewed event
        event_manager["merge_request_reviewed"].send(
            MergeRequestReviewEntity(
                project_name=webhook_data["repository"]["name"],
                author=webhook_data["pull_request"]["user"]["login"],
                source_branch=webhook_data["pull_request"]["head"]["ref"],
                target_branch=webhook_data["pull_request"]["base"]["ref"],
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                url=webhook_data["pull_request"]["html_url"],
                review_result=review_result,
                url_slug=github_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
                last_commit_id=github_last_commit_id,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)
