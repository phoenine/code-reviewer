import os
import re
import time
from urllib.parse import urljoin
import fnmatch
import requests

from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
DEFAULT_SUPPORTED_EXTENSIONS = ".java,.py,.ts,.tsx,.js,.html,.scss,.sql,.yaml,.yml,.sh,.go,.json"


def filter_changes(changes: list):
    """
    Filter changes, keeping only supported file types and necessary fields.
    """
    # Read supported file extensions from env
    supported_extensions = os.getenv(
        "SUPPORTED_EXTENSIONS", DEFAULT_SUPPORTED_EXTENSIONS
    ).split(",")

    filter_deleted_files_changes = [
        change for change in changes if not change.get("deleted_file")
    ]

    # Filter changes: keep only diff and new_path for supported extensions
    filtered_changes = [
        {
            "diff": item.get("diff", ""),
            "new_path": item["new_path"],
            "additions": len(
                re.findall(r"^\+(?!\+\+)", item.get("diff", ""), re.MULTILINE)
            ),
            "deletions": len(
                re.findall(r"^-(?!--)", item.get("diff", ""), re.MULTILINE)
            ),
        }
        for item in filter_deleted_files_changes
        if any(item.get("new_path", "").endswith(ext) for ext in supported_extensions)
    ]
    return filtered_changes


def slugify_url(original_url: str) -> str:
    """
    Convert a URL to a file-name-safe slug. Non-alphanumeric chars become underscores.
    Example:
    slugify_url("http://example.com/path/to/repo/") => example_com_path_to_repo
    slugify_url("https://gitlab.com/user/repo.git") => gitlab_com_user_repo_git
    """
    # Remove URL scheme (http, https, etc.) if present
    original_url = re.sub(r"^https?://", "", original_url)

    # Replace non-alphanumeric characters (except underscore) with underscores
    target = re.sub(r"[^a-zA-Z0-9]", "_", original_url)

    # Remove trailing underscore if present
    target = target.rstrip("_")

    return target


class MergeRequestHandler:
    def __init__(self, webhook_data: dict, gitlab_token: str, gitlab_url: str):
        self.merge_request_iid = None
        self.webhook_data = webhook_data
        self.gitlab_token = gitlab_token
        self.gitlab_url = gitlab_url
        self.event_type = None
        self.project_id = None
        self.action = None
        self.parse_event_type()

    def parse_event_type(self):
        # Extract event_type from webhook data
        self.event_type = self.webhook_data.get("object_kind", None)
        if self.event_type == "merge_request":
            self.parse_merge_request_event()

    def parse_merge_request_event(self):
        # Extract merge request fields from payload
        merge_request = self.webhook_data.get("object_attributes", {})
        self.merge_request_iid = merge_request.get("iid")
        self.project_id = merge_request.get("target_project_id")
        self.action = merge_request.get("action")

    def get_merge_request_changes(self) -> list:
        # Verify this is a merge request event
        if self.event_type != "merge_request":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'merge_request' event is supported now."
            )
            return []

        # GitLab changes API may lag; retry with backoff
        max_retries = 3  # Max retry attempts
        retry_delay = 10  # Delay between retries (seconds)
        for attempt in range(max_retries):
            # Fetch merge request changes from GitLab API
            url = urljoin(
                f"{self.gitlab_url}/",
                f"api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/changes?access_raw_diffs=true",
            )
            headers = {"Private-Token": self.gitlab_token}
            response = requests.get(
                url,
                headers=headers,
                verify=False,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            logger.debug(
                f"Get changes response from GitLab (attempt {attempt + 1}): {response.status_code}, {response.text}, URL: {url}"
            )

            # Check if request succeeded
            if response.status_code == 200:
                changes = response.json().get("changes", [])
                if changes:
                    return changes
                else:
                    logger.info(
                        f"Changes is empty, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries}), URL: {url}"
                    )
                    time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Failed to get changes from GitLab (URL: {url}): {response.status_code}, {response.text}"
                )
                return []

        logger.warning(f"Max retries ({max_retries}) reached. Changes is still empty.")
        return []  # All retries exhausted

    def get_merge_request_commits(self) -> list:
        # Verify this is a merge request event
        if self.event_type != "merge_request":
            return []

        # Fetch merge request commits from GitLab API
        url = urljoin(
            f"{self.gitlab_url}/",
            f"api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/commits",
        )
        headers = {"Private-Token": self.gitlab_token}
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Get commits response from gitlab: {response.status_code}, {response.text}"
        )
        # Check if request succeeded
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to get commits: {response.status_code}, {response.text}"
            )
            return []

    def add_merge_request_notes(self, review_result):
        url = urljoin(
            f"{self.gitlab_url}/",
            f"api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/notes",
        )
        headers = {
            "Private-Token": self.gitlab_token,
            "Content-Type": "application/json",
        }
        data = {"body": review_result}
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Add notes to gitlab {url}: {response.status_code}, {response.text}"
        )
        if response.status_code == 201:
            logger.info("Note successfully added to merge request.")
        else:
            logger.error(f"Failed to add note: {response.status_code}")
            logger.error(response.text)

    def target_branch_protected(self) -> bool:
        url = urljoin(
            f"{self.gitlab_url}/",
            f"api/v4/projects/{self.project_id}/protected_branches",
        )
        headers = {
            "Private-Token": self.gitlab_token,
            "Content-Type": "application/json",
        }
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Get protected branches response from gitlab: {response.status_code}, {response.text}"
        )
        # Check if request succeeded
        if response.status_code == 200:
            data = response.json()
            target_branch = self.webhook_data["object_attributes"]["target_branch"]
            return any(fnmatch.fnmatch(target_branch, item["name"]) for item in data)
        else:
            logger.warning(
                f"Failed to get protected branches: {response.status_code}, {response.text}"
            )
            return False


