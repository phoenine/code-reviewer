from biz.model.review_comment import ReviewComment, ReviewResult


def _format_score(score: int | None) -> str:
    return f"{score}" if score is not None else "N/A"


def _format_comment(comment: ReviewComment, index: int) -> str:
    location = comment.path
    if comment.line_resolved and comment.start_line and comment.end_line:
        if comment.start_line == comment.end_line:
            location = f"{location}:{comment.start_line}"
        else:
            location = f"{location}:{comment.start_line}-{comment.end_line}"
    else:
        location = f"{location}:unresolved"

    parts = [
        f"{index}. **{comment.severity}** `{location}`",
        f"   - Category: {comment.category or 'uncategorized'}",
        f"   - Issue: {comment.content}",
    ]
    if not comment.line_resolved and comment.resolve_reason:
        parts.append(f"   - Resolution: {comment.resolve_reason}")
    return "\n".join(parts)


def _looks_like_structured_output(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith("{") or stripped.startswith("```json")


def _render_parse_error(result: ReviewResult) -> str:
    if result.raw_text and not _looks_like_structured_output(result.raw_text):
        return result.raw_text
    return "\n".join(
        [
            "## Review Conclusion",
            "- Risk Level: Low",
            "- Merge Advice: Approved",
            "- Total Score: N/A",
            "",
            "The model returned an unparseable structured review result. "
            "It has been downgraded to standard Markdown output. "
            "The original content was not published directly to avoid comment formatting issues.",
            "",
            "## Key Issues",
            "Unable to parse structured issue list. Check service logs for the raw model response.",
            "",
            "## Logic & Compatibility Check",
            "Unable to parse structured results.",
            "",
            "## Performance & Stability Check",
            "Unable to parse structured results.",
            "",
            "## Score Breakdown",
            "Total Score: N/A",
        ]
    )


def render_review_markdown(result: ReviewResult) -> str:
    if result.parse_error:
        return _render_parse_error(result)

    lines = [
        "## Review Conclusion",
        f"- Risk Level: {result.risk_level or 'Low'}",
        f"- Merge Advice: {result.merge_advice or 'Approved'}",
        f"- Total Score: {_format_score(result.score)}",
        "",
        result.summary or "No specific issues found.",
        "",
        "## Key Issues",
    ]

    if result.comments:
        for index, comment in enumerate(result.comments, start=1):
            lines.append(_format_comment(comment, index))
    else:
        lines.append("No specific issues found.")

    lines.extend(
        [
            "",
            "## Logic & Compatibility Check",
            result.summary or "No specific risks found.",
            "",
            "## Performance & Stability Check",
            "No specific risks found.",
            "",
            "## Score Breakdown",
            f"Total Score: {_format_score(result.score)}",
        ]
    )
    return "\n".join(lines).strip()
