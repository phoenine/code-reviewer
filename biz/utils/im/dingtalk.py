import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import requests

from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


class DingTalkNotifier:
    def __init__(self, webhook_url=None):
        self.enabled = os.environ.get("DINGTALK_ENABLED", "0") == "1"
        # Default: unsigned webhook; overwritten by signed URL if signing is enabled
        self.default_webhook_url = webhook_url or os.environ.get("DINGTALK_WEBHOOK_URL")
        if os.environ.get("DINGTALK_SECRET_ENABLED", "0") == "1":
            try:
                timestamp = str(round(time.time() * 1000))
                secret = os.environ.get("DINGTALK_SECRET")
                secret_enc = secret.encode("utf-8")
                string_to_sign = "{}\n{}".format(timestamp, secret)
                string_to_sign_enc = string_to_sign.encode("utf-8")
                hmac_code = hmac.new(
                    secret_enc, string_to_sign_enc, digestmod=hashlib.sha256
                ).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                self.default_webhook_url = "{}&timestamp={}&sign={}".format(
                    os.environ.get("DINGTALK_WEBHOOK_URL"), timestamp, sign
                )
                logger.info("DingTalk signed URL: %s", self.default_webhook_url)
            except Exception as e:
                logger.error("DingTalk robot signing failed: %s", e)

    def _get_webhook_url(self, project_name=None, url_slug=None):
        """
        Get the project-specific Webhook URL
        :param project_name: Project name
        :param url_slug: Slug converted from the GitLab project URL
        :return: Webhook URL
        :raises ValueError: If no Webhook URL is found
        """
        # No project_name: return default webhook URL
        if not project_name:
            if self.default_webhook_url:
                return self.default_webhook_url
            else:
                raise ValueError("No project name provided and no default DingTalk Webhook URL set.")

        # Build target key
        target_key_project = f"DINGTALK_WEBHOOK_URL_{project_name.upper()}"
        target_key_url_slug = f"DINGTALK_WEBHOOK_URL_{url_slug.upper()}"

        # Iterate env vars
        for env_key, env_value in os.environ.items():
            env_key_upper = env_key.upper()
            if env_key_upper == target_key_project:
                return env_value  # Found project match, return its URL
            if env_key_upper == target_key_url_slug:
                return env_value  # Found GitLab URL match, return its URL

        # No match found: fall back to default webhook URL
        if self.default_webhook_url:
            return self.default_webhook_url

        # No match and no default: raise error
        raise ValueError(
            f"No DingTalk Webhook URL found for project '{project_name}', and no default Webhook URL is set."
        )

    def send_message(
        self,
        content: str,
        msg_type="text",
        title="Notification",
        is_at_all=False,
        project_name=None,
        url_slug=None,
    ):
        if not self.enabled:
            logger.info("DingTalk push is not enabled")
            return

        try:
            post_url = self._get_webhook_url(
                project_name=project_name, url_slug=url_slug
            )
            headers = {"Content-Type": "application/json", "Charset": "UTF-8"}
            if msg_type == "markdown":
                message = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,  # Customize as needed
                        "text": content,
                    },
                    "at": {"isAtAll": is_at_all},
                }
            else:
                message = {
                    "msgtype": "text",
                    "text": {"content": content},
                    "at": {"isAtAll": is_at_all},
                }
            response = requests.post(
                url=post_url,
                data=json.dumps(message),
                headers=headers,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            response_data = response.json()
            if response_data.get("errmsg") == "ok":
                logger.info(f"DingTalk message sent successfully! webhook_url:{post_url}")
            else:
                logger.error(
                    f"DingTalk message sending failed! webhook_url:{post_url}, errmsg:{response_data.get('errmsg')}"
                )
        except Exception as e:
            logger.error("DingTalk message sending failed! %s", e)
