from blinker import Signal

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.service.review_service import ReviewService
from biz.utils.im import notifier
from biz.utils.log import logger

# Define global event manager (event signals)
event_manager = {
    "merge_request_reviewed": Signal(),
    "push_reviewed": Signal(),
}


# Define event handler
def on_merge_request_reviewed(mr_review_entity: MergeRequestReviewEntity):
    # Send IM notification
    im_msg = f"""
### 🔀 {mr_review_entity.project_name}: Merge Request

#### Merge Request Info:
- **Author:** {mr_review_entity.author}

- **Source Branch**: {mr_review_entity.source_branch}
- **Target Branch**: {mr_review_entity.target_branch}
- **Updated**: {mr_review_entity.updated_at}
- **Commit Message:** {mr_review_entity.commit_messages}

- [View MR Details]({mr_review_entity.url})

- **AI Review Result:** 

{mr_review_entity.review_result}
    """
    notifier.send_notification(
        content=im_msg,
        msg_type="markdown",
        title="Merge Request Review",
        project_name=mr_review_entity.project_name,
        url_slug=mr_review_entity.url_slug,
        webhook_data=mr_review_entity.webhook_data,
    )

    # Save to database
    if not ReviewService().insert_mr_review_log(mr_review_entity):
        logger.error(
            "Failed to persist merge request review log: project=%s source=%s target=%s",
            mr_review_entity.project_name,
            mr_review_entity.source_branch,
            mr_review_entity.target_branch,
        )


def on_push_reviewed(entity: PushReviewEntity):
    # Send IM notification
    im_msg = f"### 🚀 {entity.project_name}: Push\n\n"
    im_msg += "#### Commits:\n"

    for commit in entity.commits:
        message = commit.get("message", "").strip()
        author = commit.get("author", "Unknown Author")
        timestamp = commit.get("timestamp", "")
        url = commit.get("url", "#")
        im_msg += (
            f"- **Commit Message**: {message}\n"
            f"- **Author**: {author}\n"
            f"- **Time**: {timestamp}\n"
            f"- [View Commit]({url})\n\n"
        )

    if entity.review_result:
        im_msg += f"#### AI Review Result: \n {entity.review_result}\n\n"
    notifier.send_notification(
        content=im_msg,
        msg_type="markdown",
        title=f"{entity.project_name} Push Event",
        project_name=entity.project_name,
        url_slug=entity.url_slug,
        webhook_data=entity.webhook_data,
    )

    # Save to database
    if not ReviewService().insert_push_review_log(entity):
        logger.error(
            "Failed to persist push review log: project=%s branch=%s",
            entity.project_name,
            entity.branch,
        )


# Connect handlers to event signals
event_manager["merge_request_reviewed"].connect(on_merge_request_reviewed)
event_manager["push_reviewed"].connect(on_push_reviewed)
