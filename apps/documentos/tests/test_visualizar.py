"""Visualizar documentos no navegador (PDF, PNG, JPEG) com as mesmas verificações do download."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.documentos.armazenamento import gravar_versao
from apps.documentos.models import Documento
from apps.documentos.tests.test_documentos import PDF, PNG, docx

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 20


class VisualizarTests(f.Cenario):
    def setUp(self):
        raiz = tempfile.mkdtemp(prefix="docs-visualizar-")
        self.addCleanup(shutil.rmtree, raiz, True)
        override = override_settings(DOCUMENTOS_ROOT=raiz)
        override.enable()
        self.addCleanup(override.disable)
        self.doc = Documento.objects.create(titulo="Contrato fictício", processo=self.proc, cliente=self.cli)

    def versao(self, nome, conteudo):
        return gravar_versao(self.doc, SimpleUploadedFile(nome, conteudo), self.adv)

    def url(self, versao):
        return reverse("documentos:visualizar", args=[versao.pk])

    def test_exibe_pdf_png_e_jpeg_no_navegador(self):
        self.entrar(self.adv)
        for nome, conteudo, tipo in (("peticao.pdf", PDF, "application/pdf"), ("foto.png", PNG, "image/png"),
                                     ("scan.jpg", JPEG, "image/jpeg"), ("scan2.jpeg", JPEG, "image/jpeg")):
            with self.subTest(nome=nome):
                v = self.versao(nome, conteudo)
                resposta = self.client.get(self.url(v))
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta["Content-Type"], tipo)
                self.assertTrue(resposta["Content-Disposition"].startswith("inline"))
                self.assertIn(nome, resposta["Content-Disposition"])
                self.assertEqual(resposta["Cache-Control"], "private, no-store")
                self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
                self.assertEqual(b"".join(resposta.streaming_content), conteudo)

    def test_docx_nao_e_exibido_somente_baixado(self):
        v = self.versao("minuta.docx", docx())
        self.entrar(self.adv)
        self.assertEqual(self.client.get(self.url(v)).status_code, 404)
        baixar = self.client.get(reverse("documentos:baixar", args=[v.pk]))
        self.assertEqual(baixar.status_code, 200)
        self.assertTrue(baixar["Content-Disposition"].startswith("attachment"))

    def test_mesma_autorizacao_do_download(self):
        v = self.versao("peticao.pdf", PDF)
        baixar = reverse("documentos:baixar", args=[v.pk])
        # adv2 não tem vínculo com o processo; AST sem autorização.
        for usuario in (self.adv2, self.ast):
            self.entrar(usuario)
            with self.subTest(perfil=usuario.perfil, usuario=usuario.pk):
                self.assertEqual(self.client.get(self.url(v)).status_code, 404)
                self.assertEqual(self.client.get(baixar).status_code, 404)
        f.autorizar_processo(self.ast, self.proc)
        self.entrar(self.ast)
        self.assertEqual(self.client.get(self.url(v)).status_code, 200)

    def test_exige_login(self):
        v = self.versao("peticao.pdf", PDF)
        resposta = self.client.get(self.url(v))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("usuarios:login"), resposta["Location"])

    def test_arquivo_ausente_responde_404(self):
        v = self.versao("peticao.pdf", PDF)
        v.caminho_arquivo = "../fora-da-raiz.pdf"
        v.save(update_fields=["caminho_arquivo"])
        self.entrar(self.adm)
        self.assertEqual(self.client.get(self.url(v)).status_code, 404)

    def test_botoes_visualizar_e_baixar_no_historico(self):
        pdf, minuta = self.versao("peticao.pdf", PDF), self.versao("minuta.docx", docx())
        self.entrar(self.adv)
        pagina = self.client.get(self.doc.get_absolute_url())
        self.assertContains(pagina, f'href="{self.url(pdf)}" target="_blank" rel="noopener"')
        self.assertNotContains(pagina, reverse("documentos:visualizar", args=[minuta.pk]))
        for v in (pdf, minuta):
            self.assertContains(pagina, reverse("documentos:baixar", args=[v.pk]))
        # Lista: a versão atual (DOCX) só tem "Baixar".
        lista = self.client.get(reverse("documentos:lista"))
        self.assertContains(lista, reverse("documentos:baixar", args=[minuta.pk]))
        self.assertNotContains(lista, "Visualizar")
