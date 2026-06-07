import requests
import os
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


class FeishuNotifier:
    def __init__(self, webhook_url=None):
        """
        Initialize Feishu notifier
        :param webhook_url: Feishu robot webhook URL
        """
        self.default_webhook_url = webhook_url or os.environ.get(
            "FEISHU_WEBHOOK_URL", ""
        )
        self.enabled = os.environ.get("FEISHU_ENABLED", "0") == "1"

    def _get_webhook_url(self, project_name=None, url_slug=None):
        """
        Get the project-specific Webhook URL
        :param project_name: Project name
        :return: Webhook URL
        :raises ValueError: If no Webhook URL is found
        """
        # No project_name: return default webhook URL
        if not project_name:
            if self.default_webhook_url:
                return self.default_webhook_url
            else:
                raise ValueError("No project name provided and no default Feishu Webhook URL set.")

        # Build target key
        target_key_project = f"FEISHU_WEBHOOK_URL_{project_name.upper()}"
        target_key_url_slug = f"FEISHU_WEBHOOK_URL_{url_slug.upper()}"

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
            f"No Feishu Webhook URL found for project '{project_name}', and no default Webhook URL is set."
        )

    def send_message(
        self,
        content,
        msg_type="text",
        title=None,
        is_at_all=False,
        project_name=None,
        url_slug=None,
    ):
        """
        Send Feishu message
        :param content: Message content
        :param msg_type: Message type, supports text and markdown
        :param title: Message title (used for markdown type)
        :param is_at_all: Whether to @everyone
        :param project_name: Project name
        """
        if not self.enabled:
            logger.info("Feishu push is not enabled")
            return

        try:
            post_url = self._get_webhook_url(
                project_name=project_name, url_slug=url_slug
            )
            if msg_type == "markdown":
                data = {
                    "msg_type": "interactive",
                    "card": {
                        "schema": "2.0",
                        "config": {
                            "update_multi": True,
                            "style": {
                                "text_size": {
                                    "normal_v2": {
                                        "default": "normal",
                                        "pc": "normal",
                                        "mobile": "heading",
                                    }
                                }
                            },
                        },
                        "body": {
                            "direction": "vertical",
                            "padding": "12px 12px 12px 12px",
                            "elements": [
                                {
                                    "tag": "markdown",
                                    "content": content,
                                    "text_align": "left",
                                    "text_size": "normal_v2",
                                    "margin": "0px 0px 0px 0px",
                                }
                            ],
                        },
                        "header": {
                            "title": {"tag": "plain_text", "content": title},
                            "template": "blue",
                            "padding": "12px 12px 12px 12px",
                        },
                    },
                }
            else:
                data = {
                    "msg_type": "text",
                    "content": {"text": content},
                }

            response = requests.post(
                url=post_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                logger.error(
                    f"Feishu message sending failed! webhook_url:{post_url}, error_msg:{response.text}"
                )
                return

            result = response.json()
            if result.get("msg") != "success":
                logger.error(
                    f"Failed to send Feishu message! webhook_url:{post_url}, errmsg:{result}"
                )
            else:
                logger.info(f"Feishu message sent successfully! webhook_url:{post_url}")

        except Exception as e:
            logger.error("Feishu message sending failed! %s", e)
