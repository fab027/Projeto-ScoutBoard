"""Caminhos e constantes compartilhados pelo servidor, pela coleta e pelos testes."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent

# Variáveis do arquivo .env (modelo em .env.example); as que já estão no ambiente têm prioridade.
load_dotenv(RAIZ / ".env")

DADOS = RAIZ / "dados"
DADOS_BRUTOS = DADOS / "brutos"
METRICAS = DADOS / "metricas_jogador_jogo.parquet"
TREINADORES = DADOS / "treinadores.parquet"
TREINADORES_STATUS = DADOS / "treinadores_status.json"
MAPEAMENTO_TIMES = DADOS / "treinadores_times.csv"

# Cache em texto das fontes externas (CBF, ESPN, TheSportsDB, Wikimedia Commons): tabelas, elencos, jogos e
# endereços de escudos e fotos. Imagens nunca são gravadas.
CACHE_FONTES = DADOS / "cache"

# Quem acessa a Wikimedia (Wikipédia, Wikidata, Commons) sem contato no User-Agent fica limitado a
# 10 requisições por minuto; com e-mail ou endereço do projeto em SCOUTBOARD_CONTATO, a 200.
CONTATO = os.environ.get("SCOUTBOARD_CONTATO", "").strip()

# Fotos que custam uma requisição por jogador na hora da página (CBF, cerca de 0,6 s cada e em fila,
# e TheSportsDB, que trava depois de umas 10 buscas). Desligadas por padrão: quem não tem foto pelo
# id do FotMob nem no Commons aparece com as iniciais. SCOUTBOARD_FOTOS_LENTAS=1 liga de volta.
FOTOS_LENTAS = os.environ.get("SCOUTBOARD_FOTOS_LENTAS", "") == "1"
USER_AGENT = f"ScoutBoard/0.2 (projeto academico{'; ' + CONTATO if CONTATO else ''})"
