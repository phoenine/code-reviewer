import json
import os
import uuid
import hmac
import hashlib
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify

from biz.platforms.gitlab.webhook_handler import slugify_url
from biz.queue.worker import (
    handle_merge_request_event,
    handle_push_event,
    handle_github_pull_request_event,
    handle_github_push_event,
)
from biz.utils.log import logger
from biz.utils.queue import QueueStatus, handle_queue

webhook_bp = Blueprint("webhook", __name__)


@webhook_bp.route("/review/webhook", methods=["POST"])
def handle_webhook():
    """
    Main route for handling Webhook requests.
    """
    # Parse request JSON body
    if request.is_json:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400
        # Determine webhook source
        webhook_source_github = request.headers.get("X-GitHub-Event")
        if webhook_source_github:  # GitHub webhook
            return handle_github_webhook(webhook_source_github, data)
        else:  # GitLab webhook
            return handle_gitlab_webhook(data)
    else:
        return jsonify({"message": "Invalid data format"}), 400


def _extract_request_id(data: dict, platform: str) -> str:
    header_candidates = [
        "X-Request-ID",
        "X-Correlation-ID",
        "X-GitHub-Delivery",
        "X-Gitlab-Event-UUID",
    ]
    for name in header_candidates:
        value = request.headers.get(name)
        if value:
            return value

    payload_candidates = []
    if platform == "github":
        payload_candidates = [
            data.get("delivery"),
            data.get("after"),
            data.get("head_commit", {}).get("id"),
        ]
    elif platform == "gitlab":
        payload_candidates = [
            data.get("event_id"),
            data.get("after"),
            data.get("checkout_sha"),
        ]

    for value in payload_candidates:
        if value:
            return str(value)

    return str(uuid.uuid4())


def _build_task_context(
    platform: str, event_type: str, data: dict, request_id: str
) -> dict:
    return {
        "request_id": request_id,
        "platform": platform,
        "event_type": event_type,
        "project_id": data.get("project_id") or data.get("project", {}).get("id"),
        "project_name": data.get("project", {}).get("name")
        or data.get("repository", {}).get("name"),
        "user_agent": request.headers.get("User-Agent"),
        "remote_addr": request.remote_addr,
    }


def _queue_reject_response(request_id: str):
    return (
        jsonify(
            {
                "message": "Worker queue is full, please retry later.",
                "request_id": request_id,
            }
        ),
        503,
    )


def _verify_github_webhook_signature(secret: str) -> bool:
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature:
        return False
    if not signature.startswith("sha256="):
        return False

    payload = request.get_data(cache=True, as_text=False) or b""
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def handle_github_webhook(event_type, data):
    """
    Handle GitHub Webhook
    """
    # Use env var access token only, never confuse with webhook secret
    github_token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not github_token:
        return jsonify({"message": "Missing GITHUB_ACCESS_TOKEN"}), 400

    # Optional: verify webhook signature via X-Hub-Signature-256 header
    github_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if github_webhook_secret:
        if not _verify_github_webhook_signature(github_webhook_secret):
            return jsonify({"message": "Invalid GitHub webhook secret"}), 401

    github_url = os.getenv("GITHUB_URL") or "https://github.com"
    github_url_slug = slugify_url(github_url)
    request_id = _extract_request_id(data, platform="github")
    task_context = _build_task_context(
        platform="github", event_type=event_type, data=data, request_id=request_id
    )

    # Log the full payload
    logger.info(f"Received GitHub event: {event_type}")
    logger.info(f"Payload: {json.dumps(data)}")

    if event_type == "pull_request":
        # Submit to async worker queue
        queue_status = handle_queue(
            handle_github_pull_request_event,
            data,
            github_token,
            github_url,
            github_url_slug,
            task_context=task_context,
        )
        if queue_status == QueueStatus.REJECTED_QUEUE_FULL:
            return _queue_reject_response(request_id)
        # Return immediately
        return (
            jsonify(
                {
                    "message": f"GitHub request received(event_type={event_type}), will process asynchronously.",
                    "request_id": request_id,
                }
            ),
            200,
        )
    elif event_type == "push":
        # Submit to async worker queue
        queue_status = handle_queue(
            handle_github_push_event,
            data,
            github_token,
            github_url,
            github_url_slug,
            task_context=task_context,
        )
        if queue_status == QueueStatus.REJECTED_QUEUE_FULL:
            return _queue_reject_response(request_id)
        # Return immediately
        return (
            jsonify(
                {
                    "message": f"GitHub request received(event_type={event_type}), will process asynchronously.",
                    "request_id": request_id,
                }
            ),
            200,
        )
    else:
        error_message = f"Only pull_request and push events are supported for GitHub webhook, but received: {event_type}."
        logger.error(error_message)
        return jsonify(error_message), 400


