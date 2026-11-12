"""RF03 — clientes (RN01, RN07, RN08)."""
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.clientes.models import AcessoCliente, Cliente
from apps.core.tests import fabrica as f


class ClientesTests(f.Cenario):
    def test_ast_cadastra_cliente_e_recebe_acesso(self):
        self.entrar(self.ast)
        resposta = self.client.post(reverse("clientes:novo"), {"nome": "Novo Cliente Fictício", "cpf_cnpj": "123.456.789-01"})
        novo = Cliente.objects.get(nome="Novo Cliente Fictício")
        self.assertRedirects(resposta, novo.get_absolute_url())
        self.assertEqual(novo.cpf_cnpj, "12345678901")
        self.assertTrue(AcessoCliente.objects.filter(usuario=self.ast, cliente=novo).exists())

    def test_adm_cadastra_sem_criar_acesso_explicito(self):
        self.entrar(self.adm)
        self.client.post(reverse("clientes:novo"), {"nome": "Cliente do ADM"})
        self.assertFalse(AcessoCliente.objects.filter(cliente__nome="Cliente do ADM").exists())

    def test_cpf_cnpj_com_tamanho_invalido(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("clientes:novo"), {"nome": "X", "cpf_cnpj": "123"})
        self.assertContains(resposta, "CPF (11 dígitos) ou um CNPJ (14 dígitos)")

    def test_nome_obrigatorio(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("clientes:novo"), {"nome": ""})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["form"].errors["nome"])

    def test_banco_recusa_cpf_cnpj_fora_do_formato(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cliente.objects.create(nome="X", cpf_cnpj="12a")

    def test_lista_mostra_apenas_clientes_autorizados(self):
        f.autorizar_cliente(self.ast, self.cli)
        self.entrar(self.ast)
        resposta = self.client.get(reverse("clientes:lista"))
        self.assertContains(resposta, self.cli.nome)
        self.assertNotContains(resposta, self.cli2.nome)

    def test_conhecer_o_endereco_nao_autoriza(self):
        self.entrar(self.ast)
        for nome in ("clientes:detalhe", "clientes:editar"):
            with self.subTest(nome=nome):
                self.assertEqual(self.client.get(reverse(nome, args=[self.cli.pk])).status_code, 404)
        resposta = self.client.post(reverse("clientes:editar", args=[self.cli.pk]), {"nome": "Alterado"})
        self.assertEqual(resposta.status_code, 404)
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.nome, "Cliente Alfa Fictício")

    def test_detalhe_mostra_somente_processos_autorizados(self):
        f.autorizar_cliente(self.ast, self.cli)
        self.entrar(self.ast)
        resposta = self.client.get(reverse("clientes:detalhe", args=[self.cli.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, self.proc.titulo)
        f.autorizar_processo(self.ast, self.proc)
        self.assertContains(self.client.get(reverse("clientes:detalhe", args=[self.cli.pk])), self.proc.titulo)

    def test_somente_adm_arquiva(self):
        f.autorizar_cliente(self.ast, self.cli)
        self.entrar(self.ast)
        self.assertEqual(self.client.post(reverse("clientes:arquivar", args=[self.cli.pk])).status_code, 403)
        self.entrar(self.adm)
        self.client.post(reverse("clientes:arquivar", args=[self.cli.pk]))
        self.cli.refresh_from_db()
        self.assertTrue(self.cli.arquivado)
        # RN08: vínculos preservados, sem exclusão física.
        self.assertTrue(self.cli.processos.filter(pk=self.proc.pk).exists())

    def test_arquivar_exige_post(self):
        self.entrar(self.adm)
        self.assertEqual(self.client.get(reverse("clientes:arquivar", args=[self.cli.pk])).status_code, 405)

    def test_arquivado_nao_pode_ser_editado_e_pode_ser_reativado(self):
        self.cli.arquivado = True
        self.cli.save()
        self.entrar(self.adm)
        self.client.post(reverse("clientes:editar", args=[self.cli.pk]), {"nome": "Alterado"})
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.nome, "Cliente Alfa Fictício")
        self.client.post(reverse("clientes:arquivar", args=[self.cli.pk]), {"acao": "desarquivar"})
        self.cli.refresh_from_db()
        self.assertFalse(self.cli.arquivado)

    def test_arquivados_ficam_fora_da_lista_padrao(self):
        self.cli2.arquivado = True
        self.cli2.save()
        self.entrar(self.adm)
        self.assertNotContains(self.client.get(reverse("clientes:lista")), self.cli2.nome)
        self.assertContains(self.client.get(reverse("clientes:lista") + "?arquivados=1"), self.cli2.nome)
