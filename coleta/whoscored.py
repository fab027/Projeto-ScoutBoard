"""Eventos SPADL do Brasileirão pelo WhoScored (biblioteca soccerdata).

Substitui os antigos scripts dload_massa.py, extrator_ids.py, curativo.py e
config_ligas.py. Cada jogo é baixado isoladamente: a falha de um jogo na fonte
não derruba a temporada inteira, e os jogos perdidos são informados no final.

Uso (a partir da raiz do projeto):
    python -m coleta.whoscored configurar
    python -m coleta.whoscored temporada 2024
    python -m coleta.whoscored temporada 2020 --ids-arquivo ids_2020.txt --tolerante

--ids-arquivo é um texto com um game_id por linha; use-o quando o calendário do
soccerdata não funcionar (o read_schedule quebra com frequência).
--tolerante preenche campos que a Opta deixa de fora em alguns jogos. Use só
quando o parser falhar; ele também cria jogadores placeholder (player_id 0), que
processamento/metricas.py descarta.
"""
import argparse
import contextlib
import json
from pathlib import Path

import pandas as pd

from config import DADOS_BRUTOS

LIGA = "BRA-Brasileirao"
SLUGS_WHOSCORED = {
    "BRA-Brasileirao": "Brazil-Brasileirão",
    "SA-Libertadores": "South-America-Copa-Libertadores",
}


def pasta_configuracao() -> Path:
    """Pasta em que o soccerdata procura o league_dict.json."""
    return Path.home() / "soccerdata" / "config"


def configurar_ligas(pasta: Path | None = None) -> Path:
    """Grava as ligas do WhoScored preservando o que já existia no arquivo."""
    pasta = pasta or pasta_configuracao()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "league_dict.json"
    atual = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
    atual.setdefault("WhoScored", {}).update(SLUGS_WHOSCORED)
    arquivo.write_text(json.dumps(atual, indent=4, ensure_ascii=False), encoding="utf-8")
    return arquivo


def _tolerante(original):
    """Devolve um `assertget` que supre as chaves que a Opta deixa de fora às vezes."""

    def assertget(dicionario, chave):
        if chave not in dicionario:
            if chave == "expandedMinute":
                return dicionario.get("minute", 0)
            if chave == "period":
                return {"value": 1, "displayName": "FirstHalf"}
            if chave == "playerId":
                return 0
        return original(dicionario, chave)

    return assertget


@contextlib.contextmanager
def parser_tolerante():
    """Aplica o `assertget` tolerante só dentro do bloco e restaura o original ao sair."""
    from socceraction.data.opta.parsers import whoscored as opta_ws

    original = opta_ws.assertget
    opta_ws.assertget = _tolerante(original)
    try:
        yield
    finally:
        opta_ws.assertget = original


def baixar_temporada(
    temporada: str,
    ids_jogos: list[int] | None = None,
    tolerante: bool = False,
    pasta: Path = DADOS_BRUTOS,
) -> tuple[Path, list[tuple[int, str]]]:
    """Grava BRA-Brasileirao_<temporada>.parquet e devolve (arquivo, [(jogo, erro), ...])."""
    import soccerdata as sd

    ws = sd.WhoScored(leagues=LIGA, seasons=temporada, headless=False)
    if ids_jogos is None:
        ids_jogos = ws.read_schedule().reset_index()["game_id"].dropna().astype(int).tolist()
    if not ids_jogos:
        raise RuntimeError(f"Nenhum jogo encontrado para {temporada}")

    eventos, falhas = [], []
    with parser_tolerante() if tolerante else contextlib.nullcontext():
        for numero, jogo in enumerate(ids_jogos, 1):
            print(f"[{numero}/{len(ids_jogos)}] jogo {jogo}")
            try:
                eventos.append(ws.read_events(match_id=[jogo], output_fmt="spadl"))
            except Exception as erro:
                falhas.append((jogo, str(erro)))
                print(f"  falhou: {erro}")

    if not eventos:
        raise RuntimeError(f"Nenhum jogo de {temporada} pôde ser convertido para SPADL")
    tabela = pd.concat(eventos, ignore_index=True)
    tabela["player"] = tabela["player"].fillna("Desconhecido").astype(str)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"BRA-Brasileirao_{temporada}.parquet"
    tabela.to_parquet(destino, index=False)
    return destino, falhas


def _ler_ids(arquivo: str) -> list[int]:
    return [int(linha) for linha in Path(arquivo).read_text(encoding="utf-8").split() if linha.strip().isdigit()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extrai eventos SPADL do Brasileirão pelo WhoScored.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("configurar", help="grava as ligas do WhoScored para o soccerdata")
    temporada = comandos.add_parser("temporada", help="baixa e converte uma temporada")
    temporada.add_argument("ano")
    temporada.add_argument("--ids-arquivo", help="arquivo com um game_id por linha")
    temporada.add_argument("--tolerante", action="store_true", help="suprime campos ausentes da Opta")
    args = parser.parse_args(argv)

    if args.comando == "configurar":
        print(f"Ligas gravadas em {configurar_ligas()}")
        return 0
    ids = _ler_ids(args.ids_arquivo) if args.ids_arquivo else None
    destino, falhas = baixar_temporada(args.ano, ids, tolerante=args.tolerante)
    print(f"Temporada {args.ano} salva em {destino}")
    if falhas:
        print(f"{len(falhas)} jogo(s) não baixado(s): {[jogo for jogo, _ in falhas]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
