import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("feishu_notify_relay")

app = FastAPI(title="Feishu Notify Relay", version="0.1.0")


def _load_json_file(path: str) -> Dict[str, str]:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = BASE_DIR / file_path
    if not file_path.exists():
        logger.warning("Mapping file not found: %s", file_path)
        return {}

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid mapping json object: {file_path}")
    return {str(k): str(v) for k, v in data.items()}


class FeishuClient:
    def __init__(self) -> None:
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.open_base_url = os.getenv("FEISHU_OPEN_BASE_URL", "https://open.feishu.cn")
        self._tenant_access_token: Optional[str] = None
        self._expires_at: float = 0

    def _get_tenant_access_token(self) -> str:
        if self._tenant_access_token and time.time() < self._expires_at:
            return self._tenant_access_token

        if not self.app_id or not self.app_secret:
            raise RuntimeError("FEISHU_APP_ID or FEISHU_APP_SECRET is empty")

        url = f"{self.open_base_url}/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(
            url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Get tenant_access_token failed: {resp.status_code} {resp.text}")

        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Get tenant_access_token failed: {result}")

        self._tenant_access_token = result["tenant_access_token"]
        expire = int(result.get("expire", 7200))
        self._expires_at = time.time() + max(expire - 120, 60)
        return self._tenant_access_token

    def send_interactive_card(self, open_id: str, title: str, markdown_content: str) -> Dict[str, Any]:
        token = self._get_tenant_access_token()
        url = f"{self.open_base_url}/open-apis/im/v1/messages?receive_id_type=open_id"

        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": markdown_content,
                    }
                ],
            },
        }

        payload = {
            "receive_id": open_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Send message failed: {resp.status_code} {resp.text}")

        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Send message failed: {result}")
        return result


def _detect_git_platform(webhook_data: Dict[str, Any]) -> str:
    if webhook_data.get("object_kind") in {"push", "merge_request"}:
        return "gitlab"
    if webhook_data.get("pull_request") is not None:
        return "github"
    if webhook_data.get("sender") is not None and webhook_data.get("repository") is not None:
        return "github"
    return "unknown"


def _extract_git_user(webhook_data: Dict[str, Any]) -> Optional[str]:
    platform = _detect_git_platform(webhook_data)
    if platform == "gitlab":
        object_kind = webhook_data.get("object_kind")
        if object_kind == "push":
            return webhook_data.get("user_username")
        if object_kind == "merge_request":
            return (webhook_data.get("user") or {}).get("username")

    if platform == "github":
        if webhook_data.get("pull_request"):
            pr_user = (webhook_data.get("pull_request") or {}).get("user") or {}
            return pr_user.get("login")
        sender = webhook_data.get("sender") or {}
        return sender.get("login")
    return None


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/notify")
async def notify(
    request: Request,
    x_relay_token: Optional[str] = Header(default=None, alias="X-Relay-Token"),
) -> Dict[str, Any]:
    relay_token = os.getenv("RELAY_TOKEN", "")
    if relay_token and x_relay_token != relay_token:
        raise HTTPException(status_code=401, detail="Invalid relay token")

    payload = await request.json()
    ai_data = payload.get("ai_codereview_data") or {}
    webhook_data = payload.get("webhook_data") or {}

    if not webhook_data:
        raise HTTPException(status_code=400, detail="webhook_data is required")

    git_user = _extract_git_user(webhook_data)
    if not git_user:
        raise HTTPException(status_code=400, detail="Cannot extract git user from webhook_data")

    git_user_to_name = _load_json_file(os.getenv("GIT_USER_TO_NAME_FILE", "config/git_user_to_name.json"))
    feishu_open_ids = _load_json_file(os.getenv("FEISHU_OPEN_IDS_FILE", "config/feishu_open_ids.json"))

    target_name = git_user_to_name.get(git_user, git_user)
    open_id = feishu_open_ids.get(target_name) or feishu_open_ids.get(git_user)
    if not open_id:
        raise HTTPException(
            status_code=404,
            detail=f"No Feishu open_id mapping found for git_user={git_user}, target_name={target_name}",
        )

    title = ai_data.get("title") or "Code Review Notification"
    content = ai_data.get("content") or "(empty content)"

    client = FeishuClient()
    result = client.send_interactive_card(open_id=open_id, title=title, markdown_content=content)
    logger.info("Delivered notification to open_id=%s git_user=%s", open_id, git_user)
    return {
        "ok": True,
        "git_user": git_user,
        "target_name": target_name,
        "open_id": open_id,
        "feishu_result": result,
    }
