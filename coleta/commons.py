"""Escudos e fotos do Wikimedia Commons, pelas APIs oficiais (MediaWiki e Wikidata).

O que vem daqui:
- escudos dos clubes: a imagem do infobox do clube na Wikipédia (pt) ou, na falta dela, o logotipo
  (P154) do clube no Wikidata. Só vale arquivo que está no Commons (licença livre ou domínio
  público) e que não é fotografia: escudo guardado só na Wikipédia, como "uso restrito", fica de
  fora, e o site usa a reserva (CBF ou ESPN);
- fotos de jogadores, como reserva da CBF: a imagem (P18) de quem jogou pelo clube (P54) e tem
  exatamente o mesmo nome;
- fotos de técnicos: a imagem (P18) que coleta/treinadores.py grava junto com o histórico;
- autor e licença de cada arquivo, para a página de créditos do site.

Nenhuma imagem é baixada nem gravada: o site redireciona o navegador para a miniatura no Commons.
Em dados/cache/ fica só texto (nome do arquivo, endereço, autor e licença).

Limites da Wikimedia (2026): 10 requisições por minuto para quem não se identifica e 200 para quem
manda contato no User-Agent (variável SCOUTBOARD_CONTATO, em config.py). Por isso tudo é pedido em
lote e em série: os escudos de todos os clubes custam 3 requisições e valem VALIDADE segundos; as
fotos de jogadores, uma consulta por clube; os créditos, uma requisição a cada LOTE arquivos.

No site nenhum pedido de imagem espera essas leituras (Commons(em_segundo_plano=True)). Para ler
tudo de uma vez antes de subir o site: python -m coleta.commons
"""
import csv
import html
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests

from config import CACHE_FONTES, MAPEAMENTO_TIMES, USER_AGENT
from coleta.nomes import normalizar

API_COMMONS = "https://commons.wikimedia.org/w/api.php"
API_WIKIPEDIA = "https://pt.wikipedia.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
ARQUIVO_NO_COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"
LARGURA = 120  # um dos tamanhos padrão de miniatura da Wikimedia
LOTE = 50  # máximo de títulos por requisição para quem não é robô registrado
INTERVALO = 1.0  # segundos entre o início de duas requisições, somando todo o processo
TEMPO_LIMITE = 15  # segundos por requisição: as consultas medidas levam de 0,5 a 2,5 s
ESPERA_MAXIMA = 10  # até quantos segundos de Retry-After vale esperar; acima disso, falha na hora
VALIDADE = 30 * 24 * 3600  # escudos e fotos mudam pouco: uma conferência por mês
PAUSA_APOS_FALHA = 300
IDADE_MINIMA, IDADE_MAXIMA = 15, 46  # de quem pode ter jogado na temporada
ERROS = (requests.RequestException, ValueError, KeyError)

CONSULTA_CLUBES = """
SELECT ?clube ?titulo ?logo WHERE {{
  VALUES ?clube {{ {clubes} }}
  OPTIONAL {{ ?artigo schema:about ?clube ; schema:isPartOf <https://pt.wikipedia.org/> ; schema:name ?titulo . }}
  OPTIONAL {{ ?clube wdt:P154 ?logo . }}
}}
"""
# Futebolistas (Q937857) com imagem que jogaram pelo clube, com rótulos e apelidos nas línguas usadas na base.
CONSULTA_JOGADORES = """
SELECT ?jogador ?nome ?nascimento ?imagem WHERE {{
  ?jogador wdt:P54 wd:{clube} ; wdt:P106 wd:Q937857 ; wdt:P18 ?imagem .
  {{ ?jogador rdfs:label ?nome . }} UNION {{ ?jogador skos:altLabel ?nome . }}
  FILTER(LANG(?nome) IN ("pt", "pt-br", "en", "es"))
  OPTIONAL {{ ?jogador wdt:P569 ?nascimento . }}
}}
"""

