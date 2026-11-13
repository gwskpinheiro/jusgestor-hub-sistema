"""Comando verificar_armazenamento com armazenamento simulado (sem rede)."""
import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from apps.documentos.management.commands import verificar_armazenamento as cmd

SEGREDO = "segredo-ficticio-nunca-exibir-987654"
CHAVE_ID = "chave-id-ficticia-123"
AMBIENTE = {
    "SUPABASE_STORAGE_ENDPOINT": "https://projetoficticio.storage.supabase.co/storage/v1/s3",
    "SUPABASE_STORAGE_REGION": "sa-east-1",
    "SUPABASE_STORAGE_BUCKET": "bucket-ficticio",
    "SUPABASE_STORAGE_ACCESS_KEY_ID": CHAVE_ID,
    "SUPABASE_STORAGE_SECRET_ACCESS_KEY": SEGREDO,
}


class SemListagem(InMemoryStorage):
    """Simula o bucket; falha se o comando tentar listar arquivos."""

    def listdir(self, path):
        raise AssertionError("o comando não pode listar o armazenamento")


class LeituraDivergente(SemListagem):
    def _open(self, name, mode="rb"):
        return ContentFile(b"%PDF-1.4 conteudo diferente", name=name)


class RemocaoFalha(SemListagem):
    def delete(self, name):
        raise ConnectionError(f"falha ao remover ({SEGREDO})")


class ChaveOcupada(SemListagem):
    def exists(self, name):
        return True

    def delete(self, name):
        raise AssertionError("não pode remover um arquivo que o teste não criou")


