(function () {
  "use strict";

  const CAMPOS = ["temporada", "jogo", "time", "jogador", "x", "y"];
  const DEFAULTS = { x: "finalizacoes", y: "passes_certos" };
  const estado = {};
  let ultimoDado = null;
  let cliqueLigado = false;

  const $ = (id) => document.getElementById(id);

  function esc(valor) {
    return String(valor ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // Imagem externa por cima da reserva (mesma regra do _macros.html): a reserva aparece enquanto
  // carrega, some quando a imagem chega e volta se a imagem falhar.
  function imagemHtml(src) {
    if (!src) return "";
    return `<img src="${esc(src)}" alt="" loading="lazy" onload="this.parentNode.classList.add('com-imagem')" onerror="this.remove()">`;
  }

  // Foto do jogador sobre as iniciais.
  function avatarHtml(nome, foto) {
    const iniciais = String(nome || "?").slice(0, 2).toUpperCase();
    return `<span class="avatar avatar-sm avatar-iniciais" aria-hidden="true">${esc(iniciais)}${imagemHtml(foto)}</span>`;
  }

  // Escudo do time sobre um distintivo com a sigla e uma cor fixa por time.
  function escudoHtml(time, src, teamId) {
    const cor = `hsl(${((Number(teamId) || 0) * 47) % 360} 55% 38%)`;
    const sigla = String(time || "?").slice(0, 3).toUpperCase();
    return `<span class="escudo escudo-gerado" style="--cor:${cor}" aria-hidden="true">${esc(sigla)}${imagemHtml(src)}</span>`;
  }

  function lerUrl() {
    const params = new URLSearchParams(window.location.search);
    CAMPOS.forEach((campo) => {
      estado[campo] = params.get(campo) || DEFAULTS[campo] || "";
    });
  }

  function gravarUrl() {
    const params = new URLSearchParams();
    CAMPOS.forEach((campo) => {
      const valor = estado[campo];
      if (valor && valor !== DEFAULTS[campo]) params.set(campo, valor);
    });
    const query = params.toString();
    history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }

  function preencherSelect(select, itens, valorAtual, rotuloVazio) {
    const opcoes = [];
    if (rotuloVazio !== undefined) {
      opcoes.push(`<option value="">${esc(rotuloVazio)}</option>`);
    }
    itens.forEach((item) => {
      const selecionado = String(item.valor) === String(valorAtual) ? " selected" : "";
      opcoes.push(`<option value="${esc(item.valor)}"${selecionado}>${esc(item.rotulo)}</option>`);
    });
    select.innerHTML = opcoes.join("");
  }

  function mostrarErro(mensagem) {
    const p = $("erro");
    p.textContent = mensagem || "";
    p.hidden = !mensagem;
  }

  async function carregar(tentativa = 0) {
    const params = new URLSearchParams();
    CAMPOS.forEach((campo) => {
      if (estado[campo]) params.set(campo, estado[campo]);
    });
    let dados;
    try {
      const resposta = await fetch(`/api/painel?${params.toString()}`);
      dados = await resposta.json();
      if (!resposta.ok) {
        // Filtro inválido (ex.: jogador de outra temporada, vindo de um link antigo):
        // limpa os filtros dependentes e tenta de novo, uma única vez.
        if (tentativa === 0 && (estado.jogo || estado.time || estado.jogador)) {
          Object.assign(estado, { jogo: "", time: "", jogador: "" });
          gravarUrl();
          return carregar(1);
        }
        mostrarErro(dados.erro);
        return;
      }
    } catch (erro) {
      mostrarErro("Não foi possível carregar os dados. Verifique o servidor.");
      return;
    }
    mostrarErro("");
    try {
      render(dados);
    } catch (erro) {
      console.error(erro);
      mostrarErro("Erro ao montar a tela. Veja o console para detalhes.");
    }
  }

  function render(d) {
    preencherControles(d.opcoes);
    renderResumo(d);
    renderDetalheJogador(d.jogador);
    renderTreinador(d.treinador);
    renderDispersao(d);
    renderCampo(d.posicoes, d.jogador);
  }

  function preencherControles(opcoes) {
    if (!estado.temporada) estado.temporada = opcoes.temporadas[opcoes.temporadas.length - 1];
    preencherSelect(
      $("temporada"),
      opcoes.temporadas.map((t) => ({ valor: t, rotulo: t })).reverse(),
      estado.temporada
    );
    preencherSelect(
      $("jogo"),
      opcoes.jogos.map((j) => ({ valor: j.game_id, rotulo: j.rotulo })),
      estado.jogo,
      "Todos os jogos"
    );
    preencherSelect(
      $("time"),
      opcoes.times.map((t) => ({ valor: t.team_id, rotulo: t.time })),
      estado.time,
      "Todos os times"
    );
    preencherSelect(
      $("jogador"),
      opcoes.jogadores.map((j) => ({ valor: j.player_id, rotulo: `${j.player} (${j.time})` })),
      estado.jogador,
      "Todos os jogadores"
    );
    const metricas = Object.entries(opcoes.metricas).map(([valor, rotulo]) => ({ valor, rotulo }));
    preencherSelect($("eixo-x"), metricas, estado.x);
    preencherSelect($("eixo-y"), metricas, estado.y);
  }

  function renderResumo(d) {
    const jogos = d.opcoes.jogos.length;
    const jogadores = d.opcoes.jogadores.length;
    $("resumo").textContent =
      `Temporada ${d.filtros.temporada} · ${jogos} jogos · ${jogadores} jogadores no recorte`;
  }

  function renderDetalheJogador(jogador) {
    const cartao = $("detalhe-jogador");
    if (!jogador) {
      cartao.hidden = true;
      cartao.innerHTML = "";
      return;
    }
    cartao.hidden = false;
    cartao.innerHTML = `
      <div class="premio-quem">
        ${avatarHtml(jogador.player, jogador.foto)}
        <div>
          <h2>${esc(jogador.player)}</h2>
          <p class="apoio">${escudoHtml(jogador.time, jogador.escudo, jogador.team_id)} ${esc(jogador.time)}</p>
        </div>
      </div>
      <p class="apoio">${jogador.jogos} jogos · ${Math.round(jogador.minutos)} min estimados</p>
      <p class="apoio">Gols ${jogador.gols} · Passes certos ${jogador.passes_certos} · Desarmes ${jogador.desarmes}
      · Interceptações ${jogador.interceptacoes} · Finalizações ${jogador.finalizacoes}</p>
      ${percentisHtml(jogador.percentis)}`;
  }

  // Cartão do jogador: cada métrica por 90 minutos e o percentil dela na temporada.
  function percentisHtml(percentis) {
    if (!percentis || !percentis.length) return "";
    const linhas = percentis
      .map((p) => `
        <li class="percentil percentil-${p.percentil >= 67 ? "alto" : p.percentil >= 34 ? "medio" : "baixo"}">
          <span class="percentil-rotulo">${esc(p.rotulo)}</span>
          <span class="percentil-valor">${String(p.por_90).replace(".", ",")}</span>
          <span class="percentil-barra" role="img" aria-label="Percentil ${p.percentil}"><span style="width:${p.percentil}%"></span></span>
          <span class="percentil-numero">${p.percentil}</span>
        </li>`)
      .join("");
    return `
      <h3 class="percentis-titulo">Por 90 minutos e percentil na temporada</h3>
      <ul class="percentis">${linhas}</ul>
      <p class="apoio">Comparado com quem jogou pelo menos 450 minutos na temporada.</p>`;
  }

  function renderTreinador(treinador) {
    const cartao = $("treinador");
    // Sem time ou jogador selecionado, o cartão some em vez de ocupar espaço vazio.
    cartao.hidden = !treinador;
    if (!treinador) {
      cartao.innerHTML = "";
      return;
    }
    const historico = treinador.historico
      .slice()
      .reverse()
      .map((h) => `<li>${esc(h.treinador)} · ${esc(h.inicio || "?")} a ${esc(h.fim || "atual")}</li>`)
      .join("");
    const outra = treinador.outra_fonte
      ? `<p class="aviso">${esc(treinador.outra_fonte.fonte)} indica <strong>${esc(treinador.outra_fonte.treinador)}</strong>. Confira qual está mais recente.</p>`
      : "";
    cartao.innerHTML = `
      <h2>Perfil do treinador</h2>
      <p class="apoio">${esc(treinador.time)}</p>
      <p class="treinador-atual">${treinador.atual ? avatarHtml(treinador.atual, treinador.foto) : ""}<span>${esc(treinador.atual || "Sem técnico atual registrado")}</span></p>
      <p class="apoio">Fonte: ${esc(treinador.fonte || "Wikidata")}.</p>
      ${outra}
      <ul class="historico">${historico}</ul>`;
  }

  // Cor de um token do CSS, para o gráfico acompanhar o tema claro ou escuro.
  function corDoTema(token) {
    return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  }

  function renderDispersao(d) {
    if (typeof Plotly === "undefined") {
      $("grafico-dispersao").innerHTML =
        '<p class="apoio">Gráfico indisponível: a biblioteca Plotly não foi carregada.</p>';
      return;
    }
    ultimoDado = d;
    const pontos = d.dispersao;
    const eixo = corDoTema("--eixo");
    const texto = corDoTema("--texto");
    const grade = corDoTema("--grade");
    const rotuloX = d.opcoes.metricas[d.filtros.x];
    const rotuloY = d.opcoes.metricas[d.filtros.y];
    const trace = {
      type: "scatter",
      mode: "markers",
      x: pontos.map((p) => p.x),
      y: pontos.map((p) => p.y),
      text: pontos.map((p) => `${p.player} (${p.time})`),
      hovertemplate: `%{text}<br>${esc(rotuloX)}: %{x:.2f}<br>${esc(rotuloY)}: %{y:.2f}<extra></extra>`,
      marker: { size: 9, color: corDoTema("--ponto"), opacity: 0.8 },
    };
    const destaque = d.jogador && pontos.find((p) => p.player_id === d.jogador.player_id);
    const traces = [trace];
    if (destaque) {
      traces.push({
        type: "scatter",
        mode: "markers+text",
        x: [destaque.x],
        y: [destaque.y],
        text: [destaque.player],
        textposition: "top center",
        hoverinfo: "skip",
        marker: { size: 16, color: corDoTema("--amarelo"), line: { color: corDoTema("--placar"), width: 1 } },
      });
    }
    const eixoEstilo = { title: { font: { color: eixo } }, zeroline: false, gridcolor: grade, linecolor: grade, tickfont: { color: eixo } };
    const layout = {
      margin: { l: 56, r: 16, t: 16, b: 52 },
      font: { family: "Geist, Segoe UI, sans-serif", color: texto, size: 13 },
      xaxis: { ...eixoEstilo, title: { text: rotuloX, font: { color: eixo } } },
      yaxis: { ...eixoEstilo, title: { text: rotuloY, font: { color: eixo } } },
      showlegend: false,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      hoverlabel: { font: { family: "Geist, Segoe UI, sans-serif" } },
    };
    Plotly.react("grafico-dispersao", traces, layout, { responsive: true, displaylogo: false });
    if (!cliqueLigado) {
      // Ligado uma única vez: o Plotly reaproveita o mesmo elemento a cada redesenho.
      cliqueLigado = true;
      $("grafico-dispersao").on("plotly_click", (evento) => {
        const ponto = evento.points[0];
        // Só a camada dos jogadores (0) tem índice na lista; a do jogador destacado não.
        if (ponto.curveNumber !== 0) return;
        const jogadorClicado = ultimoDado.dispersao[ponto.pointNumber];
        if (jogadorClicado) selecionarJogador(jogadorClicado.player_id);
      });
    }
  }

  function renderCampo(posicoes, jogador) {
    const svg = $("campo");
    const linhas = [
      '<rect x="0" y="0" width="105" height="68" class="linha"/>',
      '<line x1="52.5" y1="0" x2="52.5" y2="68" class="linha"/>',
      '<circle cx="52.5" cy="34" r="9.15" class="linha"/>',
      '<rect x="0" y="13.84" width="16.5" height="40.32" class="linha"/>',
      '<rect x="88.5" y="13.84" width="16.5" height="40.32" class="linha"/>',
    ].join("");
    const pontos = posicoes
      .filter((p) => !jogador || p.player_id !== jogador.player_id)
      .map((p) => `<circle class="ponto" cx="${p.posicao_x}" cy="${p.posicao_y}" r="1.1"
        data-id="${p.player_id}"><title>${esc(p.player)} (${esc(p.time)})</title></circle>`)
      .join("");
    const destaque = jogador && posicoes.find((p) => p.player_id === jogador.player_id);
    const marcado = destaque
      ? `<circle class="ponto-destaque" cx="${destaque.posicao_x}" cy="${destaque.posicao_y}" r="2.2">
           <title>${esc(destaque.player)}</title></circle>`
      : "";
    svg.innerHTML = linhas + pontos + marcado;
    svg.querySelectorAll("circle.ponto").forEach((c) => {
      c.addEventListener("click", () => selecionarJogador(Number(c.dataset.id)));
    });
  }

  function selecionarJogador(id) {
    estado.jogador = String(id);
    gravarUrl();
    carregar();
  }

  function ligarEventos() {
    $("temporada").addEventListener("change", (e) => {
      Object.assign(estado, { temporada: e.target.value, jogo: "", time: "", jogador: "" });
      gravarUrl();
      carregar();
    });
    // Time e jogador escolhidos antes podem não estar no jogo novo: saem, e o jogo escolhido fica.
    $("jogo").addEventListener("change", (e) => {
      Object.assign(estado, { jogo: e.target.value, time: "", jogador: "" });
      gravarUrl();
      carregar();
    });
    $("time").addEventListener("change", (e) => {
      Object.assign(estado, { time: e.target.value, jogador: "" });
      gravarUrl();
      carregar();
    });
    $("jogador").addEventListener("change", (e) => { estado.jogador = e.target.value; gravarUrl(); carregar(); });
    $("eixo-x").addEventListener("change", (e) => { estado.x = e.target.value; gravarUrl(); carregar(); });
    $("eixo-y").addEventListener("change", (e) => { estado.y = e.target.value; gravarUrl(); carregar(); });
    $("limpar").addEventListener("click", () => {
      Object.assign(estado, { jogo: "", time: "", jogador: "" });
      gravarUrl();
      carregar();
    });
  }

  lerUrl();
  ligarEventos();
  carregar();
  window.addEventListener("tema-mudou", () => {
    if (ultimoDado) renderDispersao(ultimoDado);
  });
})();
