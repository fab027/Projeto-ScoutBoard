"""Páginas e API do site do ScoutBoard (blueprint registrado em sb_web.create_app).

Execução a partir da raiz do projeto: `python iniciar.py`.
"""
import logging
from functools import lru_cache

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request

from coleta import cbf
from sb_web import classificacao, painel
from sb_web.fonte_cbf import ERROS_CBF, FonteCBF

site_bp = Blueprint("site", __name__)
log = logging.getLogger(__name__)
CACHE_NAVEGADOR = "public, max-age=604800"  # uma semana: o navegador guarda, o projeto não


@lru_cache(maxsize=1)
def dados() -> painel.Dados:
    return painel.carregar()


@lru_cache(maxsize=1)
def fonte() -> FonteCBF:
    return FonteCBF(dados())


def _inteiro(valor: str | None) -> int | None:
    if valor in (None, ""):
        return None
    return int(valor)


def _temporada() -> str:
    return request.args.get("temporada") or dados().temporadas[-1]


def _pagina(modelo: str, nome: str, status: int = 200, **contexto):
    return render_template(modelo, pagina=nome, **contexto), status


@site_bp.get("/")
def inicio():
    return _pagina("index.html", "inicio")


@site_bp.get("/api/painel")
def api_painel():
    try:
        resposta = painel.painel(
            dados(),
            temporada=_temporada(),
            jogo=_inteiro(request.args.get("jogo")),
            time=_inteiro(request.args.get("time")),
            jogador=_inteiro(request.args.get("jogador")),
            x=request.args.get("x", "finalizacoes"),
            y=request.args.get("y", "passes_certos"),
        )
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    return jsonify(resposta)


@site_bp.get("/rankings")
def rankings():
    temporada = _temporada()
    metrica = request.args.get("metrica", "gols")
    try:
        contexto = painel.pagina_rankings(dados(), temporada, metrica)
        return _pagina("rankings.html", "rankings", **contexto)
    except ValueError as erro:
        return _pagina(
            "rankings.html", "rankings", 400,
            temporada=temporada, metrica=metrica, temporadas=dados().temporadas,
            metricas=painel.METRICAS_RANKING, ranking=[], premios=[], erro=str(erro),
        )


@site_bp.get("/jogadores")
def jogadores():
    temporada = _temporada()
    termo = request.args.get("termo", "")
    try:
        time = _inteiro(request.args.get("time"))
    except ValueError:
        time = None
    try:
        contexto = painel.pagina_jogadores(dados(), temporada, time, termo)
        return _pagina("jogadores.html", "jogadores", **contexto)
    except ValueError as erro:
        return _pagina(
            "jogadores.html", "jogadores", 400,
            temporada=temporada, temporadas=dados().temporadas,
            time=None, termo=termo, times=[], jogadores=[], erro=str(erro),
        )


@site_bp.get("/times")
def times():
    temporadas = cbf.temporadas_disponiveis()
    temporada = request.args.get("temporada") or temporadas[-1]
    recorte = request.args.get("recorte", "geral")
    contexto = {
        "temporada": temporada, "temporadas": temporadas, "recorte": recorte,
        "recortes": classificacao.RECORTES, "zonas": classificacao.ZONAS,
        "na_base": temporada in dados().temporadas, "cbf": None, "tabela": [],
    }
    if temporada not in temporadas or recorte not in classificacao.RECORTES:
        return _pagina("times.html", "times", 400, erro="Temporada ou recorte inválido.", **contexto)
    # Artilharia: pela base (parquet) sempre que a temporada existe nela; é mais completa que a da
    # CBF e não depende de rede. A CBF/ESPN só entra na temporada que a base não tem (a atual).
    contexto["artilharia_base"] = painel.artilharia(dados(), temporada) if contexto["na_base"] else None
    try:
        # Geral abre só com a tabela; mandante e visitante precisam dos jogos dos 20 times.
        dados_temporada = fonte().temporada(temporada, completa=recorte != "geral")
        dados_temporada = fonte().com_escudos(temporada, dados_temporada)
        # A fonte mostra o clube atual de cada artilheiro; vale o clube daquela temporada.
        dados_temporada = {
            **dados_temporada,
            "artilharia": [] if contexto["na_base"] else fonte().corrigir_clubes(
                temporada, dados_temporada, dados_temporada.get("artilharia", [])
            ),
            "assistencias": fonte().corrigir_clubes(
                temporada, dados_temporada, dados_temporada.get("assistencias", []), comparar_gols=False
            ),
        }
        contexto["cbf"] = classificacao.montar(dados_temporada, recorte, fonte().links(temporada))
        if contexto["artilharia_base"]:
            # Nome do clube como na tabela oficial ("São Paulo", não "Sao Paulo" da base).
            oficiais = {l["team_id"]: l["time"] for l in contexto["cbf"]["linhas"] if l.get("team_id")}
            contexto["artilharia_base"] = [{**a, "time": oficiais.get(a["team_id"], a["time"])}
                                           for a in contexto["artilharia_base"]]
        return _pagina("times.html", "times", **contexto)
    except ERROS_CBF as erro:
        log.warning("CBF e ESPN indisponíveis para a temporada %s: %s", temporada, erro)
        if not contexto["na_base"]:
            return _pagina("times.html", "times", 503, erro="Não foi possível consultar a CBF nem a ESPN agora. Tente de novo em alguns minutos.", **contexto)
        # Sem a CBF, a tabela é calculada pelos gols dos eventos da base.
        contexto["tabela"] = painel.pagina_times(dados(), temporada)["tabela"]
        return _pagina("times.html", "times", aviso_cbf=True, **contexto)


