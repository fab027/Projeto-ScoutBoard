"""Observações de scout: formulário validado no servidor e gravação pelo ORM."""
import pytest

from sb_web import create_app, rotas
from sb_web.campeonato.models import Player
from sb_web.ext.db import db
from sb_web.scout import servico
from sb_web.scout.models import Observacao


@pytest.fixture
def jogador():
    """Um jogador real da base: (player_id, nome, última temporada)."""
    linha = rotas.dados().ultimos.iloc[0]
    return int(linha.player_id), linha.player, linha.temporada


def envio(jogador, **trocas):
    player_id, _, temporada = jogador
    return {"player_id": player_id, "temporada": temporada, "autor": "Ana Scout", "nota": 8,
            "texto": "Boa leitura de jogo e passe vertical.", **trocas}


def gravadas(cliente):
    with cliente.application.app_context():
        return list(db.session.scalars(db.select(Observacao)))


def test_lista_vazia_responde_200(cliente):
    resposta = cliente.get("/observacoes/")
    assert resposta.status_code == 200
    assert "Nenhuma observação ainda." in resposta.get_data(as_text=True)


def test_formulario_abre_com_o_jogador_escolhido(cliente, jogador):
    player_id, nome, temporada = jogador
    corpo = cliente.get(f"/observacoes/nova?jogador={player_id}").get_data(as_text=True)
    assert nome in corpo
    assert f'name="player_id" type="hidden" value="{player_id}"' in corpo
    assert f'<option selected value="{temporada}">' in corpo


def test_formulario_sem_jogador_manda_escolher_na_lista(cliente):
    resposta = cliente.get("/observacoes/nova")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/jogadores")
    assert cliente.get("/observacoes/nova?jogador=-1").status_code == 404


def test_envio_valido_grava_jogador_e_observacao(cliente, jogador):
    player_id, nome, temporada = jogador
    resposta = cliente.post("/observacoes/nova", data=envio(jogador, autor="  Ana Scout  "))
    assert resposta.status_code == 303
    assert resposta.headers["Location"].endswith(f"/observacoes/?jogador={player_id}")

    with cliente.application.app_context():
        observacao = db.session.scalars(db.select(Observacao)).one()
        assert (observacao.player_id, observacao.temporada, observacao.nota) == (player_id, temporada, 8)
        assert observacao.autor == "Ana Scout"  # espaços das pontas saem
        assert observacao.jogador.player == nome  # o jogador entrou na tabela `jogadores`
        assert observacao.criado_em is not None

    corpo = cliente.get(resposta.headers["Location"]).get_data(as_text=True)
    assert "Observação gravada." in corpo
    assert "Boa leitura de jogo e passe vertical." in corpo


def test_segunda_observacao_reaproveita_o_jogador(cliente, jogador):
    cliente.post("/observacoes/nova", data=envio(jogador, nota=6))
    cliente.post("/observacoes/nova", data=envio(jogador, nota=9))
    with cliente.application.app_context():
        assert db.session.scalar(db.select(db.func.count(Player.player_id))) == 1
        resumo = servico.resumo_por_jogador()
    assert resumo == [{"player_id": jogador[0], "player": jogador[1], "observacoes": 2, "media": 7.5}]
    assert "7.5" in cliente.get("/observacoes/").get_data(as_text=True)


@pytest.mark.parametrize("trocas, mensagem", [
    ({"autor": ""}, "Informe seu nome."),
    ({"autor": "A"}, "Use de 2 a 60 caracteres."),
    ({"nota": ""}, "Dê uma nota."),
    ({"nota": 0}, "A nota vai de 1 a 10."),
    ({"nota": 11}, "A nota vai de 1 a 10."),
    ({"texto": "curto"}, "Escreva de 10 a 1000 caracteres."),
    ({"texto": "x" * 1001}, "Escreva de 10 a 1000 caracteres."),
    ({"temporada": "1999"}, "Temporada inválida."),
    ({"player_id": -1}, "Jogador não encontrado na base."),
    ({"player_id": "abc"}, "Jogador inválido."),
])
def test_envio_invalido_devolve_400_com_o_erro_e_nao_grava(cliente, jogador, trocas, mensagem):
    resposta = cliente.post("/observacoes/nova", data=envio(jogador, **trocas))
    assert resposta.status_code == 400
    assert mensagem in resposta.get_data(as_text=True)
    assert gravadas(cliente) == []


def test_envio_invalido_mantem_o_que_foi_digitado(cliente, jogador):
    corpo = cliente.post("/observacoes/nova", data=envio(jogador, nota=99)).get_data(as_text=True)
    assert 'value="Ana Scout"' in corpo
    assert "Boa leitura de jogo e passe vertical." in corpo
    assert 'aria-invalid="true"' in corpo


def test_texto_e_escapado_na_pagina(cliente, jogador):
    cliente.post("/observacoes/nova", data=envio(jogador, texto="<script>alert(1)</script> perigoso"))
    corpo = cliente.get("/observacoes/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in corpo
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in corpo


def test_filtro_por_jogador_e_jogador_inexistente(cliente, jogador):
    outro = rotas.dados().ultimos.iloc[1]
    cliente.post("/observacoes/nova", data=envio(jogador))
    vazio = cliente.get(f"/observacoes/?jogador={int(outro.player_id)}").get_data(as_text=True)
    assert "Nenhuma observação ainda." in vazio
    assert cliente.get("/observacoes/?jogador=-1").status_code == 404


def test_excluir_apaga_e_volta_para_a_lista(cliente, jogador):
    cliente.post("/observacoes/nova", data=envio(jogador))
    observacao_id = gravadas(cliente)[0].id
    resposta = cliente.post(f"/observacoes/{observacao_id}/excluir", data={"jogador": jogador[0]})
    assert resposta.status_code == 303
    assert resposta.headers["Location"].endswith(f"/observacoes/?jogador={jogador[0]}")
    assert gravadas(cliente) == []
    assert cliente.post(f"/observacoes/{observacao_id}/excluir").status_code == 404
    assert cliente.get(f"/observacoes/{observacao_id}/excluir").status_code == 405


def test_sem_token_csrf_o_envio_e_recusado(jogador):
    cliente = create_app(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://").test_client()
    resposta = cliente.post("/observacoes/nova", data=envio(jogador))
    assert resposta.status_code == 400
    assert "O formulário expirou" in resposta.get_data(as_text=True)
    assert gravadas(cliente) == []
    assert cliente.post("/observacoes/1/excluir").status_code == 400


def test_jogadores_tem_link_para_anotar(cliente):
    corpo = cliente.get("/jogadores").get_data(as_text=True)
    assert "/observacoes/nova?jogador=" in corpo


def test_pagina_de_erro_404_no_padrao_do_site_e_json_na_api(cliente):
    resposta = cliente.get("/nao-existe")
    assert resposta.status_code == 404
    corpo = resposta.get_data(as_text=True)
    assert "Página não encontrada" in corpo and "logo.svg" in corpo
    api = cliente.get("/api/nao-existe")
    assert api.status_code == 404 and "erro" in api.get_json()


def test_configuracao_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    monkeypatch.setenv("SECRET_KEY", "chave-do-ambiente")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    app = create_app(SQLALCHEMY_DATABASE_URI="sqlite://")
    assert app.debug is True
    assert app.config["SECRET_KEY"] == "chave-do-ambiente"
    assert app.config["LOG_LEVEL"] == "WARNING"
    monkeypatch.delenv("FLASK_DEBUG")
    assert create_app(SQLALCHEMY_DATABASE_URI="sqlite://").debug is False
