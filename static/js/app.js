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
})();
