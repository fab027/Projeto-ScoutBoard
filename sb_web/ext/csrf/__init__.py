"""Proteção CSRF de todo POST do site (Flask-WTF); os templates usam `csrf_token()`."""
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


def init_app(app):
    csrf.init_app(app)
