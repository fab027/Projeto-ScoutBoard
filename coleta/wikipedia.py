"""Leitura do infobox de clubes na Wikipédia em português (API oficial do MediaWiki).

Usado como fonte de reserva do técnico atual, quando o Wikidata não tem um técnico
atual para o clube.

Os campos são lidos do wikitexto do infobox. Se o modelo do infobox mudar,
as expressões abaixo precisam ser ajustadas (o teste de fixture acusa isso).
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from config import USER_AGENT

API = "https://pt.wikipedia.org/w/api.php"
TENTATIVAS = 6


def _consultar(parametros: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode({**parametros, 'format': 'json'})}"
    for tentativa in range(TENTATIVAS):
        try:
            requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(requisicao, timeout=60) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            if erro.code not in (429, 503) or tentativa == TENTATIVAS - 1:
                raise
        except urllib.error.URLError:
            if tentativa == TENTATIVAS - 1:
                raise
        time.sleep(15 * (tentativa + 1))
    raise RuntimeError("Falha ao consultar a Wikipédia")


def wikitexto(titulo: str) -> str | None:
    """Wikitexto da página (seguindo redirecionamentos), ou None se a página não existir."""
    resposta = _consultar({"action": "parse", "page": titulo, "prop": "wikitext", "redirects": "1"})
    if "error" in resposta:
        return None
    return resposta["parse"]["wikitext"]["*"]


def campo(texto: str, nome: str) -> list[str]:
    """Valores de todas as linhas `| nome = valor` do infobox."""
    padrao = r"^\s*\|\s*" + re.escape(nome) + r"\s*=([^\n]*)"
    return [m.group(1).strip() for m in re.finditer(padrao, texto, re.M | re.I)]


def limpar_nome(valor: str) -> str:
    """Remove notas de rodapé, modelos e links do wikitexto, ficando com o texto visível."""
    limpo = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", valor, flags=re.S)
    limpo = re.sub(r"\{\{[^{}]*\}\}", "", limpo)
    limpo = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", limpo)
    limpo = re.sub(r"<[^>]+>", "", limpo)
    return " ".join(limpo.split())


def tecnico(texto: str) -> str | None:
    valores = campo(texto, "treinador")
    if not valores:
        return None
    return limpar_nome(valores[0]) or None
