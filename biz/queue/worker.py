import os
import traceback
from datetime import datetime

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.event.event_manager import event_manager
from biz.context.window import build_review_context
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
from biz.model.diff import Diff
from biz.model.review_context import ReviewContext
from biz.service.review_service import ReviewService
from biz.utils.code_reviewer import CodeReviewer
from biz.utils.im import notifier
from biz.utils.log import logger
from biz.utils.review_renderer import render_review_markdown


def _safe_commit_message(commit: dict) -> str:
    return (commit.get("message") or "").strip()


def _build_commits_text(commits: list[dict]) -> str:
    return ";".join(_safe_commit_message(commit) for commit in commits)


def _count_change_stats(changes: list[Diff]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for item in changes:
        additions += item.additions
        deletions += item.deletions
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


def _build_context(
    handler, changes: list[Diff], ref: str | None
) -> ReviewContext | None:
    if not ref or not hasattr(handler, "get_file_content"):
        return None
    try:
        return build_review_context(changes, ref, handler.get_file_content)
    except Exception as e:
        logger.warning(
            "Failed to build review context, falling back to diff-only review: %s", e
        )
        return None


def _review_changes(
    changes: list[Diff],
    commits: list[dict],
    project_context: dict | None = None,
    review_context: ReviewContext | None = None,
) -> tuple[str, int | None]:
    review_result = CodeReviewer(project_context).review_diffs(
        changes, _build_commits_text(commits), review_context
    )
    return render_review_markdown(review_result), review_result.score


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
        if not push_review_enabled:
            logger.info("Push review is disabled, skipping review event.")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            changes = filter_changes(changes)
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_context = _build_context(
                    handler, changes, webhook_data.get("after")
                )
                review_result, score = _review_changes(
                    changes,
                    commits,
                    _gitlab_project_context(webhook_data),
                    review_context,
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
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        handler = MergeRequestHandler(webhook_data, gitlab_token, gitlab_url)
        logger.info("Merge Request Hook event received")

        object_attributes = webhook_data.get("object_attributes", {})
        is_draft = object_attributes.get("draft") or object_attributes.get(
            "work_in_progress"
        )
        if is_draft:
            msg = (
                f"[Notice] MR is draft, AI review skipped.\n"
                f"Project: {webhook_data['project']['name']}\n"
                f"Author: {webhook_data['user']['username']}\n"
                f"Source Branch: {object_attributes.get('source_branch')}\n"
                f"Target Branch: {object_attributes.get('target_branch')}"
            )
            notifier.send_notification(content=msg)
            logger.info("MR is draft, sending notification only, skipping AI review.")
            return

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

        last_commit_id = object_attributes.get("last_commit", {}).get("id", "")
        if last_commit_id:
            project_name = webhook_data["project"]["name"]
            source_branch = object_attributes.get("source_branch", "")
            target_branch = object_attributes.get("target_branch", "")

            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, last_commit_id
            ):
                logger.info(
                    f"Merge Request with last_commit_id {last_commit_id} already exists, "
                    f"skipping review for {project_name}."
                )
                return

        changes = handler.get_merge_request_changes()
        logger.info("changes: %s", changes)
        changes = filter_changes(changes)
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        additions, deletions = _count_change_stats(changes)

        commits = handler.get_merge_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_context = _build_context(handler, changes, last_commit_id)
        review_result, score = _review_changes(
            changes, commits, _gitlab_project_context(webhook_data), review_context
        )

        handler.add_merge_request_notes(f"Auto Review Result: \n{review_result}")

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
        if not push_review_enabled:
            logger.info("GitHub push review is disabled, skipping review event.")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            changes = filter_github_changes(changes)
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_context = _build_context(
                    handler, changes, webhook_data.get("after")
                )
                review_result, score = _review_changes(
                    changes,
                    commits,
                    _github_project_context(webhook_data),
                    review_context,
                )
                additions, deletions = _count_change_stats(changes)
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
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        handler = GithubPullRequestHandler(webhook_data, github_token, github_url)
        logger.info("GitHub Pull Request event received")
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

        github_last_commit_id = webhook_data["pull_request"]["head"]["sha"]
        if github_last_commit_id:
            project_name = webhook_data["repository"]["name"]
            source_branch = webhook_data["pull_request"]["head"]["ref"]
            target_branch = webhook_data["pull_request"]["base"]["ref"]

            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, github_last_commit_id
            ):
                logger.info(
                    f"Pull Request with last_commit_id {github_last_commit_id} already exists, "
                    f"skipping review for {project_name}."
                )
                return

        changes = handler.get_pull_request_changes()
        logger.info("changes: %s", changes)
        changes = filter_github_changes(changes)
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        additions, deletions = _count_change_stats(changes)

        commits = handler.get_pull_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_context = _build_context(handler, changes, github_last_commit_id)
        review_result, score = _review_changes(
            changes, commits, _github_project_context(webhook_data), review_context
        )

        handler.add_pull_request_notes(f"Auto Review Result: \n{review_result}")

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
