from biz.utils.im.dingtalk import DingTalkNotifier
from biz.utils.im.feishu import FeishuNotifier
from biz.utils.im.webhook import ExtraWebhookNotifier
from biz.utils.im.wecom import WeComNotifier


def send_notification(content, msg_type="markdown", title="Notification", is_at_all=False, project_name=None, url_slug="", webhook_data=None):
    """
    Send notification to configured platforms (DingTalk, WeCom, Feishu)
    :param content: Message content
    :param msg_type: Message type, supports text and markdown
    :param title: Message title (used with markdown type)
    :param is_at_all: Whether to @everyone
    :param url_slug:
    :param webhook_data: Raw push/merge event data
    """
    # DingTalk notification
    dingtalk_notifier = DingTalkNotifier()
    dingtalk_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
    )

    # WeCom notification
    wecom_notifier = WeComNotifier()
    wecom_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
    )

    # Feishu notification
    feishu_notifier = FeishuNotifier()
    feishu_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
    )

    # Custom webhook notification
    extra_webhook_notifier = ExtraWebhookNotifier()
    system_data = {
        "content": content,
        "msg_type": msg_type,
        "title": title,
        "is_at_all": is_at_all,
        "project_name": project_name,
        "url_slug": url_slug,
    }
    if webhook_data is None:
        webhook_data = {}
    extra_webhook_notifier.send_message(
        system_data=system_data, webhook_data=webhook_data
    )