def _imagem(achado: tuple[bytes, str] | str | None) -> Response:
    """Conteúdo da imagem (foto da CBF, guardada só em memória) ou redirecionamento para o endereço dela.

    Escudos e fotos do Commons, da ESPN e do TheSportsDB são redirecionados: o navegador carrega de lá.
    """
    if not achado:
        abort(404)
    if isinstance(achado, str):
        resposta = redirect(achado, 302)
        resposta.headers["Cache-Control"] = CACHE_NAVEGADOR
        return resposta
    conteudo, tipo = achado
    return Response(conteudo, mimetype=tipo, headers={"Cache-Control": CACHE_NAVEGADOR})


@site_bp.get("/escudo/<int:team_id>")
def escudo(team_id: int):
    """Redireciona para o escudo no Wikimedia Commons ou, se o clube não está lá, na CBF ou na ESPN.

    ?temporada= é a temporada da página: só ela é consultada na reserva.
    """
    try:
        return _imagem(fonte().escudo(team_id, request.args.get("temporada")))
    except ERROS_CBF:
        abort(404)


@site_bp.get("/foto/jogador/<int:player_id>")
def foto_jogador(player_id: int):
    """Foto do jogador da base: da página dele na CBF ou, na falta dela, do Commons ou do TheSportsDB.

    ?temporada= é a temporada da página: só o time do jogador nela é consultado.
    """
    try:
        return _imagem(fonte().foto_jogador(player_id, request.args.get("temporada")))
    except ERROS_CBF:
        abort(404)


@site_bp.get("/foto/atleta/<ano>/<int:atleta_id>")
def foto_atleta(ano: str, atleta_id: int):
    """Foto por id da CBF (artilharia). Com ?nome=&clube=, usa o TheSportsDB se a CBF falhar."""
    if ano not in cbf.temporadas_disponiveis():
        abort(404)
    try:
        achado = fonte().foto_atleta(ano, atleta_id)
    except ERROS_CBF:
        achado = None
    if not achado and request.args.get("nome"):
        return _foto_por_nome()
    return _imagem(achado)


def _foto_por_nome() -> Response:
    """Foto pelo nome e clube (?nome=&clube=), no TheSportsDB (artilharia vinda da ESPN, que não traz foto)."""
    nome, clube = request.args.get("nome", "").strip(), request.args.get("clube", "").strip()
    if not nome or not clube:
        abort(404)
    try:
        return _imagem(fonte().foto_por_nome(nome, clube))
    except ERROS_CBF:
        abort(404)


@site_bp.get("/foto/nome")
def foto_nome():
    return _foto_por_nome()


@site_bp.get("/foto/treinador")
def foto_treinador():
    """Foto do técnico (?nome=) no Wikimedia Commons; o arquivo vem da coleta de técnicos."""
    return _imagem(fonte().foto_treinador(request.args.get("nome", "").strip()))


@site_bp.get("/creditos")
def creditos():
    """Autor e licença das imagens do Wikimedia Commons que o site mostra."""
    return _pagina("creditos.html", "creditos", creditos=fonte().creditos())


@site_bp.get("/busca")
def busca():
    termo = request.args.get("q", "").strip()
    return _pagina("busca.html", "busca", termo=termo, termo_busca=termo, **painel.buscar(dados(), termo))


@site_bp.get("/api/busca")
def api_busca():
    termo = request.args.get("q", "").strip()
    return jsonify(painel.buscar(dados(), termo))