_sessao = requests.Session()
_sessao.headers["User-Agent"] = USER_AGENT
_trava = threading.Lock()
_ultima = [0.0]


def consultar(endereco: str, parametros: dict) -> dict:
    """JSON de uma API da Wikimedia: uma requisição por vez, com INTERVALO entre elas.

    Se a Wikimedia limitar (429) ou estiver sobrecarregada (503), espera o Retry-After e tenta
    mais uma vez; se ele passar de ESPERA_MAXIMA, falha na hora, para a página não ficar esperando.
    """
    for tentativa in range(2):
        with _trava:
            espera = _ultima[0] + INTERVALO - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            _ultima[0] = time.monotonic()
            resposta = _sessao.get(endereco, params={**parametros, "format": "json"}, timeout=TEMPO_LIMITE)
        if resposta.status_code in (429, 503) and tentativa == 0:
            pedido = resposta.headers.get("Retry-After", "")
            espera = float(pedido) if pedido.isdigit() else 5.0
            if espera <= ESPERA_MAXIMA:
                time.sleep(espera)
                continue
        resposta.raise_for_status()
        dados = resposta.json()
        if "error" in dados:
            raise ValueError(f"Wikimedia: {dados['error'].get('info', dados['error'])}")
        return dados
    raise RuntimeError(f"Falha ao consultar {endereco}")


# ---------- Leitura das respostas ----------

def _nome(arquivo: str) -> str:
    """Nome do arquivo como o Commons o escreve: sem o prefixo, com espaços e a primeira letra maiúscula."""
    nome = re.sub(r"^(File|Ficheiro|Arquivo|Imagem):", "", str(arquivo), flags=re.I).replace("_", " ").strip()
    return nome[:1].upper() + nome[1:]


def arquivo_do_endereco(endereco: str | None) -> str | None:
    """'http://commons.wikimedia.org/wiki/Special:FilePath/Tite%202018.jpg' (Wikidata) -> 'Tite 2018.jpg'."""
    if not endereco or "Special:FilePath/" not in endereco:
        return None
    return _nome(unquote(endereco.rsplit("Special:FilePath/", 1)[1]))


def miniatura(arquivo: str, largura: int = LARGURA) -> str:
    """Endereço que o Commons redireciona para a miniatura do arquivo, sem consultar a API."""
    return f"{ARQUIVO_NO_COMMONS}{quote(_nome(arquivo).replace(' ', '_'))}?width={largura}"


def pagina_do_arquivo(arquivo: str) -> str:
    return f"https://commons.wikimedia.org/wiki/File:{quote(_nome(arquivo).replace(' ', '_'))}"


def _texto(valor: str | None) -> str | None:
    """Texto visível de um campo que o Commons devolve em HTML (o autor costuma ser um link)."""
    limpo = " ".join(html.unescape(re.sub(r"<[^>]+>", "", valor or "")).split())
    return limpo[:120] or None


def _paginas(endereco: str, parametros: dict, consultar=consultar) -> tuple[list[dict], dict[str, str]]:
    """Páginas de uma consulta `action=query` (seguindo "continue") e as trocas de título que a API fez."""
    paginas, trocas = [], {}
    parametros = {"action": "query", "formatversion": "2", **parametros}
    while True:
        resposta = consultar(endereco, parametros)
        consulta = resposta.get("query", {})
        for chave in ("normalized", "redirects"):
            trocas.update({item["from"]: item["to"] for item in consulta.get(chave, [])})
        paginas += consulta.get("pages", [])
        if "continue" not in resposta:
            return paginas, trocas
        parametros = {**parametros, **resposta["continue"]}


def _lotes(itens: list[str]) -> list[list[str]]:
    unicos = list(dict.fromkeys(itens))
    return [unicos[inicio:inicio + LOTE] for inicio in range(0, len(unicos), LOTE)]


