"""Modal de confirmação (substitui window.confirm).

O comportamento do modal no navegador (abrir, Esc, foco, envio com CSRF) é
validado no Chrome por um roteiro separado; aqui ficam as garantias do servidor
e do JavaScript.
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.financeiro import servicos

ESTATICOS = Path(settings.BASE_DIR) / "static"


def js():
    return (ESTATICOS / "js" / "app.js").read_text(encoding="utf-8")


class ModalNasPaginasTests(f.Cenario):
    def test_layout_tem_modal_acessivel(self):
        self.entrar(self.adv)
        pagina = self.client.get(reverse("core:painel"))
        self.assertContains(pagina, '<dialog class="modal" id="modal-confirmacao"', count=1)
        self.assertContains(pagina, 'aria-labelledby="modal-confirmacao-titulo"')
        self.assertContains(pagina, 'aria-describedby="modal-confirmacao-mensagem"')
        self.assertContains(pagina, '<form method="dialog"')
        self.assertContains(pagina, "data-modal-voltar autofocus")  # foco inicial na opção segura

    def test_cancelar_compromisso_pede_confirmacao_e_concluir_nao(self):
        comp = f.compromisso(self.adv, self.proc, titulo="Audiência fictícia")
        self.entrar(self.adv)
        for url in (reverse("agenda:lista"), comp.get_absolute_url()):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                cancelar = re.search(r'<button[^>]*value="cancelado"[^>]*>', html, re.S).group(0)
                concluir = re.search(r'<button[^>]*value="concluido"[^>]*>', html, re.S).group(0)
                self.assertIn("data-confirmar=", cancelar)
                self.assertIn('data-confirmar-titulo="Cancelar compromisso"', cancelar)
                self.assertNotIn("data-confirmar", concluir)

    def test_operacoes_relevantes_tem_confirmacao(self):
        f.autorizar_cliente(self.ast, self.cli)
        hora = f.registro_hora(self.adv, self.proc, minutos=60)
        lanc = servicos.converter_horas(administrador=self.adm, processo=self.proc, registros=[hora],
                                        valor=Decimal("100.00"), descricao="Honorários fictícios",
                                        vencimento=date(2026, 12, 1))
        f.registro_hora(self.adv, self.proc, minutos=30)  # horas livres para a tela de cobrança
        self.entrar(self.adm)
        paginas = {
            "arquivar cliente": (self.cli.get_absolute_url(), 'data-confirmar-titulo="Arquivar cliente"'),
            "arquivar processo": (self.proc.get_absolute_url(), 'data-confirmar-titulo="Arquivar processo"'),
            "gerar cobrança": (reverse("financeiro:cobrar_horas") + f"?processo={self.proc.pk}",
                               'data-confirmar-titulo="Gerar cobrança"'),
            "quitar": (lanc.get_absolute_url(), 'data-confirmar-titulo="Quitar lançamento"'),
            "cancelar lançamento": (lanc.get_absolute_url(), 'data-confirmar-titulo="Cancelar lançamento"'),
            "redefinir senha": (reverse("gestao_usuarios:lista"), 'data-confirmar-titulo="Redefinir senha"'),
        }
        for nome, (url, atributo) in paginas.items():
            with self.subTest(operacao=nome):
                resposta = self.client.get(url)
                self.assertContains(resposta, atributo)
                self.assertContains(resposta, "csrfmiddlewaretoken")  # o formulário mantém o CSRF

    def test_desativacao_de_usuario_confirma_somente_conta_ativa(self):
        self.entrar(self.adm)
        ativo = self.client.get(reverse("gestao_usuarios:editar", args=[self.ast.pk]))
        self.assertContains(ativo, 'data-confirmar-se-desmarcar="ativo"')
        self.assertContains(ativo, 'data-confirmar-titulo="Desativar usuário"')
        self.ast.ativo = False
        self.ast.save(update_fields=["ativo"])
        inativo = self.client.get(reverse("gestao_usuarios:editar", args=[self.ast.pk]))
        self.assertNotContains(inativo, "data-confirmar")

    def test_desativacao_continua_funcionando_no_servidor(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("gestao_usuarios:editar", args=[self.ast.pk]),
                                    {"nome": self.ast.nome, "email": self.ast.email, "perfil": self.ast.perfil})
        self.assertRedirects(resposta, reverse("gestao_usuarios:lista"))
        self.ast.refresh_from_db()
        self.assertFalse(self.ast.ativo)

    def test_outros_formularios_genericos_nao_ganham_confirmacao(self):
        self.entrar(self.adm)
        for url in (reverse("clientes:novo"), reverse("processos:novo"), reverse("gestao_usuarios:novo")):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "data-confirmar")


class ConfirmacaoJsTests(SimpleTestCase):
    def test_js_usa_modal_e_preserva_botao_e_csrf(self):
        codigo = js()
        self.assertIn("showModal()", codigo)
        self.assertIn("requestSubmit(", codigo)       # reenvia o mesmo form (CSRF e botão)
        self.assertIn("evento.submitter", codigo)
        # window.confirm só como alternativa para navegadores sem <dialog>.
        self.assertEqual(codigo.count("window.confirm("), 1)
        self.assertIn('typeof modal.showModal === "function"', codigo)
