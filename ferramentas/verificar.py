"""Verifica se o ambiente, os testes e o site estão funcionando.

Uso, a partir da raiz do projeto:
    venv\\Scripts\\python.exe ferramentas\\verificar.py

Roda com o mesmo Python que o chamou, então não depende de ativar o venv
nem da sintaxe do terminal (PowerShell, cmd ou Git Bash).
"""
import importlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PORTA = 5055
MODULOS = ["pandas", "pyarrow", "flask", "flask_sqlalchemy", "pytest", "socceraction", "requests"]


def passo(titulo):
    print(f"\n== {titulo}")


def checar_dependencias():
    print("Python usado:", sys.executable)
    faltando = []
    for modulo in MODULOS:
        try:
            importlib.import_module(modulo)
            print("ok   ", modulo)
        except Exception as erro:
            print("FALTA", modulo, "->", erro)
            faltando.append(modulo)
    if faltando:
        print("\nInstale as dependencias com:")
        print("    python -m pip install -r requirements-dev.txt")
        print("(com o Python do venv: venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt)")
        return False
    return True


def rodar_testes():
    resultado = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ)
    return resultado.returncode == 0


def esperar_servidor(url, limite_segundos=40):
    fim = time.time() + limite_segundos
    while time.time() < fim:
        try:
            with urllib.request.urlopen(url, timeout=3) as resposta:
                return resposta.status
        except (urllib.error.URLError, ConnectionError):
            time.sleep(1)
    return None


def checar_servidor():
    processo = subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "app", "run", "--port", str(PORTA)],
        cwd=RAIZ,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{PORTA}"
        status_pagina = esperar_servidor(base + "/")
        print("Pagina inicial:", status_pagina, "(esperado 200)")
        if status_pagina != 200:
            return False
        with urllib.request.urlopen(base + "/api/painel?temporada=2025", timeout=60) as resposta:
            print("API /api/painel?temporada=2025:", resposta.status, "(esperado 200)")
            return resposta.status == 200
    except (urllib.error.URLError, ConnectionError, OSError) as erro:
        print("Falha ao consultar o servidor:", erro)
        return False
    finally:
        processo.terminate()
        processo.wait(timeout=10)


def main():
    passo("1. Dependencias")
    if not checar_dependencias():
        return 1

    passo("2. Testes automatizados")
    if not rodar_testes():
        print("\nHá testes falhando. Veja a saida acima.")
        return 1

    passo(f"3. Site em http://127.0.0.1:{PORTA}")
    if not checar_servidor():
        print("\nO site não respondeu como esperado.")
        return 1

    print("\nTudo certo. Para atualizar os técnicos e abrir o site, rode:")
    print("    python iniciar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
