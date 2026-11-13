"""Backup e restauração dos arquivos de documentos com armazenamento simulado (sem rede)."""
import json
import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from apps.documentos import backup_remoto as bk
from apps.documentos import remoto

PDF = b"%PDF-1.4 documento ficticio"
DOCS = {
    "documentos/1/" + "a" * 32 + ".pdf": PDF,
    "documentos/1/" + "b" * 32 + ".png": b"\x89PNG\r\n\x1a\nficticio",
    "documentos/7/" + "c" * 32 + ".docx": b"PK\x03\x04ficticio",
}
OUTRO = {"outro-prefixo/segredo.pdf": b"%PDF nao deve ser lido"}
SEGREDO = "segredo-ficticio-nao-exibir-5555"
AMBIENTE = {
    "SUPABASE_STORAGE_ENDPOINT": "https://ficticio.storage.supabase.co/storage/v1/s3",
    "SUPABASE_STORAGE_REGION": "sa-east-1",
    "SUPABASE_STORAGE_BUCKET": "bucket-ficticio",
    "SUPABASE_STORAGE_PREFIXO": "documentos",
    "SUPABASE_STORAGE_ACCESS_KEY_ID": "id-ficticio",
    "SUPABASE_STORAGE_SECRET_ACCESS_KEY": SEGREDO,
}


