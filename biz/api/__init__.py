import os
from pathlib import Path

from flask import Flask

# Global config
push_review_enabled = os.environ.get("PUSH_REVIEW_ENABLED", "0") == "1"

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"

# Create Flask app. In production, Flask serves both API and React static assets.
api_app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIST_DIR),
    static_url_path="",
)


def init_app(app):
    """
    Initialize the app and register all routes.
    """
    from biz.api.routes import register_routes

    register_routes(app)
