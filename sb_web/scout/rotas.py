"""Páginas das observações de scout: lista, formulário de nova observação e exclusão."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from sb_web import rotas as site
from sb_web.scout import servico
from sb_web.scout.forms import ObservacaoForm

scout_bp = Blueprint("scout", __name__, url_prefix="/observacoes")


def _jogadores() -> dict[int, dict]:
    """Jogadores da base por id, com o nome e a última temporada em que aparecem."""
    ultimos = site.dados().ultimos
    return {
        int(linha.player_id): {"player": linha.player, "temporada": linha.temporada}
        for linha in ultimos.itertuples()
    }


def _jogador_do_filtro() -> int | None:
    try:
        return int(request.args["jogador"])
    except (KeyError, ValueError):
        return None


@scout_bp.get("/")
def lista():
    jogadores = _jogadores()
    player_id = _jogador_do_filtro()
    jogador = jogadores.get(player_id) if player_id is not None else None
    if player_id is not None and jogador is None:
        abort(404)
    return render_template(
        "observacoes.html", pagina="observacoes",
        observacoes=servico.listar(player_id), resumo=servico.resumo_por_jogador(),
        player_id=player_id, jogador=jogador,
    )


@scout_bp.route("/nova", methods=["GET", "POST"])
def nova():
    jogadores = _jogadores()
    form = ObservacaoForm(jogadores=frozenset(jogadores), temporadas=site.dados().temporadas)
    if request.method == "GET":
        player_id = _jogador_do_filtro()
        if player_id is None:
            flash("Escolha um jogador na lista para anotar uma observação.", "aviso")
            return redirect(url_for("site.jogadores"))
        if player_id not in jogadores:
            abort(404)
        form.player_id.data = player_id
        form.temporada.data = request.args.get("temporada") or jogadores[player_id]["temporada"]
    if form.validate_on_submit():
        servico.registrar(
            player_id=form.player_id.data, nome=jogadores[form.player_id.data]["player"],
            temporada=form.temporada.data, autor=form.autor.data,
            nota=form.nota.data, texto=form.texto.data,
        )
        flash("Observação gravada.", "sucesso")
        return redirect(url_for("scout.lista", jogador=form.player_id.data), 303)
    try:
        jogador = jogadores.get(int(form.player_id.data))
    except (TypeError, ValueError):
        jogador = None
    status = 400 if request.method == "POST" else 200
    return render_template("observacao_nova.html", pagina="observacoes", form=form, jogador=jogador), status


@scout_bp.post("/<int:observacao_id>/excluir")
def excluir(observacao_id: int):
    if not servico.excluir(observacao_id):
        abort(404)
    flash("Observação excluída.", "sucesso")
    # Volta para a lista do mesmo jogador, se a exclusão partiu dela.
    return redirect(url_for("scout.lista", jogador=request.form.get("jogador", type=int)), 303)
