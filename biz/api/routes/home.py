from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_from_directory

home_bp = Blueprint("home", __name__)


@home_bp.route("/health")
def health():
    return jsonify({"status": "ok"})


@home_bp.route("/")
def home():
    return _send_react_app()


@home_bp.route("/<path:path>")
def spa_fallback(path: str):
    static_folder = current_app.static_folder
    if static_folder:
        target = Path(static_folder) / path
        if target.exists() and target.is_file():
            return send_from_directory(static_folder, path)
    return _send_react_app()


def _send_react_app():
    static_folder = current_app.static_folder
    if not static_folder:
        return """<h2>The code review api server is running.</h2>"""
    index_file = Path(static_folder) / "index.html"
    if not index_file.exists():
        return """<h2>The code review api server is running.</h2>"""
    return send_from_directory(static_folder, "index.html")
