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

  // Tema claro (padrão) ou escuro. A preferência fica somente no navegador
  // (localStorage); o tema salvo é aplicado no <head>, antes da pintura.
  var CHAVE_TEMA = "jusgestor-tema";
  var raiz = document.documentElement;
  var botoesTema = document.querySelectorAll("[data-alternar-tema]");

  function temaAtual() {
    return raiz.getAttribute("data-tema") === "escuro" ? "escuro" : "claro";
  }

  function aplicarTema(tema) {
    if (tema === "escuro") raiz.setAttribute("data-tema", "escuro");
    else raiz.removeAttribute("data-tema");
    botoesTema.forEach(function (botao) {
      botao.setAttribute("aria-pressed", tema === "escuro" ? "true" : "false");
    });
  }

  function salvarTema(tema) {
    try {
      if (tema === "escuro") window.localStorage.setItem(CHAVE_TEMA, "escuro");
      else window.localStorage.removeItem(CHAVE_TEMA);
    } catch (e) { /* armazenamento indisponível: vale só para esta página */ }
  }

  botoesTema.forEach(function (botao) {
    botao.hidden = false;
    botao.addEventListener("click", function () {
      var novo = temaAtual() === "escuro" ? "claro" : "escuro";
      aplicarTema(novo);
      salvarTema(novo);
    });
  });
  aplicarTema(temaAtual());

  // Mantém outras abas abertas do sistema no mesmo tema.
  window.addEventListener("storage", function (evento) {
    if (evento.key === CHAVE_TEMA || evento.key === null) {
      aplicarTema(evento.newValue === "escuro" ? "escuro" : "claro");
    }
  });

  // Confirmação antes de ações relevantes (cobrar, quitar, cancelar, arquivar,
  // redefinir senha, desativar usuário), em um modal acessível (<dialog>).
  //
  // Atributos, no <form> ou no botão de envio (o do botão tem prioridade):
  //   data-confirmar="mensagem"         ativa a confirmação
  //   data-confirmar-titulo="..."       título do modal (padrão: "Confirmar ação")
  //   data-confirmar-botao="..."        texto do botão de confirmação (padrão: texto do botão clicado)
  //   data-confirmar-perigo             botão de confirmação em vermelho (também para .botao--perigo)
  //   data-confirmar-se-desmarcar="x"   (no form) só confirma se a caixa "x", antes marcada, foi desmarcada
  //
  // O envio confirmado é o mesmo formulário, com o mesmo token CSRF e o mesmo
  // botão (nome/valor) que o usuário escolheu.
  var modal = document.getElementById("modal-confirmacao");
  var pendente = null;

  function precisaConfirmar(form, botao) {
    if (botao && botao.hasAttribute("data-confirmar")) return botao;
    if (!form.hasAttribute("data-confirmar")) return null;
    var nomeCampo = form.getAttribute("data-confirmar-se-desmarcar");
    if (nomeCampo) {
      var campo = form.elements[nomeCampo];
      if (!campo || !campo.defaultChecked || campo.checked) return null;
    }
    return form;
  }

  function reenviar(form, botao) {
    form.setAttribute("data-confirmado", "1");
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit(botao && botao.form === form ? botao : undefined);
      return;
    }
    if (botao && botao.name) {
      var oculto = document.createElement("input");
      oculto.type = "hidden";
      oculto.name = botao.name;
      oculto.value = botao.value;
      form.appendChild(oculto);
    }
    form.submit();
  }

  function abrirModal(form, botao, origem) {
    var mensagem = origem.getAttribute("data-confirmar");
    var titulo = origem.getAttribute("data-confirmar-titulo") || "Confirmar ação";
    var textoBotao = origem.getAttribute("data-confirmar-botao")
      || (botao && botao.textContent.trim()) || "Confirmar";
    var perigo = origem.hasAttribute("data-confirmar-perigo")
      || (botao && botao.classList.contains("botao--perigo"));
    var confirmar = modal.querySelector("[data-modal-confirmar]");

    modal.querySelector("#modal-confirmacao-titulo").textContent = titulo;
    modal.querySelector("#modal-confirmacao-mensagem").textContent = mensagem;
    confirmar.textContent = textoBotao;
    confirmar.classList.toggle("botao--perigo-cheio", !!perigo);
    confirmar.classList.toggle("botao--primario", !perigo);

    pendente = { form: form, botao: botao, foco: document.activeElement };
    modal.returnValue = "";
    modal.showModal();  // foco inicial no botão "Voltar" (autofocus): opção mais segura
  }

  if (modal && typeof modal.showModal === "function") {
    modal.addEventListener("close", function () {
      var acao = pendente;
      pendente = null;
      if (!acao) return;
      if (modal.returnValue === "confirmar") {
        reenviar(acao.form, acao.botao);
      } else if (acao.foco && typeof acao.foco.focus === "function") {
        acao.foco.focus();  // devolve o foco a quem abriu o modal
      }
    });
    // Clique no fundo escurecido equivale a "Voltar".
    modal.addEventListener("click", function (evento) {
      if (evento.target === modal) modal.close("voltar");
    });
  }

  document.addEventListener("submit", function (evento) {
    var form = evento.target;
    if (!(form instanceof HTMLFormElement) || form.getAttribute("method") === "dialog") return;
    if (form.getAttribute("data-confirmado") === "1") {
      form.removeAttribute("data-confirmado");
      return;  // envio já confirmado
    }
    var botao = evento.submitter || null;
    var origem = precisaConfirmar(form, botao);
    if (!origem) return;
    evento.preventDefault();
    if (modal && typeof modal.showModal === "function") {
      abrirModal(form, botao, origem);
    } else if (window.confirm(origem.getAttribute("data-confirmar"))) {
      // Somente navegadores sem suporte a <dialog> (Chrome e Firefox atuais têm).
      reenviar(form, botao);
    }
  });

  // Impressão em PDF pelo navegador (RF08).
  document.addEventListener("click", function (evento) {
    if (evento.target.closest && evento.target.closest("[data-imprimir]")) {
      window.print();
    }
  });
})();