def informacoes(arquivos: list[str], consultar=consultar) -> dict[str, dict | None]:
    """Miniatura, tipo, autor e licença de cada arquivo no Commons; None para o que não existe lá.

    Um arquivo que só existe na Wikipédia (escudo de "uso restrito") volta como None.
    """
    saida: dict[str, dict | None] = {}
    for lote in _lotes([_nome(a) for a in arquivos if a]):
        paginas, _ = _paginas(API_COMMONS, {
            "titles": "|".join(f"File:{nome}" for nome in lote), "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata", "iiurlwidth": str(LARGURA),
            "iiextmetadatafilter": "Artist|LicenseShortName",
        }, consultar)
        lidos = {}
        for pagina in paginas:
            dados = (pagina.get("imageinfo") or [None])[0]
            if not dados or pagina.get("missing"):
                continue
            extras = dados.get("extmetadata") or {}
            nome = _nome(pagina["title"])
            lidos[nome] = {
                "arquivo": nome,
                "miniatura": dados.get("thumburl") or miniatura(nome),
                "tipo": dados.get("mime"),
                "autor": _texto((extras.get("Artist") or {}).get("value")),
                "licenca": _texto((extras.get("LicenseShortName") or {}).get("value")),
                "pagina": dados.get("descriptionurl") or pagina_do_arquivo(nome),
            }
        saida.update({nome: lidos.get(nome) for nome in lote})
    return saida


def imagens_das_paginas(titulos: list[str], consultar=consultar) -> dict[str, str | None]:
    """Título da página na Wikipédia (pt) -> arquivo da imagem principal dela (a do infobox)."""
    saida: dict[str, str | None] = {}
    for lote in _lotes(titulos):
        paginas, trocas = _paginas(API_WIKIPEDIA, {
            "titles": "|".join(lote), "prop": "pageimages", "piprop": "name", "pilicense": "any",
            "pilimit": str(LOTE), "redirects": "1",
        }, consultar)
        imagens = {pagina["title"]: pagina.get("pageimage") for pagina in paginas}
        for titulo in lote:
            destino = trocas.get(titulo, titulo)  # título normalizado
            destino = trocas.get(destino, destino)  # e o destino do redirecionamento
            saida[titulo] = _nome(imagens[destino]) if imagens.get(destino) else None
    return saida


def _linhas_sparql(consulta: str, consultar=consultar) -> list[dict[str, str]]:
    resposta = consultar(SPARQL, {"query": consulta})
    return [{campo: valor["value"] for campo, valor in linha.items()} for linha in resposta["results"]["bindings"]]


def _qid(endereco: str) -> str:
    return endereco.rsplit("/", 1)[-1]


def _serve_de_escudo(dados: dict | None) -> bool:
    """Está no Commons e não é fotografia: o P154 de alguns clubes aponta para uma foto do escudo."""
    return bool(dados) and dados.get("tipo") != "image/jpeg"


def buscar_escudos(qids: dict[int, str], consultar=consultar) -> dict[int, dict | None]:
    """team_id -> dados do escudo no Commons (ver `informacoes`), ou None para o clube sem escudo lá.

    Três requisições para todos os clubes: o título do clube na Wikipédia (pt) e o logotipo P154,
    pelo Wikidata; a imagem do infobox, pela Wikipédia; e a conferência dos arquivos no Commons.
    """
    clubes: dict[str, dict] = {}
    consulta = CONSULTA_CLUBES.format(clubes=" ".join(f"wd:{qid}" for qid in sorted(set(qids.values()))))
    for linha in _linhas_sparql(consulta, consultar):
        clube = clubes.setdefault(_qid(linha["clube"]), {"titulo": None, "logos": []})
        clube["titulo"] = clube["titulo"] or linha.get("titulo")
        logo = arquivo_do_endereco(linha.get("logo"))
        if logo and logo not in clube["logos"]:
            clube["logos"].append(logo)
    do_infobox = imagens_das_paginas([c["titulo"] for c in clubes.values() if c["titulo"]], consultar)
    candidatos = {
        qid: [a for a in [do_infobox.get(clube["titulo"]), *clube["logos"]] if a]
        for qid, clube in clubes.items()
    }
    dados = informacoes([a for lista in candidatos.values() for a in lista], consultar)
    return {
        int(team_id): next((dados[a] for a in candidatos.get(qid, []) if _serve_de_escudo(dados.get(a))), None)
        for team_id, qid in qids.items()
    }


