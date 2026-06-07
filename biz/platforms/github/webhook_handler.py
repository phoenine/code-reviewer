import os
import re
import time
from urllib.parse import urlparse

import requests
import fnmatch
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
DEFAULT_SUPPORTED_EXTENSIONS = ".java,.py,.ts,.tsx,.js,.html,.scss,.sql,.yaml,.yml,.sh,.go,.json"


def _get_github_api_base_url(github_url: str) -> str:
    raw_url = (github_url or "").strip() or "https://github.com"
    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"

    parsed = urlparse(raw_url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    if host in {"github.com", "www.github.com"}:
        return "https://api.github.com"
    if path.endswith("/api/v3"):
        return f"{scheme}://{host}{path}"
    return f"{scheme}://{host}/api/v3"


def filter_changes(changes: list):
    """
    Filter changes, keeping only supported file types and necessary fields.
    Handles GitHub-specific change format.
    """
    # Read supported file extensions from env
    supported_extensions = os.getenv(
        "SUPPORTED_EXTENSIONS", DEFAULT_SUPPORTED_EXTENSIONS
    ).split(",")

    # Filter out deleted files
    not_deleted_changes = []
    for change in changes:
        # Check status field first for 'removed'
        if change.get("status") == "removed":
            logger.info(
                f"Detected file deletion via status field: {change.get('new_path')}"
            )
            continue

        # Fallback: inspect diff pattern for deletion
        diff = change.get("diff", "")
        if diff:
            diff_header_match = re.match(r"@@ -\d+,\d+ \+0,0 @@", diff)
            if diff_header_match:
                # Check if all lines (except header) start with '-'
                diff_lines = diff.split("\n")[1:]  # Skip diff header line
                if all(line.startswith("-") or not line for line in diff_lines):
                    logger.info(
                        f"Detected file deletion via diff pattern: {change.get('new_path')}"
                    )
                    continue

        not_deleted_changes.append(change)

    logger.info(f"SUPPORTED_EXTENSIONS: {supported_extensions}")
    logger.info(f"After filtering deleted files: {not_deleted_changes}")

    # Filter: keep only diff and new_path for supported extensions
    filtered_changes = [
        {
            "diff": item.get("diff", ""),
            "new_path": item["new_path"],
            "additions": item.get("additions", 0),
            "deletions": item.get("deletions", 0),
        }
        for item in not_deleted_changes
        if any(item.get("new_path", "").endswith(ext) for ext in supported_extensions)
    ]
    logger.info(f"After filtering by extension: {filtered_changes}")
    return filtered_changes


class PullRequestHandler:
    def __init__(self, webhook_data: dict, github_token: str, github_url: str):
        self.pull_request_number = None
        self.webhook_data = webhook_data
        self.github_token = github_token
        self.github_url = github_url
        self.event_type = None
        self.repo_full_name = None
        self.action = None
        self.api_base_url = _get_github_api_base_url(github_url)
        self.parse_event_type()

    def parse_event_type(self):
        # Extract event_type from webhook data
        self.event_type = "pull_request"  # Event type already resolved from X-GitHub-Event header
        self.parse_pull_request_event()

    def parse_pull_request_event(self):
        # Extract pull request fields
        self.pull_request_number = self.webhook_data.get("pull_request", {}).get(
            "number"
        )
        self.repo_full_name = self.webhook_data.get("repository", {}).get("full_name")
        self.action = self.webhook_data.get("action")

    def get_pull_request_changes(self) -> list:
        # Verify this is a pull request event
        if self.event_type != "pull_request":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'pull_request' event is supported now."
            )
            return []

        # GitHub PR changes API may lag; retry with backoff
        max_retries = 3  # Max retry attempts
        retry_delay = 10  # Delay between retries (seconds)
        for attempt in range(max_retries):
            # Fetch PR changed files from GitHub API
            url = f"{self.api_base_url}/repos/{self.repo_full_name}/pulls/{self.pull_request_number}/files"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
            logger.debug(
                f"Get changes response from GitHub (attempt {attempt + 1}): {response.status_code}, {response.text}, URL: {url}"
            )

            # Check if request succeeded
            if response.status_code == 200:
                files = response.json()
                if files:
                    # Convert to GitLab-compatible changes format
                    changes = []
                    for file in files:
                        change = {
                            "old_path": file.get("filename"),
                            "new_path": file.get("filename"),
                            "diff": file.get("patch", ""),
                            "additions": file.get("additions", 0),
                            "deletions": file.get("deletions", 0),
                        }
                        changes.append(change)
                    return changes
                else:
                    logger.info(
                        f"Changes is empty, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries}), URL: {url}"
                    )
                    time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Failed to get changes from GitHub (URL: {url}): {response.status_code}, {response.text}"
                )
                return []

        logger.warning(f"Max retries ({max_retries}) reached. Changes is still empty.")
        return []  # All retries exhausted

    def get_pull_request_commits(self) -> list:
        # Verify this is a pull request event
        if self.event_type != "pull_request":
            return []

        # Fetch PR commits from GitHub API
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/pulls/{self.pull_request_number}/commits"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get commits response from GitHub: {response.status_code}, {response.text}"
        )

        # Check if request succeeded
        if response.status_code == 200:
            # Convert GitHub commits to GitLab-compatible format
            github_commits = response.json()
            gitlab_format_commits = []
            for commit in github_commits:
                gitlab_commit = {
                    "id": commit.get("sha"),
                    "title": commit.get("commit", {}).get("message", "").split("\n")[0],
                    "message": commit.get("commit", {}).get("message", ""),
                    "author_name": commit.get("commit", {})
                    .get("author", {})
                    .get("name"),
                    "author_email": commit.get("commit", {})
                    .get("author", {})
                    .get("email"),
                    "created_at": commit.get("commit", {})
                    .get("author", {})
                    .get("date"),
                    "web_url": commit.get("html_url"),
                }
                gitlab_format_commits.append(gitlab_commit)
            return gitlab_format_commits
        else:
            logger.warning(
                f"Failed to get commits: {response.status_code}, {response.text}"
            )
            return []

    def add_pull_request_notes(self, review_result):
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/issues/{self.pull_request_number}/comments"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        data = {"body": review_result}
        response = requests.post(
            url, headers=headers, json=data, timeout=HTTP_TIMEOUT_SECONDS
        )
        logger.debug(
            f"Add comment to GitHub PR {url}: {response.status_code}, {response.text}"
        )
        if response.status_code == 201:
            logger.info("Comment successfully added to pull request.")
        else:
            logger.error(f"Failed to add comment: {response.status_code}")
            logger.error(response.text)

    def target_branch_protected(self) -> bool:
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/branches?protected=true"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        if response.status_code == 200:
            data = response.json()
            target_branch = self.webhook_data["pull_request"]["base"]["ref"]
            return any(fnmatch.fnmatch(target_branch, item["name"]) for item in data)
        else:
            logger.warning(
                f"Failed to get protected branches: {response.status_code}, {response.text}"
            )
            return False