class PushHandler:
    def __init__(self, webhook_data: dict, gitlab_token: str, gitlab_url: str):
        self.webhook_data = webhook_data
        self.gitlab_token = gitlab_token
        self.gitlab_url = gitlab_url
        self.event_type = None
        self.project_id = None
        self.branch_name = None
        self.commit_list = []
        self.parse_event_type()

    def parse_event_type(self):
        # Extract event_type from webhook data
        # Regular webhook uses object_kind; System Hook uses event_name
        self.event_type = self.webhook_data.get("event_name") or self.webhook_data.get(
            "object_kind"
        )
        if self.event_type == "push":
            self.parse_push_event()

    def parse_push_event(self):
        # Extract push event fields from payload
        self.project_id = self.webhook_data.get("project_id", None)
        if self.project_id is None:
            self.project_id = self.webhook_data.get("project", {}).get("id")
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

        url = urljoin(
            f"{self.gitlab_url}/",
            f"api/v4/projects/{self.project_id}/repository/commits/{last_commit_id}/comments",
        )
        headers = {
            "Private-Token": self.gitlab_token,
            "Content-Type": "application/json",
        }
        data = {"note": message}
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Add comment to commit {last_commit_id}: {response.status_code}, {response.text}"
        )
        if response.status_code == 201:
            logger.info("Comment successfully added to push commit.")
        else:
            logger.error(f"Failed to add comment: {response.status_code}")
            logger.error(response.text)

    def __repository_commits(
        self,
        ref_name: str = "",
        since: str = "",
        until: str = "",
        pre_page: int = 100,
        page: int = 1,
    ):
        # Fetch repository commits
        url = f"{urljoin(f'{self.gitlab_url}/', f'api/v4/projects/{self.project_id}/repository/commits')}?ref_name={ref_name}&since={since}&until={until}&per_page={pre_page}&page={page}"
        headers = {"Private-Token": self.gitlab_token}
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Get commits response from GitLab for repository_commits: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to get commits for ref {ref_name}: {response.status_code}, {response.text}"
            )
            return []

    def repository_compare(self, before: str, after: str):
        # Compare two commits
        url = f"{urljoin(f'{self.gitlab_url}/', f'api/v4/projects/{self.project_id}/repository/compare')}?from={before}&to={after}"
        headers = {"Private-Token": self.gitlab_token}
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Get changes response from GitLab for repository_compare: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
            return response.json().get("diffs", [])
        else:
            logger.warning(
                f"Failed to get changes for repository_compare: {response.status_code}, {response.text}"
            )
            return []

    def get_commit_diff(self, commit_sha: str):
        """Fetch diff for a single commit"""
        url = f"{urljoin(f'{self.gitlab_url}/', f'api/v4/projects/{self.project_id}/repository/commits/{commit_sha}/diff')}"
        headers = {"Private-Token": self.gitlab_token}
        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        logger.debug(
            f"Get commit diff response from GitLab: {response.status_code}, {response.text}, URL: {url}"
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to get commit diff for {commit_sha}: {response.status_code}, {response.text}"
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

        before = self.webhook_data.get("before", "")
        after = self.webhook_data.get("after", "")

        if not before or not after:
            logger.warning("Missing before or after commit SHA in webhook data.")
            return []

        if after.startswith("0000000"):
            # Branch deletion — skip
            logger.info("Branch deletion detected, no changes to review.")
            return []

        if before.startswith("0000000"):
            # Branch creation — use single commit diff API
            logger.info("New branch creation detected, using commit diff API.")
            if self.commit_list:
                # Fetch latest commit diff
                latest_commit_id = after
                return self.get_commit_diff(latest_commit_id)
            else:
                return []
        else:
            # Normal push — use compare API
            logger.info(f"Comparing commits from {before} to {after}")
            return self.repository_compare(before, after)
