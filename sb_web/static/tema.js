(function () {
  "use strict";

  const CHAVE = "scoutboard-tema";
  const raiz = document.documentElement;
  const botao = document.getElementById("alternar-tema");
  const escuroDoSistema = window.matchMedia("(prefers-color-scheme: dark)");

  // Tema em uso agora: a escolha salva ou, sem escolha, o do sistema.
  function temaAtual() {
    if (raiz.dataset.theme) return raiz.dataset.theme;
    return escuroDoSistema.matches ? "dark" : "light";
  }

  function atualizarBotao() {
    const proximo = temaAtual() === "dark" ? "claro" : "escuro";
    botao.setAttribute("aria-label", `Alternar para o modo ${proximo}`);
    botao.title = `Modo ${proximo}`;
  }

  function alternar() {
    const novo = temaAtual() === "dark" ? "light" : "dark";
    raiz.setAttribute("data-theme", novo);
    try {
      localStorage.setItem(CHAVE, novo === "dark" ? "escuro" : "claro");
    } catch (erro) { /* sem armazenamento: o tema vale só nesta página */ }
    atualizarBotao();
    // Gráficos que dependem das cores do tema se redesenham.
    window.dispatchEvent(new Event("tema-mudou"));
  }

  if (!botao) return;
  botao.addEventListener("click", alternar);
  // Quem não escolheu tema segue a mudança do sistema operacional.
  escuroDoSistema.addEventListener("change", atualizarBotao);
  atualizarBotao();
})();
