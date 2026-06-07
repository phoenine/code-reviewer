import sqlite3
import time
from contextlib import closing
from typing import Callable

import pandas as pd

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.utils.log import logger


class ReviewService:
    DB_FILE = "data/data.db"
    DB_TIMEOUT_SECONDS = 10
    DB_BUSY_TIMEOUT_MS = 5000
    DB_WRITE_RETRIES = 3
    DB_WRITE_RETRY_DELAY_SECONDS = 0.3
    MR_DEDUP_INDEX_NAME = "ux_mr_review_log_last_commit"

    @staticmethod
    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(ReviewService.DB_FILE, timeout=ReviewService.DB_TIMEOUT_SECONDS)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"PRAGMA busy_timeout={ReviewService.DB_BUSY_TIMEOUT_MS};")
        return conn

    @staticmethod
    def _is_locked_error(error: Exception) -> bool:
        sqlite_errorcode = getattr(error, "sqlite_errorcode", None)
        busy_codes = {
            getattr(sqlite3, "SQLITE_BUSY", 5),
            getattr(sqlite3, "SQLITE_LOCKED", 6),
        }
        if sqlite_errorcode in busy_codes:
            return True
        error_text = str(error).lower()
        return "database is locked" in error_text or "sqlite_busy" in error_text

    @staticmethod
    def _execute_write_with_retry(
        operation_name: str,
        func: Callable[[], None],
        ignore_integrity_error: bool = False,
    ) -> bool:
        for attempt in range(1, ReviewService.DB_WRITE_RETRIES + 1):
            try:
                func()
                return True
            except sqlite3.IntegrityError as e:
                if ignore_integrity_error:
                    logger.info("%s ignored duplicate record: %s", operation_name, e)
                    return True
                logger.error("%s failed: %s", operation_name, e)
                return False
            except sqlite3.OperationalError as e:
                if ReviewService._is_locked_error(e) and attempt < ReviewService.DB_WRITE_RETRIES:
                    logger.warning(
                        "%s hit sqlite lock, retrying (%d/%d)",
                        operation_name,
                        attempt,
                        ReviewService.DB_WRITE_RETRIES,
                    )
                    time.sleep(ReviewService.DB_WRITE_RETRY_DELAY_SECONDS)
                    continue
                logger.error("%s failed: %s", operation_name, e)
                return False
            except sqlite3.DatabaseError as e:
                logger.error("%s failed: %s", operation_name, e)
                return False
        return False

    @staticmethod
    def init_db() -> bool:
        """Initialize database and table structures"""
        def _execute():
            with closing(ReviewService._connect()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                        CREATE TABLE IF NOT EXISTS mr_review_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            project_name TEXT,
                            author TEXT,
                            source_branch TEXT,
                            target_branch TEXT,
                            updated_at INTEGER,
                            commit_messages TEXT,
                            score INTEGER,
                            url TEXT,
                            review_result TEXT,
                            additions INTEGER DEFAULT 0,
                            deletions INTEGER DEFAULT 0,
                            last_commit_id TEXT DEFAULT ''
                        )
                    """
                )
                cursor.execute(
                    """
                        CREATE TABLE IF NOT EXISTS push_review_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            project_name TEXT,
                            author TEXT,
                            branch TEXT,
                            updated_at INTEGER,
                            commit_messages TEXT,
                            score INTEGER,
                            review_result TEXT,
                            additions INTEGER DEFAULT 0,
                            deletions INTEGER DEFAULT 0
                        )
                    """
                )
                # Ensure old tables have additions/deletions columns
                tables = ["mr_review_log", "push_review_log"]
                columns = ["additions", "deletions"]
                for table in tables:
                    cursor.execute(f"PRAGMA table_info({table})")
                    current_columns = [col[1] for col in cursor.fetchall()]
                    for column in columns:
                        if column not in current_columns:
                            cursor.execute(
                                f"ALTER TABLE {table} ADD COLUMN {column} INTEGER DEFAULT 0"
                            )

                # Add last_commit_id column to old mr_review_log table
                mr_columns = [
                    {"name": "last_commit_id", "type": "TEXT", "default": "''"}
                ]
                cursor.execute(f"PRAGMA table_info('mr_review_log')")
                current_columns = [col[1] for col in cursor.fetchall()]
                for column in mr_columns:
                    if column.get("name") not in current_columns:
                        cursor.execute(
                            f"ALTER TABLE mr_review_log ADD COLUMN {column.get('name')} {column.get('type')} "
                            f"DEFAULT {column.get('default')}"
                        )

                conn.commit()
                # Add time range index for common queries
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_push_review_log_updated_at ON "
                    "push_review_log (updated_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_mr_review_log_updated_at ON mr_review_log (updated_at);"
                )
                # Clean duplicate data before creating unique index (keep latest)
                conn.execute(
                    """
                    DELETE FROM mr_review_log
                    WHERE last_commit_id <> ''
                      AND id NOT IN (
                        SELECT MAX(id)
                        FROM mr_review_log
                        WHERE last_commit_id <> ''
                        GROUP BY project_name, source_branch, target_branch, last_commit_id
                      )
                    """
                )
                # Idempotent unique index (non-null last_commit_id only)
                conn.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS {ReviewService.MR_DEDUP_INDEX_NAME}
                    ON mr_review_log (project_name, source_branch, target_branch, last_commit_id)
                    WHERE last_commit_id <> ''
                    """
                )

        result = ReviewService._execute_write_with_retry("init_db", _execute)
        if not result:
            logger.error("Database initialization failed.")
        return result

    @staticmethod
    def insert_mr_review_log(entity: MergeRequestReviewEntity) -> bool:
        """Insert merge request review log"""
        def _execute():
            with closing(ReviewService._connect()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                                INSERT INTO mr_review_log (project_name,author, source_branch, target_branch, 
                                updated_at, commit_messages, score, url,review_result, additions, deletions, 
                                last_commit_id)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                    (
                        entity.project_name,
                        entity.author,
                        entity.source_branch,
                        entity.target_branch,
                        entity.updated_at,
                        entity.commit_messages,
                        entity.score,
                        entity.url,
                        entity.review_result,
                        entity.additions,
                        entity.deletions,
                        entity.last_commit_id,
                    ),
                )
                conn.commit()

        return ReviewService._execute_write_with_retry(
            "insert_mr_review_log",
            _execute,
            ignore_integrity_error=True,
        )

    @staticmethod
    def get_mr_review_logs(
        authors: list | None = None,
        project_names: list | None = None,
        updated_at_gte: int | None = None,
        updated_at_lte: int | None = None,
    ) -> pd.DataFrame:
        """Get merge request review logs matching criteria"""
        try:
            with closing(ReviewService._connect()) as conn:
                query = """
                            SELECT project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result, additions, deletions
                            FROM mr_review_log
                            WHERE 1=1
                            """
                params = []

                if authors:
                    placeholders = ",".join(["?"] * len(authors))
                    query += f" AND author IN ({placeholders})"
                    params.extend(authors)

                if project_names:
                    placeholders = ",".join(["?"] * len(project_names))
                    query += f" AND project_name IN ({placeholders})"
                    params.extend(project_names)

                if updated_at_gte is not None:
                    query += " AND updated_at >= ?"
                    params.append(updated_at_gte)

                if updated_at_lte is not None:
                    query += " AND updated_at <= ?"
                    params.append(updated_at_lte)
                query += " ORDER BY updated_at DESC"
                df = pd.read_sql_query(sql=query, con=conn, params=params)
            return df
        except sqlite3.DatabaseError as e:
            logger.error("Error retrieving review logs: %s", e)
            return pd.DataFrame()

    @staticmethod
    def check_mr_last_commit_id_exists(
        project_name: str, source_branch: str, target_branch: str, last_commit_id: str
    ) -> bool:
        """Check if a Merge Request with the same last_commit_id already exists for the given project"""
        try:
            with closing(ReviewService._connect()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM mr_review_log 
                    WHERE project_name = ? AND source_branch = ? AND target_branch = ? AND last_commit_id = ?
                """,
                    (project_name, source_branch, target_branch, last_commit_id),
                )
                count = cursor.fetchone()[0]
                return count > 0
        except sqlite3.DatabaseError as e:
            logger.error("Error checking last_commit_id: %s", e)
            return False

    @staticmethod
    def insert_push_review_log(entity: PushReviewEntity) -> bool:
        """Insert push review log"""
        def _execute():
            with closing(ReviewService._connect()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                                INSERT INTO push_review_log (project_name,author, branch, updated_at, commit_messages, score,review_result, additions, deletions)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                    (
                        entity.project_name,
                        entity.author,
                        entity.branch,
                        entity.updated_at,
                        entity.commit_messages,
                        entity.score,
                        entity.review_result,
                        entity.additions,
                        entity.deletions,
                    ),
                )
                conn.commit()

        return ReviewService._execute_write_with_retry("insert_push_review_log", _execute)

    @staticmethod
    def get_push_review_logs(
        authors: list | None = None,
        project_names: list | None = None,
        updated_at_gte: int | None = None,
        updated_at_lte: int | None = None,
    ) -> pd.DataFrame:
        """Get push review logs matching criteria"""
        try:
            with closing(ReviewService._connect()) as conn:
                # Base query
                query = """
                    SELECT project_name, author, branch, updated_at, commit_messages, score, review_result, additions, deletions
                    FROM push_review_log
                    WHERE 1=1
                """
                params = []

                # Conditionally add authors filter
                if authors:
                    placeholders = ",".join(["?"] * len(authors))
                    query += f" AND author IN ({placeholders})"
                    params.extend(authors)

                if project_names:
                    placeholders = ",".join(["?"] * len(project_names))
                    query += f" AND project_name IN ({placeholders})"
                    params.extend(project_names)

                # Conditionally add updated_at_gte filter
                if updated_at_gte is not None:
                    query += " AND updated_at >= ?"
                    params.append(updated_at_gte)

                # Conditionally add updated_at_lte filter
                if updated_at_lte is not None:
                    query += " AND updated_at <= ?"
                    params.append(updated_at_lte)

                # Sort by updated_at descending
                query += " ORDER BY updated_at DESC"

                # Execute query
                df = pd.read_sql_query(sql=query, con=conn, params=params)
                return df
        except sqlite3.DatabaseError as e:
            logger.error("Error retrieving push review logs: %s", e)
            return pd.DataFrame()
