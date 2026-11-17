"""Campeonato Brasileiro Série A pelo site da CBF (cbf.com.br), lido do HTML das páginas.

O site é feito em Next.js: cada página traz os dados em JSON dentro de `self.__next_f.push(...)`.
Nenhuma imagem é gravada: escudos têm endereço próprio na CBF e a foto de um atleta vem
embutida (base64) na página dele, entregue pelo servidor do ScoutBoard sob demanda.

Páginas usadas (ano = temporada):
- /tabelas/campeonato-brasileiro/serie-a/{ano}: classificação e artilharia
- /times/campeonato-brasileiro/serie-a/{ano}/{id}: elenco e jogos do time
- /atletas/campeonato-brasileiro/serie-a/{ano}/{id}: foto do atleta

Tudo é lido sob demanda (ver Cache): a tabela de uma temporada só quando alguém a pede, a página
de um time só quando uma foto ou um recorte precisa dela. O texto lido fica em
dados/cache/cbf-{ano}.json; a temporada em andamento é conferida depois de VALIDADE_ABERTA
segundos, e as encerradas, nunca.
"""
import base64
import json
import re
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import certifi
import requests
from requests.adapters import HTTPAdapter

from config import CACHE_FONTES, USER_AGENT
from coleta.nomes import normalizar

BASE = "https://www.cbf.com.br/futebol-brasileiro"
CAMPEONATO = "campeonato-brasileiro/serie-a"
PRIMEIRA_TEMPORADA = 2019
TENTATIVAS = 3
CODIGOS_RETENTAVEIS = {429, 500, 502, 503, 504}
PARALELO = 2  # requisições ao mesmo tempo, somando todo o processo
INTERVALO = 0.5  # segundos entre o início de duas requisições: a CBF bloqueia rajadas
PAUSA_APOS_FALHA = 300  # bloqueios da CBF duram minutos (ou horas): nesse tempo, só as reservas
VALIDADE_ABERTA = 15 * 60
JOGOS_NA_TEMPORADA = 38

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
# Siglas que aparecem no nome oficial dos clubes, mas não no nome usado na base (ex.: "Cruzeiro Saf").
_SIGLAS = re.compile(r"\b(s\.?\s?a\.?\s?f\.?|fc|ec|af)\b")
_PARTICULAS = {"de", "da", "do", "dos", "das", "e"}
_UFS = {
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe",
    "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to",
}
# Nome da base -> nome da CBF, quando não há palavra em comum.
_APELIDOS_TIMES = {"cs alagoano": "csa"}


# ---------- Leitura das páginas ----------

def fluxo(html: str) -> str:
    """Texto dos dados do Next.js, juntando os pedaços enviados por `self.__next_f.push`."""
    return "".join(json.loads(m.group(1)) for m in _PUSH.finditer(html))


def _json_depois(texto: str, chave: str, inicio_valor: str):
    """Valor JSON da primeira `chave` cujo valor começa com `inicio_valor`, ou None."""
    posicao = texto.find(chave + inicio_valor)
    if posicao < 0:
        return None
    valor, _ = json.JSONDecoder().raw_decode(texto, posicao + len(chave))
    return valor


