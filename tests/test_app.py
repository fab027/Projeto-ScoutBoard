def test_pagina_inicial_carrega_com_logo_e_secoes(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Painel do Brasileirão" in corpo
    assert "logo.svg" in corpo
    assert 'id="campo"' in corpo


def test_plotly_e_servido_localmente(cliente):
    """O gráfico não pode depender de CDN externo: a página referencia o Plotly do próprio projeto."""
    corpo = cliente.get("/").get_data(as_text=True)
    assert "cdnjs.cloudflare.com" not in corpo
    resposta = cliente.get("/static/vendor/plotly-2.35.2.min.js")
    assert resposta.status_code == 200
    assert b"plotly.js v2.35.2" in resposta.get_data()[:200]


def test_api_painel_padrao_usa_temporada_mais_recente(cliente):
    resposta = cliente.get("/api/painel")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["filtros"]["temporada"] == "2025"
    assert set(dados) == {"filtros", "opcoes", "dispersao", "posicoes", "treinador", "jogador"}
    assert len(dados["opcoes"]["times"]) == 20
    assert len(dados["opcoes"]["jogos"]) == 380


def test_api_painel_aceita_filtros(cliente):
    time = cliente.get("/api/painel?temporada=2025").get_json()["opcoes"]["times"][0]["team_id"]
    dados = cliente.get(f"/api/painel?temporada=2025&time={time}&x=gols&y=desarmes").get_json()
    assert dados["filtros"]["time"] == time
    assert dados["filtros"]["x"] == "gols"
    assert all(t["team_id"] == time for t in dados["opcoes"]["times"][:1])


def test_api_painel_devolve_400_para_entrada_invalida(cliente):
    resposta = cliente.get("/api/painel?temporada=1999")
    assert resposta.status_code == 400
    assert "erro" in resposta.get_json()
    assert cliente.get("/api/painel?x=inexistente").status_code == 400
