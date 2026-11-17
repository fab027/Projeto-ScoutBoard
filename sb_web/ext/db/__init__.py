from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_app(app):
    db.init_app(app)

def register_models():
    import sb_web.campeonato.models
    import sb_web.analytics.models
    # Importado só para registrar o modelo no metadata antes de create_all.
    import sb_web.scout.models  # noqa: F401


def create_tables(app):
    """Cria as tabelas que ainda não existem (as páginas de observações leem o banco ao abrir)."""
    with app.app_context():
        db.create_all()
