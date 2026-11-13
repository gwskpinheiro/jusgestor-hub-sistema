"""Camada de armazenamento dos documentos: destinos, falhas e acesso indevido.

Nenhum teste usa rede: o destino alternativo é o InMemoryStorage do Django,
que se comporta como um armazenamento remoto (nada é gravado em disco).
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.documentos import armazenamento as arm
from apps.documentos.backends import ArmazenamentoLocal
from apps.documentos.models import Documento, VersaoDocumento
from apps.documentos.tests.test_documentos import PDF, PNG

EM_MEMORIA = {**settings.STORAGES, "documentos": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}


def pdf(nome="peticao.pdf", conteudo=PDF):
    return SimpleUploadedFile(nome, conteudo)


class BaseArmazenamento(f.Cenario):
    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="docs-armazenamento-")
        self.addCleanup(shutil.rmtree, self.raiz, True)
        override = override_settings(DOCUMENTOS_ROOT=self.raiz)
        override.enable()
        self.addCleanup(override.disable)
        self.doc = Documento.objects.create(titulo="Contrato fictício", processo=self.proc, cliente=self.cli)

    def arquivos_em_disco(self):
        return [p for p in Path(self.raiz).rglob("*") if p.is_file()]

    def baixar(self, versao):
        return self.client.get(reverse("documentos:baixar", args=[versao.pk]))

    def visualizar(self, versao):
        return self.client.get(reverse("documentos:visualizar", args=[versao.pk]))


class ArmazenamentoLocalTests(BaseArmazenamento):
    def test_segue_documentos_root_e_nao_tem_url_publica(self):
        destino = storages["documentos"]
        self.assertIsInstance(destino, ArmazenamentoLocal)
        self.assertEqual(destino.location, str(Path(self.raiz).resolve()))
        with self.assertRaises(ValueError):
            destino.url("1/arquivo.pdf")

    def test_grava_com_a_mesma_chave_de_antes(self):
        v = arm.gravar_versao(self.doc, pdf(), self.adv)
        self.assertRegex(v.caminho_arquivo, rf"^{self.doc.pk}/[0-9a-f]{{32}}\.pdf$")
        self.assertEqual((Path(self.raiz) / v.caminho_arquivo).read_bytes(), PDF)

    def test_registro_no_formato_anterior_continua_acessivel(self):
        # Arquivo gravado pela versão anterior do código (sem a camada de armazenamento).
        chave = f"{self.doc.pk}/{'b' * 32}.pdf"
        destino = Path(self.raiz) / chave
        destino.parent.mkdir(parents=True)
        destino.write_bytes(PDF)
        v = VersaoDocumento.objects.create(documento=self.doc, autor=self.adv, numero_versao=1, nome_arquivo="antigo.pdf",
                                           caminho_arquivo=chave, extensao="pdf", tamanho_bytes=len(PDF))
        self.entrar(self.adv)
        self.assertEqual(b"".join(self.baixar(v).streaming_content), PDF)
        self.assertEqual(self.visualizar(v).status_code, 200)

    def test_nunca_sobrescreve_versao_existente(self):
        v1 = arm.gravar_versao(self.doc, pdf(conteudo=PDF + b"v1"), self.adv)
        with mock.patch.object(arm, "gerar_chave", return_value=v1.caminho_arquivo), \
                self.assertRaises(arm.ArmazenamentoIndisponivel):
            arm.gravar_versao(self.doc, pdf(conteudo=PDF + b"v2"), self.adv)
        self.assertEqual((Path(self.raiz) / v1.caminho_arquivo).read_bytes(), PDF + b"v1")
        self.assertEqual(self.doc.versoes.count(), 1)
        self.assertEqual(len(self.arquivos_em_disco()), 1)  # a cópia renomeada foi removida


@override_settings(STORAGES=EM_MEMORIA)
class DestinoAlternativoTests(BaseArmazenamento):
    """Os fluxos completos funcionam com outro backend (como será o Supabase Storage)."""

    def test_upload_versoes_download_e_visualizacao(self):
        self.entrar(self.adv)
        resposta = self.client.post(reverse("documentos:novo"), {
            "titulo": "Petição em memória", "cliente": "", "processo": self.proc.pk, "descricao": "",
            "arquivo": pdf("inicial.pdf", PDF + b"v1")})
        doc = Documento.objects.get(titulo="Petição em memória")
        self.assertRedirects(resposta, doc.get_absolute_url())
        self.client.post(reverse("documentos:nova_versao", args=[doc.pk]), {"arquivo": SimpleUploadedFile("foto.png", PNG)})
        v1, v2 = doc.versoes.order_by("numero_versao")
        self.assertEqual((v1.numero_versao, v2.numero_versao), (1, 2))
        self.assertTrue(storages["documentos"].exists(v1.caminho_arquivo))
        self.assertEqual(self.arquivos_em_disco(), [])  # nada no disco local
        baixado = self.baixar(v1)
        self.assertTrue(baixado["Content-Disposition"].startswith("attachment"))
        self.assertEqual(b"".join(baixado.streaming_content), PDF + b"v1")  # v1 preservada
        visto = self.visualizar(v2)
        self.assertEqual((visto.status_code, visto["Content-Type"]), (200, "image/png"))
        self.assertTrue(visto["Content-Disposition"].startswith("inline"))
        self.assertEqual(visto["X-Content-Type-Options"], "nosniff")
        self.assertEqual(visto["Cache-Control"], "private, no-store")

    def test_validacao_continua_antes_de_gravar(self):
        self.entrar(self.adv)
        resposta = self.client.post(reverse("documentos:nova_versao", args=[self.doc.pk]),
                                    {"arquivo": SimpleUploadedFile("falso.pdf", b"MZ executavel")})
        self.assertEqual(resposta.status_code, 400)
        self.assertFalse(storages["documentos"].exists(str(self.doc.pk)))  # nada foi gravado


class FalhasTests(BaseArmazenamento):
    def test_falha_ao_gravar_nao_registra_nada_e_avisa(self):
        self.entrar(self.adv)
        with mock.patch.object(ArmazenamentoLocal, "save", side_effect=OSError("disco cheio")), \
                self.assertLogs("apps.documentos.armazenamento", "ERROR"):
            resposta = self.client.post(reverse("documentos:novo"), {
                "titulo": "Não deve existir", "cliente": "", "processo": self.proc.pk, "descricao": "",
                "arquivo": pdf()})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não foi possível acessar o armazenamento de documentos")
        self.assertNotContains(resposta, "disco cheio")
        self.assertFalse(Documento.objects.filter(titulo="Não deve existir").exists())
        self.assertFalse(VersaoDocumento.objects.exists())

    def test_falha_ao_gravar_nova_versao_mantem_as_anteriores(self):
        v1 = arm.gravar_versao(self.doc, pdf(), self.adv)
        self.entrar(self.adv)
        with mock.patch.object(ArmazenamentoLocal, "save", side_effect=ConnectionError("recusada")), \
                self.assertLogs("apps.documentos.armazenamento", "ERROR"):
            resposta = self.client.post(reverse("documentos:nova_versao", args=[self.doc.pk]), {"arquivo": pdf()})
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(list(self.doc.versoes.all()), [v1])
        self.assertContains(resposta, "Contrato fictício", status_code=503)

    def test_falha_no_banco_remove_o_arquivo_gravado(self):
        with mock.patch.object(VersaoDocumento.objects, "create", side_effect=IntegrityError("falha simulada")), \
                self.assertRaises(IntegrityError):
            arm.gravar_versao(self.doc, pdf(), self.adv)
        self.assertEqual(self.arquivos_em_disco(), [])

    def test_arquivo_ausente_responde_404(self):
        v = arm.gravar_versao(self.doc, pdf(), self.adv)
        (Path(self.raiz) / v.caminho_arquivo).unlink()
        self.entrar(self.adm)
        self.assertEqual(self.baixar(v).status_code, 404)
        self.assertEqual(self.visualizar(v).status_code, 404)

    def test_armazenamento_fora_do_ar_responde_503_sem_detalhes(self):
        v = arm.gravar_versao(self.doc, pdf(), self.adv)
        self.entrar(self.adm)
        with mock.patch.object(ArmazenamentoLocal, "open", side_effect=ConnectionError("host interno 10.0.0.5")), \
                self.assertLogs("apps.documentos.armazenamento", "ERROR"):
            for resposta in (self.baixar(v), self.visualizar(v)):
                self.assertEqual(resposta.status_code, 503)
                self.assertEqual(resposta["Retry-After"], "30")
                self.assertNotIn(b"10.0.0.5", resposta.content)


class AcessoIndevidoTests(BaseArmazenamento):
    def setUp(self):
        super().setUp()
        self.versao = arm.gravar_versao(self.doc, pdf(), self.adv)
        self.outro = Documento.objects.create(titulo="Outro documento", processo=self.proc2, cliente=self.cli2)
        self.versao_outro = arm.gravar_versao(self.outro, pdf(conteudo=PDF + b"sigiloso"), self.adv2)

    def espiar(self):
        espiao = mock.patch.object(ArmazenamentoLocal, "open", autospec=True, side_effect=ArmazenamentoLocal.open)
        return espiao

    def test_chave_adulterada_nao_alcanca_outro_arquivo(self):
        chaves = [
            "../" + self.versao.caminho_arquivo,
            "/etc/passwd",
            self.versao_outro.caminho_arquivo,                       # arquivo de outro documento
            self.versao.caminho_arquivo.replace("/", "\\"),
            self.versao.caminho_arquivo[:-4] + ".png",               # extensão diferente da registrada
            f"{self.doc.pk}/../{self.versao_outro.caminho_arquivo}",
            f"{self.doc.pk}/nome-qualquer.pdf",
            "",
        ]
        self.entrar(self.adm)
        for chave in chaves:
            with self.subTest(chave=chave):
                VersaoDocumento.objects.filter(pk=self.versao.pk).update(caminho_arquivo=chave)
                with self.espiar() as aberto:
                    self.assertEqual(self.baixar(self.versao).status_code, 404)
                    self.assertEqual(self.visualizar(self.versao).status_code, 404)
                aberto.assert_not_called()  # o armazenamento nem é consultado

    def test_sem_permissao_o_armazenamento_nao_e_consultado(self):
        f.autorizar_cliente(self.ast, self.cli)  # acesso ao cliente não libera documento do processo
        for usuario in (self.adv2, self.ast):
            self.entrar(usuario)
            with self.subTest(usuario=usuario.perfil), self.espiar() as aberto:
                self.assertEqual(self.baixar(self.versao).status_code, 404)
                self.assertEqual(self.visualizar(self.versao).status_code, 404)
                aberto.assert_not_called()

    def test_sem_login_o_armazenamento_nao_e_consultado(self):
        with self.espiar() as aberto:
            for resposta in (self.baixar(self.versao), self.visualizar(self.versao)):
                self.assertEqual(resposta.status_code, 302)
            aberto.assert_not_called()

    def test_validacao_da_chave(self):
        self.assertEqual(arm.chave_da_versao(self.versao), self.versao.caminho_arquivo)
        for chave in ("1/" + "A" * 32 + ".pdf", "0/" + "a" * 32 + ".pdf", "1/" + "a" * 31 + ".pdf"):
            with self.subTest(chave=chave), self.assertRaises(arm.ArquivoIndisponivel):
                arm.chave_da_versao(VersaoDocumento(documento_id=1, caminho_arquivo=chave, extensao="pdf"))


class TipoMimeTests(BaseArmazenamento):
    """O bucket aceita só tipos de documento: o tipo gravado precisa ser o canônico."""

    def test_tipos_registrados_para_todos_os_formatos(self):
        import mimetypes

        from apps.documentos.models import TIPOS_PERMITIDOS

        for extensao, tipo in TIPOS_PERMITIDOS.items():
            with self.subTest(extensao=extensao):
                self.assertEqual(mimetypes.guess_type(f"arquivo.{extensao}")[0], tipo)

    def test_tipo_do_navegador_e_substituido_pelo_canonico(self):
        from apps.documentos.tests.test_documentos import docx

        recebidos = []
        original = ArmazenamentoLocal.save

        def registrar(destino, nome, conteudo, *a, **k):
            recebidos.append(conteudo.content_type)
            return original(destino, nome, conteudo, *a, **k)

        enviado = SimpleUploadedFile("minuta.docx", docx(), content_type="application/octet-stream")
        with mock.patch.object(ArmazenamentoLocal, "save", autospec=True, side_effect=registrar):
            arm.gravar_versao(self.doc, enviado, self.adv)
        self.assertEqual(recebidos, ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"])

    def test_cliente_s3_enviaria_o_tipo_correto(self):
        from django.core.files.base import ContentFile
        from storages.backends.s3 import S3Storage

        from apps.core.tests.test_configuracao_armazenamento import SUPABASE
        from config.armazenamento import config_supabase

        s3 = S3Storage(**config_supabase(SUPABASE)["OPTIONS"])  # sem rede: só monta os parâmetros
        for nome, tipo in (("1/a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                           ("1/a.pdf", "application/pdf"), ("1/a.png", "image/png"), ("1/a.jpg", "image/jpeg")):
            with self.subTest(nome=nome):
                self.assertEqual(s3._get_write_parameters(nome, ContentFile(b""))["ContentType"], tipo)
