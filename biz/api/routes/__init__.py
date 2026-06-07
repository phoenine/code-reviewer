from biz.api.routes import dashboard, home, webhook


def register_routes(app):
    """
    Register all routes to the Flask application.
    """
    app.register_blueprint(home.home_bp)
    app.register_blueprint(webhook.webhook_bp)
    app.register_blueprint(dashboard.dashboard_bp)
