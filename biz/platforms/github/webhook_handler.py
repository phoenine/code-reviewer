import base64
import binascii
import os
import time
from urllib.parse import quote, urlparse

import requests
import fnmatch
from biz.diff.filter import filter_diffs
from biz.diff.parser import parse_changes
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


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


def _get_repository_file_content(
    api_base_url: str, repo_full_name: str | None, github_token: str, path: str, ref: str
) -> str | None:
    if not repo_full_name or not path or not ref:
        return None

    encoded_path = quote(path, safe="/")
    url = f"{api_base_url}/repos/{repo_full_name}/contents/{encoded_path}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.raw",
    }
    response = requests.get(
        url, headers=headers, params={"ref": ref}, timeout=HTTP_TIMEOUT_SECONDS
    )
    logger.debug(
        "Get file content from GitHub: %s, URL: %s, path: %s, ref: %s",
        response.status_code,
        url,
        path,
        ref,
    )
    if response.status_code != 200:
        logger.warning(
            "Failed to get file content from GitHub: %s, %s, path=%s, ref=%s",
            response.status_code,
            response.text,
            path,
            ref,
        )
        return None

    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return response.content.decode("utf-8", errors="replace")

    try:
        data = response.json()
    except ValueError:
        return response.content.decode("utf-8", errors="replace")
    if isinstance(data, dict) and "content" in data:
        encoded_content = data.get("content")
        if not encoded_content or not str(encoded_content).strip():
            return None
        try:
            return base64.b64decode(encoded_content).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError) as exc:
            logger.warning(
                "Failed to decode GitHub file content: %s, path=%s", exc, path
            )
            return None
    return response.content.decode("utf-8", errors="replace")


def filter_changes(changes: list):
    """Filter changes, delegating to the structured diff pipeline"""
    return filter_diffs(parse_changes(changes, source="github"))


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
        self.event_type = "pull_request"
        self.parse_pull_request_event()

    def parse_pull_request_event(self):
        self.pull_request_number = self.webhook_data.get("pull_request", {}).get(
            "number"
        )
        self.repo_full_name = self.webhook_data.get("repository", {}).get("full_name")
        self.action = self.webhook_data.get("action")

    def get_pull_request_changes(self) -> list:
        if self.event_type != "pull_request":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'pull_request' event is supported now."
            )
            return []

        max_retries = 3
        retry_delay = 10
        for attempt in range(max_retries):
            url = f"{self.api_base_url}/repos/{self.repo_full_name}/pulls/{self.pull_request_number}/files"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
            logger.debug(
                f"Get changes response from GitHub (attempt {attempt + 1}): {response.status_code}, {response.text}, URL: {url}"
            )

            if response.status_code == 200:
                files = response.json()
                if files:
                    changes = []
                    for file in files:
                        change = {
                            "old_path": file.get("filename"),
                            "new_path": file.get("filename"),
                            "diff": file.get("patch", ""),
                            "filename": file.get("filename"),
                            "previous_filename": file.get("previous_filename"),
                            "patch": file.get("patch", ""),
                            "status": file.get("status", ""),
                            "sha": file.get("sha", ""),
                            "additions": file.get("additions", 0),
                            "deletions": file.get("deletions", 0),
                        }
                        changes.append(change)
                    return changes
                else:
                    logger.info(
                        f"Changes is empty, retrying in {retry_delay} seconds... "
                        f"(attempt {attempt + 1}/{max_retries}), URL: {url}"
                    )
                    time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Failed to get changes from GitHub (URL: {url}): {response.status_code}, {response.text}"
                )
                return []

        logger.warning(f"Max retries ({max_retries}) reached. Changes is still empty.")
        return []

    def get_pull_request_commits(self) -> list:
        if self.event_type != "pull_request":
            return []

        url = f"{self.api_base_url}/repos/{self.repo_full_name}/pulls/{self.pull_request_number}/commits"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get commits response from GitHub: {response.status_code}, {response.text}"
        )

        if response.status_code == 200:
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

    def get_file_content(self, path: str, ref: str) -> str | None:
        return _get_repository_file_content(
            self.api_base_url,
            self.repo_full_name,
            self.github_token,
            path,
            ref,
        )

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
        self.event_type = "push"
        self.parse_push_event()

    def parse_push_event(self):
        self.repo_full_name = self.webhook_data.get("repository", {}).get("full_name")
        self.branch_name = self.webhook_data.get("ref", "").replace("refs/heads/", "")
        self.commit_list = self.webhook_data.get("commits", [])

    def get_push_commits(self) -> list:
        if self.event_type != "push":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'push' event is supported now."
            )
            return []

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
        if not self.commit_list:
            logger.warning("No commits found to add notes to.")
            return

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

    def get_file_content(self, path: str, ref: str) -> str | None:
        return _get_repository_file_content(
            self.api_base_url,
            self.repo_full_name,
            self.github_token,
            path,
            ref,
        )

    def __repository_commits(self, sha: str = "", per_page: int = 100, page: int = 1):
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
        url = f"{self.api_base_url}/repos/{self.repo_full_name}/compare/{base}...{head}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        logger.debug(
            f"Get changes response from GitHub for repository_compare: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
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
        if self.event_type != "push":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'push' event is supported now."
            )
            return []

        if not self.commit_list:
            logger.info("No commits found in push event.")
            return []

        before = self.webhook_data.get("before", "")
        after = self.webhook_data.get("after", "")
        if before and after:
            if self.webhook_data.get("created", False):
                first_commit_id = self.commit_list[0].get("id")
                if first_commit_id:
                    parent_commit_id = self.get_parent_commit_id(first_commit_id)
                    if parent_commit_id:
                        before = parent_commit_id
            elif self.webhook_data.get("deleted", False):
                return []

            return self.repository_compare(before, after)
        else:
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
