"""
API service entry point
"""
from dotenv import load_dotenv

# Load env vars before any other imports
load_dotenv("conf/.env")

import os

from biz.api import api_app, init_app
from biz.service.review_service import ReviewService
from biz.utils.config_checker import check_config

# Initialize app and register routes
init_app(api_app)

if __name__ == '__main__':
    check_config()
    ReviewService.init_db()

    # Start Flask API server
    port = int(os.environ.get('SERVER_PORT', 5001))
    api_app.run(host='0.0.0.0', port=port)