class Registro(InMemoryStorage):
    """Armazenamento simulado que registra leituras e remoções."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lidos, self.removidos = [], []

    def _open(self, name, mode="rb"):
        self.lidos.append(name)
        return super()._open(name, mode)

    def delete(self, name):
        self.removidos.append(name)
        return super().delete(name)


def armazenamento_com(arquivos):
    destino = Registro()
    for chave, conteudo in arquivos.items():
        destino.save(chave, ContentFile(conteudo))
    destino.lidos.clear()
    return destino


def conteudo(destino, chave):
    with destino.open(chave, "rb") as arquivo:
        return arquivo.read()


class BaseBackup(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="backup-docs-teste-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pasta = self.tmp / "copia"


class ExportacaoTests(BaseBackup):
    def test_exporta_somente_o_prefixo_com_chaves_originais(self):
        destino = armazenamento_com({**DOCS, **OUTRO})
        manifesto = bk.exportar(destino, "documentos", self.pasta, "teste")
        chaves = sorted(i["chave"] for i in manifesto["arquivos"])
        self.assertEqual(chaves, sorted(c.removeprefix("documentos/") for c in DOCS))
        for chave, dados in DOCS.items():
            self.assertEqual((self.pasta / "arquivos" / chave.removeprefix("documentos/")).read_bytes(), dados)
        self.assertNotIn("outro-prefixo/segredo.pdf", destino.lidos)  # fora do prefixo: nem lido
        self.assertEqual(manifesto["total_bytes"], sum(len(d) for d in DOCS.values()))
        self.assertEqual(destino.removidos, [])  # exportação é somente leitura

    def test_manifesto_tamanho_sha256_e_lista_sha256sum(self):
        bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")
        manifesto = json.loads((self.pasta / "manifesto.json").read_text(encoding="utf-8"))
        item = next(i for i in manifesto["arquivos"] if i["chave"].endswith(".pdf"))
        self.assertEqual(item["tamanho"], len(PDF))
        self.assertEqual(item["sha256"], bk.hashlib.sha256(PDF).hexdigest())
        linhas = (self.pasta / "manifesto.sha256").read_text(encoding="utf-8").splitlines()
        self.assertIn(f"{item['sha256']}  arquivos/{item['chave']}", linhas)
        self.assertFalse(any(p.name.endswith(".parcial") for p in self.pasta.rglob("*")))

    def test_nao_grava_em_pasta_com_conteudo(self):
        self.pasta.mkdir()
        (self.pasta / "outro.txt").write_text("existente")
        with self.assertRaises(bk.BackupInvalido):
            bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")
        self.assertEqual((self.pasta / "outro.txt").read_text(), "existente")

    def test_recusa_chave_insegura_vinda_do_armazenamento(self):
        destino = armazenamento_com(DOCS)
        with mock.patch.object(bk, "percorrer", return_value=iter(["documentos/../../etc/passwd"])), \
                self.assertRaises(bk.BackupInvalido):
            bk.exportar(destino, "documentos", self.pasta, "teste")
        self.assertFalse((self.tmp / "etc").exists())

    def test_validacao_de_chaves(self):
        for chave in ("1/a.pdf", "documentos/1/" + "a" * 32 + ".pdf", ".emptyFolderPlaceholder"):
            self.assertEqual(bk.chave_segura(chave), chave)
        for chave in ("", "/etc/passwd", "../x", "a/../b", "a//b", "a\\b", "a/./b", "a/b c.pdf"):
            with self.subTest(chave=chave), self.assertRaises(bk.BackupInvalido):
                bk.chave_segura(chave)


class VerificacaoTests(BaseBackup):
    def setUp(self):
        super().setUp()
        bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")
        self.pdf = next((self.pasta / "arquivos").rglob("*.pdf"))

    def test_copia_integra(self):
        manifesto, problemas = bk.verificar(self.pasta)
        self.assertEqual(problemas, [])
        self.assertEqual(manifesto["total_arquivos"], 3)

    def test_detecta_conteudo_alterado_mesmo_tamanho(self):
        dados = bytearray(self.pdf.read_bytes())
        dados[-1] ^= 1
        self.pdf.write_bytes(bytes(dados))
        self.assertIn("SHA-256 diferente", " ".join(bk.verificar(self.pasta)[1]))

    def test_detecta_tamanho_ausencia_e_arquivo_extra(self):
        self.pdf.write_bytes(PDF + b"extra")
        next((self.pasta / "arquivos").rglob("*.png")).unlink()
        (self.pasta / "arquivos" / "intruso.pdf").write_bytes(PDF)
        problemas = " ".join(bk.verificar(self.pasta)[1])
        for texto in ("tamanho diferente", "arquivo ausente", "intruso.pdf: arquivo fora do manifesto"):
            self.assertIn(texto, problemas)

    def test_detecta_manifesto_alterado(self):
        caminho = self.pasta / "manifesto.json"
        caminho.write_text(caminho.read_text(encoding="utf-8").replace('"teste"', '"adulterado"'), encoding="utf-8")
        with self.assertRaisesMessage(bk.BackupInvalido, "manifesto foi alterado"):
            bk.verificar(self.pasta)

    def test_comando_de_verificacao(self):
        saida = StringIO()
        call_command("verificar_backup_documentos", str(self.pasta), stdout=saida)
        self.assertIn("Cópia íntegra: 3 arquivo(s)", saida.getvalue())
        self.pdf.write_bytes(b"corrompido")
        with self.assertRaises(CommandError):
            call_command("verificar_backup_documentos", str(self.pasta), stdout=StringIO())


class RestauracaoTests(BaseBackup):
    def setUp(self):
        super().setUp()
        bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")

    def test_restaura_nos_caminhos_originais(self):
        vazio = Registro()
        resultado = bk.restaurar(vazio, self.pasta, "documentos")
        self.assertEqual(sorted(resultado["restaurado"]), sorted(DOCS))
        for chave, dados in DOCS.items():
            self.assertEqual(conteudo(vazio, chave), dados)

    def test_restaura_em_prefixo_isolado_sem_tocar_nos_documentos(self):
        destino = armazenamento_com({**DOCS, **OUTRO})
        resultado = bk.restaurar(destino, self.pasta, "teste-restauracao")
        self.assertEqual(len(resultado["restaurado"]), 3)
        self.assertTrue(all(c.startswith("teste-restauracao/") for c in resultado["restaurado"]))
        self.assertEqual(destino.removidos, [])
        for chave, dados in {**DOCS, **OUTRO}.items():
            self.assertEqual(conteudo(destino, chave), dados)

    def test_identico_e_ignorado_e_diferente_nunca_e_sobrescrito(self):
        destino = armazenamento_com(DOCS)
        alterada = "documentos/1/" + "a" * 32 + ".pdf"
        destino.delete(alterada)
        destino.save(alterada, ContentFile(b"%PDF versao mais nova no bucket"))
        destino.removidos.clear()
        resultado = bk.restaurar(destino, self.pasta, "documentos")
        self.assertEqual(resultado["conflito"], [alterada])
        self.assertEqual(len(resultado["identico"]), 2)
        self.assertEqual(resultado["restaurado"], [])
        self.assertEqual(conteudo(destino, alterada), b"%PDF versao mais nova no bucket")
        self.assertEqual(destino.removidos, [])

    def test_sobrescrita_somente_quando_autorizada(self):
        destino = armazenamento_com(DOCS)
        alterada = "documentos/1/" + "a" * 32 + ".pdf"
        destino.delete(alterada)
        destino.save(alterada, ContentFile(b"%PDF diferente"))
        resultado = bk.restaurar(destino, self.pasta, "documentos", sobrescrever=True)
        self.assertEqual(resultado["sobrescrito"], [alterada])
        self.assertEqual(conteudo(destino, alterada), PDF)

    def test_copia_corrompida_nao_restaura_nada(self):
        next((self.pasta / "arquivos").rglob("*.png")).write_bytes(b"corrompido")
        vazio = Registro()
        with self.assertRaisesMessage(bk.BackupInvalido, "nada foi restaurado"):
            bk.restaurar(vazio, self.pasta, "documentos")
        self.assertEqual(InMemoryStorage.listdir(vazio, ""), ([], []))

    def test_conteudo_enviado_e_relido(self):
        class Corrompe(Registro):
            def _save(self, name, content):
                return super()._save(name, ContentFile(b"bytes trocados no caminho"))
        with self.assertRaisesMessage(bk.BackupInvalido, "difere da cópia"):
            bk.restaurar(Corrompe(), self.pasta, "documentos")


class ComandosTests(BaseBackup):
    def setUp(self):
        super().setUp()
        ambiente = mock.patch.dict(os.environ, AMBIENTE)
        ambiente.start()
        self.addCleanup(ambiente.stop)

    def com_remoto(self, destino):
        return mock.patch.object(remoto, "criar_cliente", return_value=destino)

    def test_remoto_exige_confirmacao_com_o_nome_do_bucket(self):
        for args in (["--remoto"], ["--remoto", "--confirmar", "outro"]):
            for comando in ("exportar_documentos", "testar_backup_documentos"):
                with self.subTest(comando=comando, args=args), self.com_remoto(Registro()) as fabrica, \
                        self.assertRaises(CommandError):
                    call_command(comando, *args, stdout=StringIO())
                fabrica.assert_not_called()

    def test_exportar_remoto_usa_o_prefixo_dos_documentos(self):
        destino = armazenamento_com({**DOCS, **OUTRO})
        saida = StringIO()
        with self.com_remoto(destino):
            call_command("exportar_documentos", "--remoto", "--confirmar", "bucket-ficticio",
                         "--destino", str(self.pasta), stdout=saida)
        self.assertIn("Exportados 3 arquivo(s)", saida.getvalue())
        self.assertEqual(bk.verificar(self.pasta)[1], [])
        self.assertNotIn(SEGREDO, saida.getvalue())

    def test_restaurar_sobrescrita_exige_confirmacao_propria(self):
        bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")
        destino = Registro()
        with self.com_remoto(destino) as fabrica:
            for extra in ([], ["--confirmar-sobrescrita", "outro"]):
                with self.subTest(extra=extra), self.assertRaisesMessage(CommandError, "Sobrescrita não autorizada"):
                    call_command("restaurar_documentos", str(self.pasta), "--remoto", "--confirmar", "bucket-ficticio",
                                 "--sobrescrever", *extra, stdout=StringIO())
            fabrica.assert_not_called()
            saida = StringIO()
            call_command("restaurar_documentos", str(self.pasta), "--remoto", "--confirmar", "bucket-ficticio",
                         stdout=saida)
        self.assertIn("Restaurados: 3", saida.getvalue())
        self.assertEqual(sorted(c for c in DOCS), sorted(
            bk.juntar("documentos", p) for p in [i["chave"] for i in bk.ler_manifesto(self.pasta)["arquivos"]]))

    def test_restaurar_com_conflito_termina_com_erro_sem_alterar(self):
        bk.exportar(armazenamento_com(DOCS), "documentos", self.pasta, "teste")
        destino = armazenamento_com(DOCS)
        alterada = "documentos/7/" + "c" * 32 + ".docx"
        destino.delete(alterada)
        destino.save(alterada, ContentFile(b"PK\x03\x04mais novo"))
        saida = StringIO()
        with self.com_remoto(destino), self.assertRaisesMessage(CommandError, "Restauração incompleta"):
            call_command("restaurar_documentos", str(self.pasta), "--remoto", "--confirmar", "bucket-ficticio",
                         stdout=saida)
        self.assertIn(f"[CONFLITO] {alterada}", saida.getvalue())
        self.assertEqual(conteudo(destino, alterada), b"PK\x03\x04mais novo")

    def test_teste_completo_remove_somente_os_proprios_arquivos(self):
        destino = armazenamento_com({**DOCS, **OUTRO})
        saida = StringIO()
        with self.com_remoto(destino):
            call_command("testar_backup_documentos", "--remoto", "--confirmar", "bucket-ficticio", stdout=saida)
        lidos_pelo_comando, removidos_pelo_comando = list(destino.lidos), list(destino.removidos)
        texto = saida.getvalue()
        self.assertNotIn("[FALHA]", texto)
        for etapa in ("Criar arquivos fictícios", "Exportar e verificar", "Restaurar em outro prefixo isolado",
                      "Restaurar de novo sem duplicar", "não é sobrescrito sem autorização",
                      "Sobrescrita somente com autorização", "Remover somente os arquivos do teste"):
            self.assertIn(etapa, texto)
        # Documentos e outros arquivos intactos; nenhum arquivo do teste ficou para trás.
        for chave, dados in {**DOCS, **OUTRO}.items():
            self.assertEqual(conteudo(destino, chave), dados)
        # O comando só leu e removeu arquivos dentro do próprio prefixo isolado.
        self.assertTrue(lidos_pelo_comando)
        self.assertTrue(all(c.startswith("verificacao-backup/") for c in lidos_pelo_comando))
        self.assertTrue(all(c.startswith("verificacao-backup/") for c in removidos_pelo_comando))
        self.assertEqual(sorted(bk.percorrer(destino, "verificacao-backup")), [])

    def test_falha_no_meio_ainda_limpa_e_nao_expoe_segredo(self):
        class FalhaNaExportacao(Registro):
            def listdir(self, path):
                raise ConnectionError(f"erro com {SEGREDO}")
        destino = FalhaNaExportacao()
        saida = StringIO()
        with self.com_remoto(destino), self.assertRaises(CommandError):
            call_command("testar_backup_documentos", "--remoto", "--confirmar", "bucket-ficticio", stdout=saida)
        self.assertIn("[FALHA] Exportar e verificar", saida.getvalue())
        self.assertIn("[OK]    Remover somente os arquivos do teste", saida.getvalue())
        self.assertNotIn(SEGREDO, saida.getvalue())
        self.assertEqual(InMemoryStorage.listdir(destino, ""), (["verificacao-backup"], []))
        self.assertEqual(sorted(InMemoryStorage.listdir(destino, "verificacao-backup")[1]), [])

    def test_comandos_locais_sem_remoto(self):
        raiz = self.tmp / "documentos-locais"
        documento = raiz / "1" / ("d" * 32 + ".pdf")
        documento.parent.mkdir(parents=True)
        documento.write_bytes(PDF)
        with override_settings(DOCUMENTOS_ROOT=str(raiz)), mock.patch.object(remoto, "criar_cliente") as fabrica:
            call_command("exportar_documentos", "--destino", str(self.pasta), stdout=StringIO())
            saida = StringIO()
            call_command("restaurar_documentos", str(self.pasta), stdout=saida)  # já presente e idêntico
            call_command("testar_backup_documentos", stdout=StringIO())
        fabrica.assert_not_called()
        self.assertIn("já presentes e idênticos: 1", saida.getvalue())
        self.assertEqual([i["chave"] for i in bk.ler_manifesto(self.pasta)["arquivos"]], ["1/" + "d" * 32 + ".pdf"])
        self.assertEqual([p for p in raiz.rglob("*") if p.is_file()], [documento])
