"""RF06 — documentos (RN04, RN07, RN08)."""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.documentos.models import Documento, VersaoDocumento

PDF = b"%PDF-1.4\n% documento ficticio\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def docx():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def arquivo(nome="peticao.pdf", conteudo=PDF):
    return SimpleUploadedFile(nome, conteudo)


class DocumentosTests(f.Cenario):
    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="docs-teste-")
        self.addCleanup(shutil.rmtree, self.raiz, True)
        override = override_settings(DOCUMENTOS_ROOT=self.raiz)
        override.enable()
        self.addCleanup(override.disable)

    def enviar(self, **dados):
        base = {"titulo": "Petição fictícia", "cliente": "", "processo": self.proc.pk, "descricao": "",
                "arquivo": arquivo()}
        base.update(dados)
        return self.client.post(reverse("documentos:novo"), base)

    def test_envio_cria_versao_1_privada_com_nome_gerado(self):
        self.entrar(self.adv)
        resposta = self.enviar()
        doc = Documento.objects.get(titulo="Petição fictícia")
        self.assertRedirects(resposta, doc.get_absolute_url())
        self.assertEqual(doc.cliente, self.cli)  # cliente obtido do processo
        v = doc.versoes.get()
        self.assertEqual((v.numero_versao, v.autor, v.nome_arquivo, v.extensao), (1, self.adv, "peticao.pdf", "pdf"))
        caminho = Path(self.raiz) / v.caminho_arquivo
        self.assertTrue(caminho.exists())
        self.assertNotIn("peticao", caminho.name)
        self.assertEqual(caminho.read_bytes(), PDF)

    def test_aceita_docx_png_e_jpeg(self):
        self.entrar(self.adm)
        for nome, conteudo in (("a.docx", docx()), ("b.png", PNG), ("c.jpg", b"\xff\xd8\xff\xe0" + b"0" * 20)):
            with self.subTest(nome=nome):
                self.assertEqual(self.enviar(titulo=nome, arquivo=arquivo(nome, conteudo)).status_code, 302)

    def test_recusa_extensao_nao_permitida(self):
        self.entrar(self.adm)
        resposta = self.enviar(arquivo=arquivo("script.exe", b"MZ..."))
        self.assertContains(resposta, "Tipo de arquivo não permitido")
        self.assertFalse(Documento.objects.exists())

    def test_recusa_conteudo_que_nao_corresponde_a_extensao(self):
        self.entrar(self.adm)
        for nome, conteudo in (("falso.pdf", PNG), ("falso.docx", b"PK\x03\x04nao-e-zip"), ("falso.png", PDF)):
            with self.subTest(nome=nome):
                self.assertContains(self.enviar(arquivo=arquivo(nome, conteudo)), "não corresponde")
        self.assertFalse(VersaoDocumento.objects.exists())

    def test_recusa_arquivo_acima_de_10_mib(self):
        self.entrar(self.adm)
        grande = PDF + b"0" * (10 * 1024 * 1024)
        self.assertContains(self.enviar(arquivo=arquivo("grande.pdf", grande)), "10 MiB")

    def test_exige_cliente_ou_processo(self):
        self.entrar(self.adm)
        self.assertContains(self.enviar(processo=""), "Vincule o documento a um cliente ou a um processo.")

    def test_cliente_diferente_do_processo(self):
        self.entrar(self.adm)
        resposta = self.enviar(cliente=self.cli2.pk)
        self.assertIn("cliente", resposta.context["form"].errors)

    def test_nao_vincula_a_processo_nao_autorizado(self):
        self.entrar(self.adv)
        resposta = self.enviar(processo=self.proc2.pk)
        self.assertIn("processo", resposta.context["form"].errors)

    def test_nova_versao_preserva_anteriores(self):
        self.entrar(self.adv)
        self.enviar()
        doc = Documento.objects.get()
        self.entrar(self.adm)
        self.client.post(reverse("documentos:nova_versao", args=[doc.pk]),
                         {"arquivo": arquivo("peticao-v2.pdf", PDF + b"v2")})
        versoes = list(doc.versoes.order_by("numero_versao"))
        self.assertEqual([(v.numero_versao, v.autor) for v in versoes], [(1, self.adv), (2, self.adm)])
        baixado = self.client.get(reverse("documentos:baixar", args=[versoes[0].pk]))
        self.assertEqual(b"".join(baixado.streaming_content), PDF)

    def test_download_protegido_e_como_anexo(self):
        self.entrar(self.adv)
        self.enviar()
        v = VersaoDocumento.objects.get()
        resposta = self.client.get(reverse("documentos:baixar", args=[v.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("attachment", resposta["Content-Disposition"])
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
        # Outro advogado e assistente sem acesso: 404, mesmo conhecendo o endereço.
        for intruso in (self.adv2, self.ast):
            with self.subTest(intruso=intruso.nome):
                self.entrar(intruso)
                self.assertEqual(self.client.get(reverse("documentos:baixar", args=[v.pk])).status_code, 404)
                self.assertEqual(self.client.get(v.documento.get_absolute_url()).status_code, 404)

    def test_acesso_ao_cliente_nao_libera_documento_do_processo(self):
        self.entrar(self.adv)
        self.enviar()
        v = VersaoDocumento.objects.get()
        f.autorizar_cliente(self.ast, self.cli)
        self.entrar(self.ast)
        self.assertEqual(self.client.get(reverse("documentos:baixar", args=[v.pk])).status_code, 404)
        f.autorizar_processo(self.ast, self.proc)
        self.assertEqual(self.client.get(reverse("documentos:baixar", args=[v.pk])).status_code, 200)

    def test_ast_envia_documento_de_cliente_autorizado(self):
        f.autorizar_cliente(self.ast, self.cli)
        self.entrar(self.ast)
        resposta = self.enviar(processo="", cliente=self.cli.pk)
        self.assertEqual(resposta.status_code, 302)
