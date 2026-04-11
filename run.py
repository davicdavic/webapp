"""
RetroQuest Platform
Entry point for running the Flask application
"""
import os
from app import create_app

# Create the Flask application
app = create_app(os.environ.get('FLASK_ENV', 'development'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=app.config.get("DEBUG", False)
    )