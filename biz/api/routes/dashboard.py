from __future__ import annotations

from typing import Any

import pandas as pd
from flask import Blueprint, jsonify, request

from biz.service.review_service import ReviewService


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


def _parse_int(value: str | None, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_multi(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _safe_number(value: Any, default: int | float = 0) -> int | float:
    if value is None:
        return default
    if pd.isna(value):
        return default
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _records_from_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        records.append({key: None if pd.isna(value) else value for key, value in row.items()})
    return records


def _load_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    authors = _parse_multi(request.args.get("author"))
    project_names = _parse_multi(request.args.get("project_name"))
    updated_at_gte = _parse_int(request.args.get("start"))
    updated_at_lte = _parse_int(request.args.get("end"))

    mr_df = ReviewService.get_mr_review_logs(
        authors=authors,
        project_names=project_names,
        updated_at_gte=updated_at_gte,
        updated_at_lte=updated_at_lte,
    )
    push_df = ReviewService.get_push_review_logs(
        authors=authors,
        project_names=project_names,
        updated_at_gte=updated_at_gte,
        updated_at_lte=updated_at_lte,
    )
    return _normalize_mr_df(mr_df), _normalize_push_df(push_df)


def _normalize_mr_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "type",
                "project_name",
                "author",
                "source_branch",
                "target_branch",
                "branch",
                "updated_at",
                "commit_messages",
                "score",
                "url",
                "review_result",
                "additions",
                "deletions",
            ]
        )
    result = df.copy()
    result.insert(0, "type", "mr")
    result["branch"] = result["source_branch"].fillna("") + " → " + result["target_branch"].fillna("")
    return result


def _normalize_push_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "type",
                "project_name",
                "author",
                "source_branch",
                "target_branch",
                "branch",
                "updated_at",
                "commit_messages",
                "score",
                "url",
                "review_result",
                "additions",
                "deletions",
            ]
        )
    result = df.copy()
    result.insert(0, "type", "push")
    result["source_branch"] = None
    result["target_branch"] = None
    result["url"] = None
    return result


def _combined_reviews(mr_df: pd.DataFrame, push_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "type",
        "project_name",
        "author",
        "source_branch",
        "target_branch",
        "branch",
        "updated_at",
        "commit_messages",
        "score",
        "url",
        "review_result",
        "additions",
        "deletions",
    ]
    combined = pd.concat([mr_df[columns], push_df[columns]], ignore_index=True)
    if combined.empty:
        return combined
    return combined.sort_values(by="updated_at", ascending=False).reset_index(drop=True)


def _apply_keyword(df: pd.DataFrame, keyword: str | None) -> pd.DataFrame:
    if df.empty or not keyword:
        return df
    keyword = keyword.lower()
    searchable = ["project_name", "author", "branch", "commit_messages", "review_result"]
    mask = pd.Series(False, index=df.index)
    for column in searchable:
        mask = mask | df[column].fillna("").astype(str).str.lower().str.contains(keyword, regex=False)
    return df[mask]


def _compute_previous(
    previous: dict[str, Any] | None,
    *,
    current_total: int,
    current_score: float,
    current_projects: int,
    current_members: int,
) -> dict[str, Any] | None:
    if previous is None:
        return None
    prev_total = previous["total_reviews"]
    prev_score = previous["average_score"]
    prev_projects = previous["active_projects"]
    prev_members = previous["active_members"]
    return {
        "total_reviews": prev_total,
        "average_score": prev_score,
        "active_projects": prev_projects,
        "active_members": prev_members,
        "deltas": {
            "total_reviews_pct": round(
                ((current_total - prev_total) / prev_total * 100), 1
            ) if prev_total else 0,
            "average_score_diff": round(current_score - prev_score, 2),
            "active_projects_diff": current_projects - prev_projects,
            "active_members_diff": current_members - prev_members,
        },
    }


def _valid_scores(df: pd.DataFrame) -> pd.Series:
    """Return valid score column (exclude None/NaN/0)"""
    return df["score"].dropna().loc[lambda s: s > 0]


