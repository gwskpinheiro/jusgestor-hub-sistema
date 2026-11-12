// JusGestor Hub — interações da interface.
// O sistema funciona sem JavaScript; aqui ficam apenas melhorias de uso.
(function () {
  "use strict";

  // Abre/fecha o menu lateral em telas estreitas (RNF06).
  var botoes = document.querySelectorAll("[data-alternar-menu]");
  var botaoPrincipal = document.querySelector("button[data-alternar-menu]");
  var fundo = document.querySelector(".fundo-menu");

  function definirMenu(aberto) {
    document.body.classList.toggle("menu-aberto", aberto);
    if (botaoPrincipal) botaoPrincipal.setAttribute("aria-expanded", aberto ? "true" : "false");
    if (fundo) fundo.hidden = !aberto;
  }

  botoes.forEach(function (botao) {
    botao.addEventListener("click", function () {
      definirMenu(!document.body.classList.contains("menu-aberto"));
    });
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && document.body.classList.contains("menu-aberto")) {
      definirMenu(false);
    }
  });

  // Confirmação antes de ações relevantes (arquivar, cancelar, redefinir senha).
  document.addEventListener("submit", function (evento) {
    var mensagem = evento.target.getAttribute("data-confirmar");
    if (mensagem && !window.confirm(mensagem)) {
      evento.preventDefault();
    }
  });

  // Impressão em PDF pelo navegador (RF08).
  document.addEventListener("click", function (evento) {
    if (evento.target.closest && evento.target.closest("[data-imprimir]")) {
      window.print();
    }
  });
})();