def buscar_jogadores(qid_clube: str, consultar=consultar) -> list[dict]:
    """Futebolistas com imagem no Commons que jogaram pelo clube: id, arquivo, ano de nascimento e nomes."""
    jogadores: dict[str, dict] = {}
    for linha in _linhas_sparql(CONSULTA_JOGADORES.format(clube=qid_clube), consultar):
        arquivo = arquivo_do_endereco(linha.get("imagem"))
        if not arquivo:
            continue
        jogador = jogadores.setdefault(
            _qid(linha["jogador"]), {"id": _qid(linha["jogador"]), "arquivo": arquivo, "nascimento": None, "nomes": []}
        )
        ano = (linha.get("nascimento") or "")[:4]
        jogador["nascimento"] = jogador["nascimento"] or (int(ano) if ano.isdigit() else None)
        nome = normalizar(linha.get("nome", ""))
        if nome and nome not in jogador["nomes"]:
            jogador["nomes"].append(nome)
    return list(jogadores.values())


def _idade_confere(nascimento: int | None, anos: list[int]) -> bool:
    """Quem nasceu em `nascimento` podia jogar em todas as temporadas `anos`? Sem a data, vale."""
    if not nascimento or not anos:
        return True
    return min(anos) - nascimento >= IDADE_MINIMA and max(anos) - nascimento <= IDADE_MAXIMA


def escolher_jogador(nomes: list[str], jogadores: list[dict], temporadas: list[str] = ()) -> dict | None:
    """O jogador do Commons com um dos `nomes`, quando só um sobra. Na dúvida, nenhum.

    Vale só nome igual (ao rótulo ou a um apelido do Wikidata): "Felipe Anderson" não vira "Felipe".
    Os nomes são tentados na ordem; um nome com dois donos passa a vez ao seguinte (o nome completo
    costuma desempatar). A idade tira o homônimo de outra época que jogou no mesmo clube.
    """
    anos = [int(ano) for ano in temporadas if str(ano).isdigit()]
    possiveis = [j for j in jogadores if _idade_confere(j.get("nascimento"), anos)]
    for nome in dict.fromkeys(normalizar(n) for n in nomes if n):
        achados = {j["id"]: j for j in possiveis if nome in j["nomes"]}
        if len(achados) == 1:
            return next(iter(achados.values()))
    return None


def qids_dos_times(caminho: Path = MAPEAMENTO_TIMES) -> dict[int, str]:
    """team_id da base -> item do clube no Wikidata (dados/treinadores_times.csv)."""
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        return {int(l["team_id"]): l["qid_wikidata"] for l in csv.DictReader(arquivo) if l.get("qid_wikidata")}


# ---------- Cache ----------

