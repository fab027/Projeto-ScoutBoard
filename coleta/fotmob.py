"""Fotos de jogadores e escudos direto do CDN do FotMob, pelo id: nenhuma consulta na hora da página.

O endereço da imagem depende só do id do FotMob. A ligação entre os ids da base (WhoScored) e os
do FotMob fica em dados/fotmob_ids.json, um arquivo de texto versionado: o site o lê ao subir e
nunca consulta nada para achar uma foto.

A ligação vem do site Brasileirão em Dados (brasileiraoemdados.com.br, de Ioannis Canteiro /
DataFutebol), que usa os mesmos ids do WhoScored e publica o id do FotMob de cada jogador e time
da temporada em andamento em data/core.json. Uma requisição atualiza tudo:

    python -m coleta.fotmob

Os ids já conhecidos são mantidos: quem saiu do campeonato continua com foto.
"""
import argparse
import json
from pathlib import Path

import requests

from config import DADOS, USER_AGENT

ORIGEM = "https://brasileiraoemdados.com.br/data/core.json"
ARQUIVO = DADOS / "fotmob_ids.json"
FOTO = "https://images.fotmob.com/image_resources/playerimages/{id}.png"
ESCUDO = "https://images.fotmob.com/image_resources/logo/teamlogo/{id}.png"


def ler_ids(dados: dict) -> dict:
    """{"jogadores": {player_id: id do FotMob}, "times": {team_id: id do FotMob}} do core.json."""
    def ids(itens: list) -> dict[int, int]:
        return {int(item["id"]): int(item["fm"]) for item in itens if item.get("id") and item.get("fm")}

    saida = {"jogadores": ids(dados.get("players", [])), "times": ids(dados.get("teams", []))}
    if not saida["jogadores"] or not saida["times"]:
        raise ValueError("O arquivo de origem não trouxe ids do FotMob")
    return saida


def atualizar(arquivo: Path = ARQUIVO, buscar=None) -> dict:
    """Junta os ids publicados hoje aos já guardados e grava o arquivo. Devolve quantos há de cada."""
    buscar = buscar or (lambda: requests.get(ORIGEM, headers={"User-Agent": USER_AGENT}, timeout=30).json())
    novos = ler_ids(buscar())
    guardado = carregar(arquivo)
    juntos = {chave: dict(sorted({**guardado[chave], **novos[chave]}.items())) for chave in ("jogadores", "times")}
    arquivo.write_text(json.dumps({"origem": ORIGEM, **juntos}, ensure_ascii=False, indent=0), encoding="utf-8")
    return {chave: len(valor) for chave, valor in juntos.items()}


def carregar(arquivo: Path = ARQUIVO) -> dict:
    """Ids guardados, com chaves inteiras; vazio se o arquivo ainda não existe."""
    if not arquivo.exists():
        return {"jogadores": {}, "times": {}}
    lido = json.loads(arquivo.read_text(encoding="utf-8"))
    return {chave: {int(k): int(v) for k, v in lido.get(chave, {}).items()} for chave in ("jogadores", "times")}


class Imagens:
    """Endereços de fotos e escudos no CDN do FotMob para os ids da base; só consulta a memória."""

    def __init__(self, ids: dict | None = None):
        ids = carregar() if ids is None else ids
        self.jogadores, self.times = ids["jogadores"], ids["times"]

    def foto(self, player_id: int) -> str | None:
        fotmob_id = self.jogadores.get(int(player_id))
        return FOTO.format(id=fotmob_id) if fotmob_id else None

    def escudo(self, team_id: int) -> str | None:
        fotmob_id = self.times.get(int(team_id))
        return ESCUDO.format(id=fotmob_id) if fotmob_id else None


if __name__ == "__main__":
    argparse.ArgumentParser(description="Atualiza dados/fotmob_ids.json (uma requisição).").parse_args()
    print(json.dumps(atualizar(), ensure_ascii=False))
