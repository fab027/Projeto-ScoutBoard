"""Aplicação para o comando `flask --app app ...` (ex.: `flask --app app importar-brutos`)."""
from sb_web import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