def handle_gitlab_webhook(data):
    """
    Handle GitLab Webhook
    """
    # Regular webhook uses object_kind; System Hook uses event_name
    object_kind = data.get("object_kind") or data.get("event_name")
    request_id = _extract_request_id(data, platform="gitlab")
    task_context = _build_task_context(
        platform="gitlab", event_type=object_kind, data=data, request_id=request_id
    )

    # Resolve GitLab URL: header > env > push event repository
    gitlab_url = os.getenv("GITLAB_URL") or request.headers.get("X-Gitlab-Instance")
    if not gitlab_url:
        repository = data.get("repository")
        if not repository:
            return jsonify({"message": "Missing GitLab URL"}), 400
        homepage = repository.get("homepage")
        if not homepage:
            return jsonify({"message": "Missing GitLab URL"}), 400
        try:
            parsed_url = urlparse(homepage)
            gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        except Exception as e:
            return jsonify({"error": f"Failed to parse homepage URL: {str(e)}"}), 400

    # Use env var access token only, never confuse with webhook secret
    gitlab_token = os.getenv("GITLAB_ACCESS_TOKEN")
    if not gitlab_token:
        return jsonify({"message": "Missing GITLAB_ACCESS_TOKEN"}), 400

    # Optional: verify webhook signature via X-Gitlab-Token header
    gitlab_webhook_secret = os.getenv("GITLAB_WEBHOOK_SECRET")
    if gitlab_webhook_secret:
        header_secret = request.headers.get("X-Gitlab-Token")
        if header_secret != gitlab_webhook_secret:
            return jsonify({"message": "Invalid GitLab webhook secret"}), 401

    gitlab_url_slug = slugify_url(gitlab_url)

    # Log the full payload for debugging
    logger.info(f"Received event: {object_kind}")
    logger.info(f"Payload: {json.dumps(data)}")

    # Handle merge request hook
    if object_kind == "merge_request":
        # Enqueue to thread pool for async processing
        queue_status = handle_queue(
            handle_merge_request_event,
            data,
            gitlab_token,
            gitlab_url,
            gitlab_url_slug,
            task_context=task_context,
        )
        if queue_status == QueueStatus.REJECTED_QUEUE_FULL:
            return _queue_reject_response(request_id)
        # Return immediately
        return (
            jsonify(
                {
                    "message": f"Request received(object_kind={object_kind}), will process asynchronously.",
                    "request_id": request_id,
                }
            ),
            200,
        )
    elif object_kind == "push":
        # Enqueue to thread pool for async processing
        # TODO check if PUSH_REVIEW_ENABLED is needed here
        queue_status = handle_queue(
            handle_push_event,
            data,
            gitlab_token,
            gitlab_url,
            gitlab_url_slug,
            task_context=task_context,
        )
        if queue_status == QueueStatus.REJECTED_QUEUE_FULL:
            return _queue_reject_response(request_id)
        # Return immediately
        return (
            jsonify(
                {
                    "message": f"Request received(object_kind={object_kind}), will process asynchronously.",
                    "request_id": request_id,
                }
            ),
            200,
        )
    else:
        error_message = (
            "Only merge_request and push events are supported "
            f"(both Webhook and System Hook), but received: {object_kind}."
        )
        logger.error(error_message)
        return jsonify(error_message), 400