def _inteiro(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _proximo(valor) -> dict | None:
    """`proximo_jogo` da tabela: {"id", "time", "escudo"} do adversário; o texto "nenhum" (fim de temporada) vira None."""
    if not isinstance(valor, dict) or _inteiro(valor.get("id")) is None:
        return None
    return {"adversario_id": _inteiro(valor["id"]), "adversario": valor.get("time") or "",
            "escudo": valor.get("escudo")}


def ler_tabela(html: str) -> dict:
    """Classificação (na ordem da CBF) e artilharia da página de tabela de uma temporada."""
    texto = fluxo(html)
    linhas = _json_depois(texto, '"data":', '[{"cod_time"')
    if not linhas:
        raise ValueError("Classificação não encontrada na página da CBF")
    classificacao = [
        {
            "cbf_id": int(linha["cod_time"]),
            "time": linha["time"],
            "uf": linha.get("uf_time"),
            "escudo": linha.get("escudo"),
            "posicao": _inteiro(linha.get("posicao")),
            "evolucao": _inteiro(linha.get("evolucao")) or 0,
            "pontos": _inteiro(linha.get("pontos")),
            "jogos": _inteiro(linha.get("jogos")),
            "vitorias": _inteiro(linha.get("vitorias")),
            "empates": _inteiro(linha.get("empates")),
            "derrotas": _inteiro(linha.get("derrotas")),
            "gols_pro": _inteiro(linha.get("gols_pro")),
            "gols_contra": _inteiro(linha.get("gols_contra")),
            "saldo": _inteiro(linha.get("gols_saldo")),
            "amarelos": _inteiro(linha.get("cartoes_amarelo")),
            "vermelhos": _inteiro(linha.get("cartoes_vermelho")),
            "aproveitamento": _inteiro(linha.get("aproveitamento")),
            "rodada": _inteiro(linha.get("rodada")),
            # Últimos resultados (V, E ou D) que a própria tabela traz: a sequência sem ler a página do time.
            "ultimos": [r for r in (linha.get("ultimos_jogos") or []) if r in ("V", "E", "D")],
            # Próximo adversário, que a tabela também traz (com o escudo); None quando não há jogo a fazer.
            "proximo": _proximo(linha.get("proximo_jogo")),
        }
        for linha in linhas
    ]
    artilharia = [
        {
            "atleta_id": int(atleta["id"]),
            "nome": atleta.get("nome"),
            "apelido": atleta.get("apelido") or atleta.get("nome"),
            "gols": _inteiro(atleta.get("gols")),
            "cbf_id": _inteiro((atleta.get("clube") or {}).get("id")),
            "clube": (atleta.get("clube") or {}).get("nome"),
            "escudo": (atleta.get("clube") or {}).get("url_escudo"),
        }
        for atleta in (_json_depois(texto, '"initialData":{"atletas":', "[") or [])
    ]
    rodada = max((linha["rodada"] or 0 for linha in classificacao), default=0)
    return {"rodada": rodada, "classificacao": classificacao, "artilharia": artilharia}


def _data(texto: str | None) -> str | None:
    """'03/12/2025' -> '2025-12-03' (ordenável)."""
    try:
        return datetime.strptime(str(texto).strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def ler_time(html: str) -> dict:
    """Elenco e jogos de um time na temporada da página."""
    texto = fluxo(html)
    atletas = [
        {
            "atleta_id": int(atleta["atleta_id"]),
            "nome": atleta.get("atleta_nome") or "",
            "apelido": atleta.get("Atleta_apelido") or atleta.get("atleta_apelido") or "",
        }
        for atleta in (_json_depois(texto, '"atletas":', '[{"atleta_id"') or [])
    ]
    jogos = [
        {
            "id": _inteiro(jogo.get("id_jogo")),
            "rodada": _inteiro(jogo.get("rodada")),
            "data": _data(jogo.get("data")),
            "mandante": _inteiro(jogo["mandante"].get("id")),
            "visitante": _inteiro(jogo["visitante"].get("id")),
            "gols_mandante": _inteiro(jogo["mandante"].get("gols")),
            "gols_visitante": _inteiro(jogo["visitante"].get("gols")),
        }
        for jogo in (_json_depois(texto, '"jogos":', '[{"id_jogo"') or [])
    ]
    return {"atletas": atletas, "jogos": jogos}


def ler_atleta(html: str) -> dict:
    """Foto e número de partidas do atleta na temporada da página."""
    texto = fluxo(html)
    estatisticas = _json_depois(texto, '"atleta_estatisticas":', "{") or {}
    return {"partidas": _inteiro(estatisticas.get("qtd_partidas")), "foto": _foto_do_fluxo(texto)}


def ler_foto(html: str) -> tuple[bytes, str] | None:
    """Imagem (conteúdo e tipo) da foto do atleta, embutida na página como data URI."""
    return _foto_do_fluxo(fluxo(html))


def _foto_do_fluxo(texto: str) -> tuple[bytes, str] | None:
    achado = re.search(r'"atleta_foto":"((?:[^"\\]|\\.)*)"', texto)
    if not achado:
        return None
    valor = achado.group(1)
    if valor.startswith("$"):
        # Referência a um bloco de texto do Next.js: "<id>:T<tamanho em hexadecimal>,<conteúdo>".
        bloco = re.search(r"(?<![0-9a-f])" + re.escape(valor[1:]) + r":T([0-9a-f]+),", texto)
        if not bloco:
            return None
        valor = texto[bloco.end(): bloco.end() + int(bloco.group(1), 16)]
    if not valor.startswith("data:image/") or ";base64," not in valor:
        return None
    cabecalho, conteudo = valor.split(",", 1)
    return base64.b64decode(conteudo), cabecalho[len("data:"):].split(";")[0]


# ---------- Acesso ao site ----------

# O servidor da CBF não envia o certificado intermediário que assinou o dele (Sectigo OV R36).
# Navegadores o buscam sozinhos; o Python não. O intermediário público fica no projeto e a
# verificação continua completa, até a raiz R46 do pacote certifi.
INTERMEDIARIO = Path(__file__).with_name("certificados") / "sectigo_ov_r36.pem"


class _AdaptadorCBF(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        contexto = ssl.create_default_context(cafile=certifi.where())
        contexto.load_verify_locations(cafile=str(INTERMEDIARIO))
        kwargs["ssl_context"] = contexto
        return super().init_poolmanager(*args, **kwargs)


_sessao = requests.Session()
_sessao.headers["User-Agent"] = USER_AGENT
_sessao.mount("https://www.cbf.com.br/", _AdaptadorCBF(pool_maxsize=PARALELO + 4))


_vez = threading.Semaphore(PARALELO)
_trava_ritmo = threading.Lock()
_ultima_requisicao = [0.0]


def _esperar_a_vez() -> None:
    """No máximo uma requisição a cada INTERVALO segundos, somando todas as threads do processo."""
    with _trava_ritmo:
        espera = _ultima_requisicao[0] + INTERVALO - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ultima_requisicao[0] = time.monotonic()


_pausa_ate = [0.0]


def baixar_pagina(caminho: str) -> str:
    """HTML de `BASE/caminho`, em ritmo educado e com novas tentativas quando o site limita ou falha.

    A CBF bloqueia o IP por alguns minutos depois de rajadas de requisições; por isso o ritmo
    vale para tudo (tabelas, times e fotos). Se a conexão cair mesmo assim, a coleta pausa por
    PAUSA_APOS_FALHA segundos e falha na hora, em vez de insistir e deixar as páginas esperando.
    """
    for tentativa in range(TENTATIVAS):
        restante = _pausa_ate[0] - time.monotonic()
        if restante > 0:
            raise requests.ConnectionError(f"CBF indisponível; nova tentativa em {restante:.0f}s")
        try:
            with _vez:
                _esperar_a_vez()
                resposta = _sessao.get(f"{BASE}/{caminho}", timeout=20)
        except requests.ConnectionError:
            # Conexão derrubada é o sinal do bloqueio da CBF: insistir só atrasa as páginas.
            _pausa_ate[0] = time.monotonic() + PAUSA_APOS_FALHA
            raise
        if resposta.status_code not in CODIGOS_RETENTAVEIS or tentativa == TENTATIVAS - 1:
            resposta.raise_for_status()
            return resposta.text
        time.sleep(2 * 2**tentativa)
    raise RuntimeError(f"Falha ao acessar {caminho}")


def temporadas_disponiveis(hoje: datetime | None = None) -> list[str]:
    return [str(ano) for ano in range(PRIMEIRA_TEMPORADA, (hoje or datetime.now()).year + 1)]


def tabela(ano: str, buscar=baixar_pagina) -> dict:
    """Classificação e artilharia da temporada: uma requisição. Os times entram depois, sob demanda."""
    dados = ler_tabela(buscar(f"tabelas/{CAMPEONATO}/{ano}"))
    encerrada = all((linha["jogos"] or 0) >= JOGOS_NA_TEMPORADA for linha in dados["classificacao"])
    return {"ano": str(ano), "fonte": "CBF", **dados, "encerrada": encerrada, "times": {}}


def time_da_temporada(ano: str, cbf_id: int, buscar=baixar_pagina) -> dict:
    """Elenco e jogos de um time: uma requisição."""
    return ler_time(buscar(f"times/{CAMPEONATO}/{ano}/{cbf_id}"))


def atleta(ano: str, atleta_id: int, buscar=baixar_pagina) -> dict:
    return ler_atleta(buscar(f"atletas/{CAMPEONATO}/{ano}/{atleta_id}"))


ERROS_FONTE = (requests.RequestException, ValueError, KeyError)


class Cache:
    """Temporadas lidas só quando pedidas, em memória e em `pasta` (texto), para sobreviver ao reinício.

    Três níveis, cada um buscado só quando a página precisa dele:
    - `temporada(ano)`: a tabela (uma requisição na CBF);
    - `time(ano, id)`: elenco e jogos de um time (uma requisição), para a foto de um jogador dele;
    - `completa(ano)`: os times que faltam, para os recortes de mandante e visitante.
    Encerradas nunca são lidas de novo. A em andamento é conferida depois de `validade` segundos;
    se a tabela mudou, os times guardados são descartados e lidos de novo quando pedidos.
    Por padrão lê a CBF; com `ler_tabela`, `ler_time` e outro `prefixo`, serve para outra fonte.
    """

    def __init__(self, pasta: Path = CACHE_FONTES, buscar=baixar_pagina, validade: float = VALIDADE_ABERTA,
                 ler_tabela=None, ler_time=None, prefixo: str = "cbf-", paralelo: int = PARALELO):
        self.pasta = pasta
        self.buscar = buscar
        self.validade = validade
        self.ler_tabela = ler_tabela or (lambda ano: tabela(ano, self.buscar))
        self.ler_time = ler_time or (lambda ano, time_id: time_da_temporada(ano, time_id, self.buscar))
        self.prefixo = prefixo
        self.paralelo = paralelo
        self._memoria: dict[str, tuple[float, dict]] = {}
        self._travas: dict[object, threading.Lock] = {}
        self._trava_geral = threading.Lock()

    def _trava(self, chave) -> threading.Lock:
        with self._trava_geral:
            return self._travas.setdefault(chave, threading.Lock())

    def _arquivo(self, ano: str) -> Path:
        return self.pasta / f"{self.prefixo}{ano}.json"

    def _gravar(self, dados: dict) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._arquivo(dados["ano"]).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    def temporada(self, ano: str) -> dict:
        """Tabela da temporada; levanta erro de rede/leitura se não houver cache e a fonte falhar."""
        ano = str(ano)
        with self._trava(ano):
            guardado = self._memoria.get(ano)
            if guardado is None and self._arquivo(ano).exists():
                # Do disco: encerrada vale para sempre; em andamento precisa ser conferida.
                guardado = (float("-inf"), json.loads(self._arquivo(ano).read_text(encoding="utf-8")))
                self._memoria[ano] = guardado
            if guardado and (guardado[1]["encerrada"] or time.monotonic() - guardado[0] < self.validade):
                return guardado[1]
            try:
                dados = self.ler_tabela(ano)
            except ERROS_FONTE:
                if guardado:
                    # Sem a fonte: segue com a versão anterior e só tenta de novo depois da validade.
                    self._memoria[ano] = (time.monotonic(), guardado[1])
                    return guardado[1]
                raise
            if guardado and guardado[1]["classificacao"] == dados["classificacao"]:
                dados["times"] = guardado[1].get("times", {})  # nada mudou: os times continuam valendo
            self._gravar(dados)
            self._memoria[ano] = (time.monotonic(), dados)
            return dados

    def time(self, ano: str, time_id: int) -> dict:
        """Elenco e jogos de um time na temporada, lidos na primeira vez que alguém pedir."""
        dados = self.temporada(ano)
        chave = str(time_id)
        if chave in dados["times"]:
            return dados["times"][chave]
        with self._trava((str(ano), chave)):
            if chave not in dados["times"]:
                lido = self.ler_time(str(ano), int(time_id))
                with self._trava(str(ano)):
                    dados["times"][chave] = lido
                    self._gravar(dados)
        return dados["times"][chave]

    def completa(self, ano: str) -> dict:
        """Temporada com os times que ainda faltam (para os recortes de mandante e visitante)."""
        dados = self.temporada(ano)
        faltam = [l["cbf_id"] for l in dados["classificacao"] if str(l["cbf_id"]) not in dados["times"]]
        if faltam:
            with ThreadPoolExecutor(self.paralelo) as executor:
                list(executor.map(lambda time_id: self.time(ano, time_id), faltam))
        return dados

    def atleta(self, ano: str, atleta_id: int) -> dict:
        """Foto e partidas do atleta na temporada; só em memória (a foto nunca vai para o disco)."""
        chave = (str(ano), int(atleta_id))
        if chave not in _atletas:
            if len(_atletas) >= _LIMITE_ATLETAS:
                _atletas.pop(next(iter(_atletas)))
            _atletas[chave] = atleta(*chave, self.buscar)
        return _atletas[chave]

    def foto(self, ano: str, atleta_id: int) -> tuple[bytes, str] | None:
        return self.atleta(ano, atleta_id)["foto"]


_atletas: dict[tuple[str, int], dict] = {}
_LIMITE_ATLETAS = 600  # foto de ~25 KB cada: até ~15 MB de memória


# ---------- Casamento com a base do ScoutBoard ----------

def _palavras(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalizar(texto))


def _palavras_time(nome: str) -> set[str]:
    return set(_palavras(_SIGLAS.sub(" ", normalizar(nome)))) - _PARTICULAS


def casar_times(nossos: dict[int, str], classificacao: list[dict]) -> dict[int, int]:
    """team_id da base -> id da CBF. Só entra quem tem exatamente um candidato.

    O nome da base pode terminar com a UF ("Atletico MG"), que precisa bater com a da CBF.
    Vale o nome da base contido no da CBF ou o contrário ("Sport Recife" e "Sport").
    """
    saida = {}
    for team_id, nome in nossos.items():
        nome = _APELIDOS_TIMES.get(normalizar(nome), nome)
        palavras = _palavras(nome)
        uf = palavras[-1] if len(palavras) > 1 and palavras[-1] in _UFS else None
        nucleo = _palavras_time(" ".join(palavras[:-1] if uf else palavras))
        candidatos = []
        for linha in classificacao:
            # A ESPN põe a UF no nome ("Atlético-MG"); ela vale só como UF.
            deles = _palavras_time(re.sub(r"-[A-Za-z]{2}$", "", linha["time"]))
            if uf and linha.get("uf") and normalizar(linha["uf"]) != uf:
                continue
            if nucleo and deles and (nucleo <= deles or deles <= nucleo):
                candidatos.append(linha["cbf_id"])
        if len(candidatos) == 1:
            saida[int(team_id)] = candidatos[0]
    return saida


def candidatos_atleta(nome: str, atletas: list[dict]) -> list[dict]:
    """Atletas do elenco da CBF que podem ser o jogador da base, do mais para o menos seguro.

    Regras, na ordem (vale a primeira que achar alguém): apelido igual; todas as palavras do nome
    dentro do nome completo ou do apelido; apelido inteiro dentro do nome da base ("Emerson" para
    "Emerson Royal"). Nome de uma palavra só casa por apelido igual: "Diego" não pode virar
    "Diego Alves" num elenco incompleto. Entre os achados, ficam os de apelido mais parecido com o
    nome da base ("Pedro Henrique" prefere o apelido "Pedro Henrique" a "Pedro").
    """
    alvo = normalizar(nome)
    palavras = set(_palavras(nome)) - _PARTICULAS
    regras = (
        lambda a: normalizar(a["apelido"]) == alvo,
        lambda a: len(palavras) > 1 and palavras <= set(_palavras(a["nome"])) | set(_palavras(a["apelido"])),
        lambda a: bool(set(_palavras(a["apelido"])) - _PARTICULAS)
        and set(_palavras(a["apelido"])) - _PARTICULAS <= palavras,
    )

    def nota(atleta: dict) -> int:
        deles = set(_palavras(atleta["apelido"])) - _PARTICULAS
        if normalizar(atleta["apelido"]) == alvo:
            return 3
        if deles == palavras:
            return 2
        return 1 if deles and (deles <= palavras or palavras <= deles) else 0

    for regra in regras:
        achados = [atleta for atleta in atletas if regra(atleta)]
        if achados:
            melhor = max(nota(a) for a in achados)
            return [a for a in achados if nota(a) == melhor]
    return []


def casar_atleta(nome: str, atletas: list[dict]) -> dict | None:
    """O atleta, quando só um candidato sobra. Na dúvida, nenhum: foto errada é pior que nenhuma."""
    candidatos = candidatos_atleta(nome, atletas)
    return candidatos[0] if len(candidatos) == 1 else None


def desempatar_por_jogos(jogos_na_base: int, partidas: dict[int, int | None], margem: int = 5) -> int | None:
    """Entre homônimos, o atleta cujo número de partidas na CBF mais se aproxima dos jogos na base.

    Só decide quando a diferença para o segundo colocado é de pelo menos `margem` partidas
    (ex.: dois "Pedro" no elenco, um com 30 jogos e outro com 2).
    """
    distancias = sorted((abs(n - jogos_na_base), atleta_id) for atleta_id, n in partidas.items() if n is not None)
    if not distancias:
        return None
    if len(distancias) > 1 and distancias[1][0] - distancias[0][0] < margem:
        return None
    return distancias[0][1]