class RemotoTests(SimpleTestCase):
    def setUp(self):
        ambiente = mock.patch.dict(os.environ, AMBIENTE)
        ambiente.start()
        self.addCleanup(ambiente.stop)

    def rodar(self, destino, *args):
        saida = StringIO()
        with mock.patch.object(cmd, "criar_armazenamento_remoto", return_value=(destino, "bucket-ficticio")) as fabrica:
            try:
                call_command("verificar_armazenamento", *args, stdout=saida, stderr=saida)
                erro = None
            except CommandError as e:
                erro = e
        return saida.getvalue(), erro, fabrica

    def test_sem_confirmacao_nao_acessa_o_armazenamento(self):
        saida, erro, fabrica = self.rodar(SemListagem(), "--remoto")
        self.assertIn("confirme com --confirmar", str(erro))
        fabrica.assert_not_called()

    def test_confirmacao_precisa_ser_o_nome_do_bucket(self):
        for valor in ("sim", "BUCKET-FICTICIO", "outro-bucket"):
            with self.subTest(valor=valor):
                saida, erro, fabrica = self.rodar(SemListagem(), "--remoto", "--confirmar", valor)
                self.assertIn("não corresponde", str(erro))
                fabrica.assert_not_called()

    def test_credenciais_vazias(self):
        with mock.patch.dict(os.environ, {"SUPABASE_STORAGE_SECRET_ACCESS_KEY": ""}):
            saida, erro, fabrica = self.rodar(SemListagem(), "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIn("SUPABASE_STORAGE_SECRET_ACCESS_KEY", str(erro))
        fabrica.assert_not_called()

    def test_grava_le_verifica_e_remove_somente_o_proprio_arquivo(self):
        destino = SemListagem()
        destino.save("documentos/1/" + "a" * 32 + ".pdf", ContentFile(b"%PDF documento real"))
        saida, erro, _ = self.rodar(destino, "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIsNone(erro, saida)
        for etapa in ("Chave de teste livre", "Gravação", "Arquivo encontrado após a gravação",
                      "Leitura e integridade", "SHA-256 idêntico", "Remoção do arquivo de teste",
                      "Arquivo ausente após a remoção", "gravação, leitura, integridade e remoção funcionaram"):
            self.assertIn(etapa, saida)
        self.assertNotIn("[FALHA]", saida)
        # Documento existente intacto; o arquivo de teste não ficou no armazenamento.
        with destino.open("documentos/1/" + "a" * 32 + ".pdf") as existente:
            self.assertEqual(existente.read(), b"%PDF documento real")
        # Conferência feita pelo teste (o comando nunca lista): só resta o documento.
        self.assertEqual(InMemoryStorage.listdir(destino, ""), (["documentos"], []))

    def test_conteudo_divergente_falha_e_ainda_remove(self):
        destino = LeituraDivergente()
        saida, erro, _ = self.rodar(destino, "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIsNotNone(erro)
        self.assertIn("[FALHA] Leitura e integridade", saida)
        self.assertIn("[OK]    Remoção do arquivo de teste", saida)
        self.assertEqual(InMemoryStorage.listdir(destino, ""), ([], []))

    def test_falha_na_remocao_e_informada_sem_expor_segredo(self):
        saida, erro, _ = self.rodar(RemocaoFalha(), "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIsNotNone(erro)
        self.assertIn("[FALHA] Remoção do arquivo de teste", saida)
        self.assertIn("remova manualmente apenas verificacao-conexao/", saida)
        self.assertNotIn(SEGREDO, saida + str(erro))
        self.assertIn("***", saida)

    def test_falha_na_gravacao_nao_expoe_credenciais(self):
        destino = SemListagem()
        with mock.patch.object(destino, "save", side_effect=PermissionError(f"negado para {CHAVE_ID} / {SEGREDO}")):
            saida, erro, _ = self.rodar(destino, "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIsNotNone(erro)
        self.assertIn("[FALHA] Gravação", saida)
        self.assertNotIn(SEGREDO, saida + str(erro))
        self.assertNotIn(CHAVE_ID, saida + str(erro))
        self.assertNotIn("Remoção", saida)  # nada foi gravado, nada é removido

    def test_chave_ja_existente_nao_grava_nem_remove(self):
        saida, erro, _ = self.rodar(ChaveOcupada(), "--remoto", "--confirmar", "bucket-ficticio")
        self.assertIsNotNone(erro)
        self.assertIn("[FALHA] Chave de teste livre", saida)
        self.assertNotIn("Gravação", saida)

    def test_cliente_real_usa_prefixo_exclusivo_sem_rede(self):
        destino, bucket = cmd.criar_armazenamento_remoto(AMBIENTE)
        self.assertEqual(bucket, "bucket-ficticio")
        self.assertEqual(destino.location, cmd.PREFIXO_TESTE)
        self.assertNotEqual(destino.location, "documentos")
        self.assertFalse(destino.file_overwrite)
        self.assertEqual(settings.DOCUMENTOS_ARMAZENAMENTO, "local")  # o sistema continua local

    def test_conteudo_ficticio_e_pdf(self):
        conteudo = cmd.conteudo_ficticio("marcador")
        self.assertTrue(conteudo.startswith(b"%PDF-"))
        self.assertLess(len(conteudo), 300)


class LocalTests(SimpleTestCase):
    def test_sem_remoto_usa_o_armazenamento_do_sistema(self):
        raiz = tempfile.mkdtemp(prefix="docs-verificar-")
        self.addCleanup(shutil.rmtree, raiz, True)
        documento = Path(raiz) / "1" / ("c" * 32 + ".pdf")
        documento.parent.mkdir()
        documento.write_bytes(b"%PDF documento local")
        saida = StringIO()
        with override_settings(DOCUMENTOS_ROOT=raiz), \
                mock.patch.object(cmd, "criar_armazenamento_remoto") as fabrica:
            call_command("verificar_armazenamento", stdout=saida)
        fabrica.assert_not_called()
        self.assertIn("armazenamento do sistema (local)", saida.getvalue())
        self.assertIn("gravação, leitura, integridade e remoção funcionaram", saida.getvalue())
        arquivos = [p for p in Path(raiz).rglob("*") if p.is_file()]
        self.assertEqual(arquivos, [documento])
        self.assertEqual(documento.read_bytes(), b"%PDF documento local")