class PushHandler:
    def __init__(self, webhook_data: dict, github_token: str, github_url: str):
        self.webhook_data = webhook_data
        self.github_token = github_token
        self.github_url = github_url
        self.event_type = None
        self.repo_full_name = None
        self.branch_name = None
        self.commit_list = []
        self.api_base_url = _get_github_api_base_url(github_url)
        self.parse_event_type()

    def parse_event_type(self):
        # Extract event_type from webhook data
        self.event_type = "push"  # Event type already resolved from X-GitHub-Event header
        self.parse_push_event()

    def parse_push_event(self):
        # Extract push event fields
        self.repo_full_name = self.webhook_data.get("repository", {}).get("full_name")
        self.branch_name = self.webhook_data.get("ref", "").replace("refs/heads/", "")
        self.commit_list = self.webhook_data.get("commits", [])

    def get_push_commits(self) -> list:
        # Verify this is a push event
        if self.event_type != "push":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'push' event is supported now."
            )
            return []

        # Extract commit details
        commit_details = []
        for commit in self.commit_list:
            commit_info = {
                "message": commit.get("message"),
                "author": commit.get("author", {}).get("name"),
                "timestamp": commit.get("timestamp"),
                "url": commit.get("url"),
            }
            commit_details.append(commit_info)

        logger.info(f"Collected {len(commit_details)} commits from push event.")
        return commit_details

    def add_push_notes(self, message: str):
        # Add comment to the last push commit
        if not self.commit_list:
            logger.warning("No commits found to add notes to.")
            return

        # Get the last commit ID
        last_commit_id = self.commit_list[-1].get("id")
        if not last_commit_id:
            logger.error("Last commit ID not found.")
            return

        url = f"{self.api_base_url}/repos/{self.repo_full_name}/commits/{last_commit_id}/comments"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        data = {"body": message}
        response = requests.post(
            url, headers=headers, json=data, timeout=HTTP_TIMEOUT_SECONDS
        )
        logger.debug(
            f"Add comment to commit {last_commit_id}: {response.status_code}, {response.text}"
        )
        if response.status_code == 201:
            logger.info("Comment successfully added to push commit.")
        else:
            logger.error(f"Failed to add comment: {response.status_code}")
            logger.error(response.text)

    def __repository_commits(self, sha: str = "", per_page: int = 100, page: int = 1):
        # Fetch repository commits
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/commits?sha={sha}&per_page={per_page}&page={page}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get commits response from GitHub for repository_commits: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to get commits for sha {sha}: {response.status_code}, {response.text}"
            )
            return []

    def get_parent_commit_id(self, commit_id: str) -> str:
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/commits/{commit_id}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get commit response from GitHub: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200 and response.json().get("parents"):
            return response.json().get("parents")[0].get("sha", "")
        return ""

    def repository_compare(self, base: str, head: str):
        # Compare two commits
        url = f"{urljoin(f'{self.github_url}/', f'repos/{self.repo_full_name}/compare/{base}...{head}')}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get changes response from GitHub for repository_compare: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
            # Convert GitHub diff to GitLab-compatible format
            files = response.json().get("files", [])
            diffs = []
            for file in files:
                diff = {
                    "old_path": file.get("filename"),
                    "new_path": file.get("filename"),
                    "diff": file.get("patch", ""),
                    "status": file.get("status", ""),
                    "additions": file.get("additions", 0),
                    "deletions": file.get("deletions", 0),
                }
                diffs.append(diff)
            return diffs
        else:
            logger.warning(
                f"Failed to get changes for repository_compare: {response.status_code}, {response.text}"
            )
            return []

    def get_push_changes(self) -> list:
        # Verify this is a push event
        if self.event_type != "push":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'push' event is supported now."
            )
            return []

        # No commits, return empty
        if not self.commit_list:
            logger.info("No commits found in push event.")
            return []

        # Prefer compare API for changes
        before = self.webhook_data.get("before", "")
        after = self.webhook_data.get("after", "")
        if before and after:
            # GitHub doesn't use 0000000; check for branch create/delete instead
            if self.webhook_data.get("created", False):
                # Branch creation
                first_commit_id = self.commit_list[0].get("id")
                if first_commit_id:
                    parent_commit_id = self.get_parent_commit_id(first_commit_id)
                    if parent_commit_id:
                        before = parent_commit_id
            elif self.webhook_data.get("deleted", False):
                # Branch deletion — skip
                return []

            return self.repository_compare(before, after)
        else:
            # Fallback: fetch via commits when before/after unavailable
            logger.info(
                "before or after not found in webhook data, trying to get changes from commits."
            )

            changes = []
            for commit in self.commit_list:
                commit_id = commit.get("id")
                if commit_id:
                    parent_id = self.get_parent_commit_id(commit_id)
                    if parent_id:
                        commit_changes = self.repository_compare(parent_id, commit_id)
                        changes.extend(commit_changes)

            return changes
