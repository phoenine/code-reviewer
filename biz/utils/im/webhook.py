import os
from biz.utils.log import logger
import requests

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


class ExtraWebhookNotifier:
    def __init__(self, webhook_url=None):
        """
        Initialize ExtraWebhook notifier
        :param webhook_url: Custom webhook URL
        """
        self.default_webhook_url = webhook_url or os.environ.get(
            "EXTRA_WEBHOOK_URL", ""
        )
        self.enabled = os.environ.get("EXTRA_WEBHOOK_ENABLED", "0") == "1"

    def send_message(self, system_data: dict, webhook_data: dict):
        """
        Send extra custom webhook message
        :param system_data: System message content
        :param webhook_data: Raw push/merge event data from GitHub or GitLab
        """
        if not self.enabled:
            logger.info("ExtraWebhook not enabled")
            return

        try:
            data = {"ai_codereview_data": system_data, "webhook_data": webhook_data}
            response = requests.post(
                url=self.default_webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                logger.error(
                    f"ExtraWebhook send failed! webhook_url:{self.default_webhook_url}, error_msg:{response.text}"
                )
                return

        except Exception as e:
            logger.error("ExtraWebhook send failed! %s", e)
