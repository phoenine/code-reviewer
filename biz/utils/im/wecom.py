import json
import requests
import os
import re
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


class WeComNotifier:
    def __init__(self, webhook_url=None):
        """
        Initialize WeCom notifier
        :param webhook_url: WeCom robot webhook URL
        """
        self.default_webhook_url = webhook_url or os.environ.get(
            "WECOM_WEBHOOK_URL", ""
        )
        self.enabled = os.environ.get("WECOM_ENABLED", "0") == "1"

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
                raise ValueError("No project name provided and no default WeCom Webhook URL set.")

        # Build target key
        target_key_project = f"WECOM_WEBHOOK_URL_{project_name.upper()}"
        target_key_url_slug = f"WECOM_WEBHOOK_URL_{url_slug.upper()}"

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
            f"No WeCom Webhook URL found for project '{project_name}', and no default Webhook URL is set."
        )

    def format_markdown_content(self, content, title=None):
        """
        Format markdown content for WeCom compatibility
        """
        # Process title
        formatted_content = f"## {title}\n\n" if title else ""

        # Downgrade h5+ headings to h4
        content = re.sub(r"#{5,}\s", "#### ", content)

        # Process link format
        content = re.sub(r"\[(.*?)\]\((.*?)\)", r"[link]\2", content)

        # Strip HTML tags
        content = re.sub(r"<[^>]+>", "", content)

        formatted_content += content
        return formatted_content

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
        Send WeCom message
        :param content: Message content
        :param msg_type: Message type, supports text and markdown
        :param title: Message title (used for markdown type)
        :param is_at_all: Whether to @everyone
        :param project_name: Related project name
        :param url_slug: GitLab URL Slug
        """
        if not self.enabled:
            logger.info("WeCom push is not enabled")
            return

        try:
            post_url = self._get_webhook_url(
                project_name=project_name, url_slug=url_slug
            )
            # WeCom message length limits
            # text: max 2048 bytes
            # https://developer.work.weixin.qq.com/document/path/91770#%E6%96%87%E6%9C%AC%E7%B1%BB%E5%9E%8B
            # markdown: max 4096 bytes
            # https://developer.work.weixin.qq.com/document/path/91770#markdown%E7%B1%BB%E5%9E%8B
            MAX_CONTENT_BYTES = 4096 if msg_type == "markdown" else 2048

            # Check content length
            content_length = len(content.encode("utf-8"))

            if content_length <= MAX_CONTENT_BYTES:
                # Within limit, send directly
                data = self._build_message(content, title, msg_type, is_at_all)
                self._send_message(post_url, data)
            else:
                # Exceeds limit, split and send
                logger.warning(
                    f"Message content exceeds {MAX_CONTENT_BYTES} byte limit, will split and send. Total length: {content_length} bytes"
                )
                self._send_message_in_chunks(
                    content, title, post_url, msg_type, is_at_all, MAX_CONTENT_BYTES
                )

        except Exception as e:
            logger.error(f"WeCom message sending failed! {e}")

    def _send_message_in_chunks(
        self, content, title, post_url, msg_type, is_at_all, max_bytes
    ):
        """
        Split content into multiple parts and send separately
        """
        chunks = self._split_content(content, max_bytes)
        for i, chunk in enumerate(chunks):
            chunk_title = (
                f"{title} (Part {i + 1}/{len(chunks)})"
                if title
                else f"Message (Part {i + 1}/{len(chunks)})"
            )
            data = self._build_message(chunk, chunk_title, msg_type, is_at_all)
            self._send_message(
                post_url, data, chunk_num=i + 1, total_chunks=len(chunks)
            )

    def _split_content(self, content, max_bytes):
        """
        Split content into multiple parts by maximum byte length
        """
        chunks = []
        start_pos = 0
        content_bytes = content.encode("utf-8")
        content_length = len(content_bytes)

        while start_pos < content_length:
            candidate_end = min(start_pos + max_bytes, content_length)
            if candidate_end >= content_length:
                chunk = content_bytes[start_pos:].decode("utf-8", errors="ignore")
                chunks.append(chunk)
                break

            # Prefer line break split; fall back to hard cut to avoid infinite loops
            window = content_bytes[start_pos:candidate_end]
            newline_pos = window.rfind(b"\n")
            if newline_pos != -1:
                end_pos = start_pos + newline_pos + 1
            else:
                end_pos = candidate_end

            # Safety: ensure loop always makes progress
            if end_pos <= start_pos:
                end_pos = candidate_end

            chunk = content_bytes[start_pos:end_pos].decode("utf-8", errors="ignore")
            chunks.append(chunk)
            start_pos = end_pos

        return chunks

    def _send_message(self, post_url, data, chunk_num=None, total_chunks=None):
        """Send request and return response"""
        try:
            logger.debug(
                f"Sending WeCom message{' chunk' if chunk_num else ''} {chunk_num}/{total_chunks if chunk_num else ''}: url={post_url}, data={data}"
            )
            response = self._send_request(post_url, data)

            if response and response.get("errcode") != 0:
                logger.error(
                    f"WeCom message sending failed! webhook_url:{post_url}, errmsg:{response}"
                )
            else:
                logger.info(
                    f"WeCom message{' chunk' if chunk_num else ''} sent successfully! webhook_url:{post_url}"
                )

        except Exception as e:
            logger.error(f"WeCom message{' chunk' if chunk_num else ''} sending failed! {e}")

    def _send_request(self, url, data):
        """Send request and return JSON response"""
        try:
            response = requests.post(
                url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()  # Raise on HTTP error
            return response.json()
        except requests.RequestException as e:
            logger.error(f"WeCom message send request failed! url:{url}, error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WeCom response JSON! url:{url}, error: {e}")
        return None

    def _build_message(self, content, title, msg_type, is_at_all):
        """Build message"""
        if msg_type == "text":
            return self._build_text_message(content, is_at_all)
        elif msg_type == "markdown":
            return self._build_markdown_message(content, title)
        else:
            raise ValueError(f"Unsupported message type: {msg_type}")

    def _build_text_message(self, content, is_at_all):
        """Build text message"""
        return {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": ["@all"] if is_at_all else [],
            },
        }

    def _build_markdown_message(self, content, title):
        """Build Markdown message"""
        formatted_content = self.format_markdown_content(content, title)
        return {"msgtype": "markdown", "markdown": {"content": formatted_content}}
