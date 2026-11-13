"""O nome do cliente só vira link para quem já pode abrir o cadastro do cliente (sem 404)."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core import acesso
from apps.core.tests import fabrica as f
from apps.documentos.armazenamento import gravar_versao
from apps.documentos.models import Documento


class LinkClienteTests(f.Cenario):
    def link(self):
        return f'href="{reverse("clientes:detalhe", args=[self.cli.pk])}"'

    def test_adv_sem_acesso_ao_cliente_ve_o_nome_sem_link(self):
        # adv é responsável por proc, mas não tem acesso_cliente sobre cli.
        self.entrar(self.adv)
        for url in (self.proc.get_absolute_url(), reverse("processos:lista")):
            with self.subTest(url=url):
                resposta = self.client.get(url)
                self.assertContains(resposta, self.cli.nome)
                self.assertNotContains(resposta, self.link())
        # E continua sem acesso ao cadastro (nenhuma permissão nova).
        self.assertEqual(self.client.get(reverse("clientes:detalhe", args=[self.cli.pk])).status_code, 404)

    def test_link_aparece_quando_o_cliente_ja_e_autorizado(self):
        f.autorizar_cliente(self.adv, self.cli)
        self.entrar(self.adv)
        for url in (self.proc.get_absolute_url(), reverse("processos:lista")):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), self.link())
        self.assertEqual(self.client.get(reverse("clientes:detalhe", args=[self.cli.pk])).status_code, 200)

    def test_adm_tem_link(self):
        self.entrar(self.adm)
        self.assertContains(self.client.get(self.proc.get_absolute_url()), self.link())

    def test_ast_com_processo_autorizado_mas_sem_cliente(self):
        f.autorizar_processo(self.ast, self.proc)
        self.entrar(self.ast)
        resposta = self.client.get(self.proc.get_absolute_url())
        self.assertContains(resposta, self.cli.nome)
        self.assertNotContains(resposta, self.link())

    def test_lista_mistura_clientes_com_e_sem_acesso(self):
        f.autorizar_processo(self.adv, self.proc2)  # adv vê proc (cli) e proc2 (cli2)
        f.autorizar_cliente(self.adv, self.cli2)
        self.entrar(self.adv)
        lista = self.client.get(reverse("processos:lista"))
        self.assertNotContains(lista, self.link())
        self.assertContains(lista, f'href="{reverse("clientes:detalhe", args=[self.cli2.pk])}"')

    def test_documento_de_processo_sem_acesso_ao_cliente(self):
        raiz = tempfile.mkdtemp(prefix="docs-link-")
        self.addCleanup(shutil.rmtree, raiz, True)
        with override_settings(DOCUMENTOS_ROOT=raiz):
            doc = Documento.objects.create(titulo="Contrato fictício", processo=self.proc, cliente=self.cli)
            gravar_versao(doc, SimpleUploadedFile("c.pdf", b"%PDF-1.4 ficticio"), self.adv)
            self.entrar(self.adv)
            resposta = self.client.get(doc.get_absolute_url())
            self.assertContains(resposta, self.cli.nome)
            self.assertNotContains(resposta, self.link())
            f.autorizar_cliente(self.adv, self.cli)
            self.assertContains(self.client.get(doc.get_absolute_url()), self.link())

    def test_funcao_auxiliar_apenas_filtra(self):
        self.assertEqual(acesso.ids_clientes_visiveis(self.adv, [self.cli.pk, self.cli2.pk, None]), set())
        self.assertEqual(acesso.ids_clientes_visiveis(self.adm, [self.cli.pk, self.cli2.pk]), {self.cli.pk, self.cli2.pk})
        self.assertEqual(acesso.ids_clientes_visiveis(self.adm, []), set())
        f.autorizar_cliente(self.ast, self.cli2)
        self.assertEqual(acesso.ids_clientes_visiveis(self.ast, [self.cli.pk, self.cli2.pk]), {self.cli2.pk})