@dashboard_bp.get("/summary")
def summary():
    mr_df, push_df = _load_frames()
    combined = _combined_reviews(mr_df, push_df)
    valid_scores = _valid_scores(combined) if not combined.empty else pd.Series(dtype=float)
    current_score = round(float(valid_scores.mean()), 2) if not valid_scores.empty else 0.0
    
    # previous period score filtering
    prev_valid_scores: pd.Series | None = None
    prev_score_val = 0.0

    # --- previous period comparison ---
    start_ts = _parse_int(request.args.get("start"))
    end_ts = _parse_int(request.args.get("end"))
    previous = None
    if start_ts is not None and end_ts is not None:
        period_len = end_ts - start_ts
        prev_end = start_ts - 1
        prev_start = prev_end - period_len
        prev_mr = ReviewService.get_mr_review_logs(
            updated_at_gte=prev_start,
            updated_at_lte=prev_end,
        )
        prev_push = ReviewService.get_push_review_logs(
            updated_at_gte=prev_start,
            updated_at_lte=prev_end,
        )
        prev_combined = _combined_reviews(
            _normalize_mr_df(prev_mr),
            _normalize_push_df(prev_push),
        )
        if not prev_combined.empty:
            prev_valid = _valid_scores(prev_combined)
            prev_total = int(len(prev_combined))
            prev_score_val = round(float(prev_valid.mean()), 2) if not prev_valid.empty else 0.0
            prev_projects = int(prev_combined["project_name"].nunique())
            prev_members = int(prev_combined["author"].nunique())
            previous = {
                "total_reviews": prev_total,
                "average_score": prev_score_val,
                "active_projects": prev_projects,
                "active_members": prev_members,
            }
        else:
            previous = {
                "total_reviews": 0,
                "average_score": 0,
                "active_projects": 0,
                "active_members": 0,
            }

    if combined.empty:
        resp = {
            "total_reviews": 0,
            "average_score": 0,
            "active_projects": 0,
            "active_members": 0,
            "project_counts": [],
            "project_scores": [],
            "recent_reviews": [],
            "previous": _compute_previous(
                previous,
                current_total=0,
                current_score=0.0,
                current_projects=0,
                current_members=0,
            ),
        }
        return jsonify(resp)

    project_counts = (
        combined.groupby("project_name")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "project_name"], ascending=[False, True])
    )
    project_scores = (
        combined.groupby("project_name")["score"]
        .apply(lambda s: s.dropna().loc[lambda x: x > 0].mean() if not s.dropna().empty else 0.0)
        .reset_index(name="average_score")
        .sort_values(["average_score", "project_name"], ascending=[False, True])
    )
    project_scores["average_score"] = project_scores["average_score"].round(2)

    return jsonify(
        {
            "total_reviews": int(len(combined)),
            "average_score": current_score,
            "active_projects": int(combined["project_name"].nunique()),
            "active_members": int(combined["author"].nunique()),
            "project_counts": _records_from_df(project_counts),
            "project_scores": _records_from_df(project_scores),
            "recent_reviews": _records_from_df(combined.head(5)),
            "previous": _compute_previous(
                previous,
                current_total=int(len(combined)),
                current_score=current_score,
                current_projects=int(combined["project_name"].nunique()),
                current_members=int(combined["author"].nunique()),
            ),
        }
    )


@dashboard_bp.get("/reviews")
def reviews():
    mr_df, push_df = _load_frames()
    review_type = request.args.get("type", "all")
    if review_type == "mr":
        combined = mr_df
    elif review_type == "push":
        combined = push_df
    else:
        combined = _combined_reviews(mr_df, push_df)

    combined = _apply_keyword(combined, request.args.get("keyword"))
    if not combined.empty:
        combined = combined.sort_values(by="updated_at", ascending=False).reset_index(drop=True)

    page = max(_parse_int(request.args.get("page"), 1) or 1, 1)
    page_size = min(max(_parse_int(request.args.get("page_size"), 20) or 20, 1), 100)
    total = int(len(combined))
    start = (page - 1) * page_size
    end = start + page_size
    page_df = combined.iloc[start:end]

    return jsonify(
        {
            "items": _records_from_df(page_df),
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@dashboard_bp.get("/filter-options")
def filter_options():
    mr_df = _normalize_mr_df(ReviewService.get_mr_review_logs())
    push_df = _normalize_push_df(ReviewService.get_push_review_logs())
    combined = _combined_reviews(mr_df, push_df)
    if combined.empty:
        return jsonify({"authors": [], "project_names": []})
    authors = sorted(value for value in combined["author"].dropna().unique().tolist() if value)
    project_names = sorted(value for value in combined["project_name"].dropna().unique().tolist() if value)
    return jsonify({"authors": authors, "project_names": project_names})


@dashboard_bp.get("/members")
def members():
    mr_df, push_df = _load_frames()
    combined = _combined_reviews(mr_df, push_df)
    if combined.empty:
        return jsonify(
            {
                "items": [],
                "summary": {
                    "total_reviews": 0,
                    "team_average_score": 0,
                    "total_additions": 0,
                    "total_deletions": 0,
                    "active_members": 0,
                },
            }
        )

    grouped = (
        combined.groupby("author")
        .agg(
            review_count=("author", "size"),
            average_score=("score", lambda s: s.dropna().loc[lambda x: x > 0].mean() if not s.dropna().empty else 0.0),
            additions=("additions", "sum"),
            deletions=("deletions", "sum"),
            active_projects=("project_name", "nunique"),
        )
        .reset_index()
        .sort_values(["review_count", "author"], ascending=[False, True])
    )
    grouped["average_score"] = grouped["average_score"].round(2)

    team_valid_scores = _valid_scores(combined)
    team_avg = round(float(team_valid_scores.mean()), 2) if not team_valid_scores.empty else 0.0

    return jsonify(
        {
            "items": _records_from_df(grouped),
            "summary": {
                "total_reviews": int(len(combined)),
                "team_average_score": team_avg,
                "total_additions": int(_safe_number(combined["additions"].sum())),
                "total_deletions": int(_safe_number(combined["deletions"].sum())),
                "active_members": int(combined["author"].nunique()),
            },
        }
    )
