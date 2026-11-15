"""Entry point for hosting. The hosting service starts the app with:  gunicorn wsgi:app

On your own computer keep using start.bat or `python app.py`.
"""
from app import create_app

app = create_app()