class Commons:
    """Escudos, fotos de jogadores e créditos do Commons, em memória e em `pasta` (só texto).

    - `escudo(team_id)`: endereço da miniatura do escudo; todos os clubes são lidos de uma vez e
      conferidos de novo depois de `validade` segundos;
    - `foto_jogador(nomes, team_ids, temporadas)`: endereço da foto; a lista de quem tem foto é
      lida uma vez por clube;
    - `foto(arquivo)`: endereço da miniatura de um arquivo conhecido (a foto de um técnico);
    - `creditos(arquivos)`: autor e licença dos escudos, das fotos já mostradas e de `arquivos`.

    Com `em_segundo_plano` (o padrão do site), nenhum pedido de imagem espera a Wikimedia: o que
    falta é lido por uma thread à parte, e até lá a resposta é "não tem" (o site usa a reserva ou
    as iniciais, e a imagem aparece na próxima vez). Sem ele, a leitura é feita na hora.
    `aquecer()` lê tudo de uma vez, para o primeiro acesso já sair completo.

    Sem resposta da Wikimedia, vale o que já estava guardado (ou nada) e as consultas param por
    PAUSA_APOS_FALHA segundos.
    """

    ARQUIVO_ESCUDOS = "commons-escudos.json"
    ARQUIVO_JOGADORES = "commons-jogadores.json"
    ARQUIVO_FOTOS = "commons-fotos.json"

    def __init__(self, qids: dict[int, str] | None = None, pasta: Path = CACHE_FONTES, consultar=consultar,
                 validade: float = VALIDADE, agora=time.time, em_segundo_plano: bool = False):
        self.qids = qids_dos_times() if qids is None else qids
        self.pasta = pasta
        self.consultar = consultar
        self.validade = validade
        self.agora = agora
        self.em_segundo_plano = em_segundo_plano
        self.ultimo_erro: str | None = None
        self._trava = threading.RLock()
        self._pausa_ate = 0.0
        self._guardados: dict[str, dict] = {}
        self._lendo: set[str] = set()

    def _guardado(self, nome: str, padrao: dict) -> dict:
        if nome not in self._guardados:
            arquivo = self.pasta / nome
            self._guardados[nome] = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else padrao
        return self._guardados[nome]

    def _gravar(self, nome: str) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        (self.pasta / nome).write_text(json.dumps(self._guardados[nome], ensure_ascii=False), encoding="utf-8")

    def _vencido(self, lido_em: float) -> bool:
        return self.agora() - lido_em >= self.validade and time.monotonic() >= self._pausa_ate

    def _ler(self, chave: str, buscar, guardar) -> None:
        """Roda `buscar()` (rede, fora da trava) e entrega o resultado a `guardar` (com a trava).

        Em segundo plano, só agenda a leitura, uma por `chave` de cada vez, e volta na hora.
        """
        def ler():
            try:
                lido = buscar()
            except ERROS as erro:
                self.ultimo_erro = str(erro)
                self._pausa_ate = time.monotonic() + PAUSA_APOS_FALHA
            else:
                with self._trava:
                    guardar(lido)
            finally:
                with self._trava:
                    self._lendo.discard(chave)

        with self._trava:
            if chave in self._lendo:
                return
            self._lendo.add(chave)
        if self.em_segundo_plano:
            threading.Thread(target=ler, name=f"commons-{chave}", daemon=True).start()
        else:
            ler()

    def _escudos(self) -> dict[str, dict | None]:
        with self._trava:
            guardado = self._guardado(self.ARQUIVO_ESCUDOS, {"lido_em": 0, "escudos": {}})
            vencido = self._vencido(guardado["lido_em"])
        if vencido:
            def guardar(lidos):
                guardado.update(lido_em=self.agora(), escudos={str(t): dados for t, dados in lidos.items()})
                self._gravar(self.ARQUIVO_ESCUDOS)

            self._ler("escudos", lambda: buscar_escudos(self.qids, self.consultar), guardar)
        return guardado["escudos"]

    def escudo(self, team_id: int) -> str | None:
        """Endereço da miniatura do escudo do time no Commons, ou None se ele não está lá."""
        return (self._escudos().get(str(team_id)) or {}).get("miniatura")

    def _jogadores_do_clube(self, qid: str) -> list[dict]:
        with self._trava:
            guardado = self._guardado(self.ARQUIVO_JOGADORES, {})
            vencido = self._vencido((guardado.get(qid) or {"lido_em": 0})["lido_em"])
        if vencido:
            def guardar(jogadores):
                guardado[qid] = {"lido_em": self.agora(), "jogadores": jogadores}
                self._gravar(self.ARQUIVO_JOGADORES)

            self._ler(qid, lambda: buscar_jogadores(qid, self.consultar), guardar)
        return (guardado.get(qid) or {"jogadores": []})["jogadores"]

    def foto(self, arquivo: str) -> str:
        """Endereço da miniatura de um arquivo do Commons (a foto de um técnico, por exemplo).

        Não consulta nada: vale a miniatura já conhecida ou o endereço que o próprio Commons
        redireciona. O arquivo fica anotado para a página de créditos, que busca autor e licença.
        """
        nome = _nome(arquivo)
        with self._trava:
            guardado = self._guardado(self.ARQUIVO_FOTOS, {})
            if nome not in guardado:
                guardado[nome] = False  # mostrado, ainda sem autor e licença
                self._gravar(self.ARQUIVO_FOTOS)
            return (guardado[nome] or {}).get("miniatura") or miniatura(nome)

    def foto_jogador(self, nomes: list[str], team_ids: list[int], temporadas: list[str] = ()) -> str | None:
        """Endereço da foto de quem tem um dos `nomes` e jogou por um dos times, nas `temporadas` da base."""
        jogadores = {}
        for team_id in dict.fromkeys(int(t) for t in team_ids):
            if team_id in self.qids:
                jogadores.update({j["id"]: j for j in self._jogadores_do_clube(self.qids[team_id])})
        achado = escolher_jogador(nomes, list(jogadores.values()), temporadas)
        return self.foto(achado["arquivo"]) if achado else None

    def creditos(self, arquivos: list[str] = ()) -> list[dict]:
        """Arquivo, página, autor e licença dos escudos, das fotos já mostradas e de `arquivos`.

        O que ainda não foi consultado custa, aqui e na hora, uma requisição a cada LOTE arquivos;
        sem resposta, a linha sai só com o endereço da página do arquivo, onde autor e licença estão.
        """
        linhas = [{**dados, "uso": "Escudo"} for dados in self._escudos().values() if dados]
        with self._trava:
            guardado = self._guardado(self.ARQUIVO_FOTOS, {})
            nomes = list(dict.fromkeys([*(_nome(a) for a in arquivos if a), *guardado]))
            faltam = [nome for nome in nomes if guardado.get(nome) is None or guardado.get(nome) is False]
        if faltam and time.monotonic() >= self._pausa_ate:
            try:
                lidos = informacoes(faltam, self.consultar)
            except ERROS as erro:
                self.ultimo_erro = str(erro)
                self._pausa_ate = time.monotonic() + PAUSA_APOS_FALHA
            else:
                with self._trava:
                    # O que não existe no Commons fica como {} para não ser consultado de novo.
                    guardado.update({nome: dados or {} for nome, dados in lidos.items()})
                    self._gravar(self.ARQUIVO_FOTOS)
        for nome in nomes:
            dados = guardado.get(nome)
            if dados == {}:
                continue
            linhas.append({**(dados or {"arquivo": nome, "pagina": pagina_do_arquivo(nome), "autor": None,
                                        "licenca": None}), "uso": "Foto"})
        return sorted(linhas, key=lambda linha: (linha["uso"], normalizar(linha["arquivo"])))

    def aquecer(self) -> dict:
        """Lê na hora os escudos e os jogadores de todos os clubes; devolve quantos ficaram guardados."""
        em_segundo_plano, self.em_segundo_plano = self.em_segundo_plano, False
        try:
            escudos = sum(1 for dados in self._escudos().values() if dados)
            jogadores = sum(len(self._jogadores_do_clube(qid)) for qid in dict.fromkeys(self.qids.values()))
        finally:
            self.em_segundo_plano = em_segundo_plano
        return {"escudos": escudos, "jogadores_com_foto": jogadores, "erro": self.ultimo_erro}


if __name__ == "__main__":
    import argparse

    argparse.ArgumentParser(description="Lê de uma vez escudos e fotos do Commons para dados/cache/.").parse_args()
    print(json.dumps(Commons().aquecer(), ensure_ascii=False))
