import os
import re
import time
from urllib.parse import quote, urljoin
import fnmatch
import requests

from biz.diff.filter import filter_diffs
from biz.diff.parser import parse_changes
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


def _get_repository_file_content(
    gitlab_url: str, project_id: int | str | None, gitlab_token: str, path: str, ref: str
) -> str | None:
    if not project_id or not path or not ref:
        return None

    encoded_path = quote(path, safe="")
    url = urljoin(
        f"{gitlab_url}/",
        f"api/v4/projects/{project_id}/repository/files/{encoded_path}/raw",
    )
    headers = {"Private-Token": gitlab_token}
    response = requests.get(
        url,
        headers=headers,
        params={"ref": ref},
        verify=False,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    logger.debug(
        "Get file content from GitLab: %s, URL: %s, path: %s, ref: %s",
        response.status_code,
        url,
        path,
        ref,
    )
    if response.status_code == 200:
        return response.text

    logger.warning(
        "Failed to get file content from GitLab: %s, %s, path=%s, ref=%s",
        response.status_code,
        response.text,
        path,
        ref,
    )
    return None


def filter_changes(changes: list):
    """Filter changes, delegating to the structured diff pipeline"""
    return filter_diffs(parse_changes(changes, source="gitlab"))


def slugify_url(original_url: str) -> str:
    """
    Convert a URL to a file-name-safe slug. Non-alphanumeric chars become underscores.
    Example:
    slugify_url("http://example.com/path/to/repo/") => example_com_path_to_repo
    slugify_url("https://gitlab.com/user/repo.git") => gitlab_com_user_repo_git
    """
    original_url = re.sub(r"^https?://", "", original_url)
    target = re.sub(r"[^a-zA-Z0-9]", "_", original_url)
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
        self.event_type = self.webhook_data.get("object_kind", None)
        if self.event_type == "merge_request":
            self.parse_merge_request_event()

    def parse_merge_request_event(self):
        merge_request = self.webhook_data.get("object_attributes", {})
        self.merge_request_iid = merge_request.get("iid")
        self.project_id = merge_request.get("target_project_id")
        self.action = merge_request.get("action")

    def get_merge_request_changes(self) -> list:
        if self.event_type != "merge_request":
            logger.warning(
                f"Invalid event type: {self.event_type}. Only 'merge_request' event is supported now."
            )
            return []

        max_retries = 3
        retry_delay = 10
        for attempt in range(max_retries):
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

            if response.status_code == 200:
                changes = response.json().get("changes", [])
                if changes:
                    return changes
                else:
                    logger.info(
                        f"Changes is empty, retrying in {retry_delay} seconds... "
                        f"(attempt {attempt + 1}/{max_retries}), URL: {url}"
                    )
                    time.sleep(retry_delay)
            else:
                logger.warning(
                    f"Failed to get changes from GitLab (URL: {url}): {response.status_code}, {response.text}"
                )
                return []

        logger.warning(f"Max retries ({max_retries}) reached. Changes is still empty.")
        return []

    def get_merge_request_commits(self) -> list:
        if self.event_type != "merge_request":
            return []

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
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to get commits: {response.status_code}, {response.text}"
            )
            return []

    def get_file_content(self, path: str, ref: str) -> str | None:
        return _get_repository_file_content(
            self.gitlab_url,
            self.project_id,
            self.gitlab_token,
            path,
            ref,
        )

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
        self.event_type = self.webhook_data.get("event_name") or self.webhook_data.get(
            "object_kind"
        )
        if self.event_type == "push":
            self.parse_push_event()

    def parse_push_event(self):
        self.project_id = self.webhook_data.get("project_id", None)
        if self.project_id is None:
            self.project_id = self.webhook_data.get("project", {}).get("id")
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

    def get_file_content(self, path: str, ref: str) -> str | None:
        return _get_repository_file_content(
            self.gitlab_url,
            self.project_id,
            self.gitlab_token,
            path,
            ref,
        )

    def __repository_commits(
        self,
        ref_name: str = "",
        since: str = "",
        until: str = "",
        pre_page: int = 100,
        page: int = 1,
    ):
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

        if not before or not after:
            logger.warning("Missing before or after commit SHA in webhook data.")
            return []

        if after.startswith("0000000"):
            logger.info("Branch deletion detected, no changes to review.")
            return []

        if before.startswith("0000000"):
            logger.info("New branch creation detected, using commit diff API.")
            if self.commit_list:
                latest_commit_id = after
                return self.get_commit_diff(latest_commit_id)
            else:
                return []
        else:
            logger.info(f"Comparing commits from {before} to {after}")
            return self.repository_compare(before, after)
