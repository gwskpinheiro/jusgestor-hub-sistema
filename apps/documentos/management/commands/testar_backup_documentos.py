"""Teste completo de backup e restauração com arquivos FICTÍCIOS em prefixo isolado (RNF07).

Uso:
    # armazenamento do sistema (padrão: pasta local)
    docker compose run --rm web python manage.py testar_backup_documentos

    # bucket do Supabase Storage
    docker compose run --rm web python manage.py testar_backup_documentos --remoto --confirmar <bucket>

Etapas, todas dentro de verificacao-backup/<id aleatório>/:
1. grava 3 arquivos fictícios (PDF, PNG e DOCX) em .../origem/;
2. exporta .../origem/ para uma pasta temporária local e verifica o manifesto;
3. restaura em .../restaurado/ e confere chaves e SHA-256;
4. restaura de novo: tudo "idêntico", nada reenviado;
5. troca um arquivo restaurado por outro conteúdo e restaura: o arquivo
   diferente NÃO é sobrescrito (conflito);
6. restaura com sobrescrita autorizada: o arquivo volta ao original;
7. remove somente os arquivos criados pelo teste e confirma a remoção.

Nada fora do prefixo do teste é listado, lido, alterado ou removido.
"""
import io
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.documentos.backup_remoto import exportar, juntar, restaurar, sha256_no_armazenamento, verificar
from apps.documentos.remoto import mascarar, obter_armazenamento

PREFIXO_TESTE = "verificacao-backup"


def _docx_ficticio():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document>JusGestor Hub - arquivo ficticio</w:document>")
    return buffer.getvalue()


def arquivos_ficticios(marcador):
    """Chaves no formato dos documentos (<documento>/<uuid>.<ext>) com conteúdo fictício."""
    return {
        f"901/{uuid.uuid4().hex}.pdf": b"%PDF-1.4\n% arquivo ficticio de teste de backup " + marcador.encode() + b"\n%%EOF\n",
        f"901/{uuid.uuid4().hex}.png": b"\x89PNG\r\n\x1a\n" + b"ficticio-" + marcador.encode(),
        f"902/{uuid.uuid4().hex}.docx": _docx_ficticio(),
    }


class Command(BaseCommand):
    help = "Testa exportação, verificação e restauração com arquivos fictícios em prefixo isolado."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--remoto", action="store_true", help="Executa no bucket do Supabase Storage.")
        parser.add_argument("--confirmar", metavar="BUCKET", help="Obrigatório com --remoto: nome exato do bucket.")

    def handle(self, *args, remoto=False, confirmar=None, **opcoes):
        destino, descricao = obter_armazenamento(remoto, confirmar, "Teste de backup")
        execucao = uuid.uuid4().hex[:12]
        base = juntar(PREFIXO_TESTE, execucao)
        origem, restaurado = juntar(base, "origem"), juntar(base, "restaurado")
        ficticios = arquivos_ficticios(execucao)
        criados = []  # somente estas chaves podem ser removidas no final
        falhas = []
        self.stdout.write(f"Destino: {descricao}, prefixo isolado: {base}/ ({len(ficticios)} arquivos fictícios)")

        def etapa(titulo, funcao):
            inicio = time.perf_counter()
            try:
                detalhe = funcao()
            except Exception as erro:
                texto = mascarar(f"{type(erro).__name__}: {erro}")
                falhas.append(titulo)
                self.stdout.write(self.style.ERROR(f"[FALHA] {titulo}: {texto}"))
                return False
            self.stdout.write(self.style.SUCCESS(f"[OK]    {titulo}")
                              + f" ({(time.perf_counter() - inicio) * 1000:.0f} ms)" + (f" - {detalhe}" if detalhe else ""))
            return True

        def criar_origem():
            for relativa, conteudo in ficticios.items():
                chave = juntar(origem, relativa)
                if destino.exists(chave):
                    raise RuntimeError(f"{chave} já existe; teste interrompido")
                salvo = destino.save(chave, ContentFile(conteudo, name=Path(relativa).name))
                criados.append(salvo)
                if salvo != chave:
                    raise RuntimeError(f"gravado com outro nome: {salvo}")
            return f"{len(ficticios)} arquivos em {origem}/"

        with tempfile.TemporaryDirectory(prefix="jusgestor-teste-backup-") as temporaria:
            pasta = Path(temporaria) / "copia"
            estado = {}

            def exportar_e_verificar():
                manifesto = exportar(destino, origem, pasta, descricao)
                _, problemas = verificar(pasta)
                if problemas:
                    raise RuntimeError("; ".join(problemas))
                if sorted(i["chave"] for i in manifesto["arquivos"]) != sorted(ficticios):
                    raise RuntimeError("as chaves exportadas diferem das originais")
                estado["manifesto"] = manifesto
                return f"{manifesto['total_arquivos']} arquivos, chaves preservadas, SHA-256 conferido"

            def restaurar_em_prefixo_isolado():
                resultado = restaurar(destino, pasta, restaurado)
                criados.extend(resultado["restaurado"])
                esperado = sorted(juntar(restaurado, chave) for chave in ficticios)
                if sorted(resultado["restaurado"]) != esperado:
                    raise RuntimeError(f"restaurados {len(resultado['restaurado'])} de {len(esperado)}")
                for item in estado["manifesto"]["arquivos"]:
                    if sha256_no_armazenamento(destino, juntar(restaurado, item["chave"])) != item["sha256"]:
                        raise RuntimeError(f"{item['chave']}: SHA-256 diferente após restaurar")
                return f"{len(esperado)} arquivos em {restaurado}/ com as mesmas chaves e SHA-256"

            def restaurar_de_novo():
                resultado = restaurar(destino, pasta, restaurado)
                if resultado["restaurado"] or resultado["conflito"] or len(resultado["identico"]) != len(ficticios):
                    raise RuntimeError(f"resultado inesperado: { {k: len(v) for k, v in resultado.items()} }")
                return "todos idênticos, nada reenviado"

            alvo = juntar(restaurado, sorted(ficticios)[0])
            diferente = b"%PDF-1.4\n% conteudo DIFERENTE (ficticio) para testar conflito\n%%EOF\n"

            def conflito_nao_sobrescreve():
                destino.delete(alvo)  # arquivo criado por este teste
                destino.save(alvo, ContentFile(diferente, name=Path(alvo).name))
                resultado = restaurar(destino, pasta, restaurado)
                if resultado["conflito"] != [alvo]:
                    raise RuntimeError(f"conflito esperado em {alvo}, obtido {resultado['conflito']}")
                with destino.open(alvo, "rb") as arquivo:
                    if arquivo.read() != diferente:
                        raise RuntimeError("o arquivo diferente foi alterado sem autorização")
                return "arquivo diferente mantido; conflito informado"

            def sobrescrita_autorizada():
                resultado = restaurar(destino, pasta, restaurado, sobrescrever=True)
                if resultado["sobrescrito"] != [alvo]:
                    raise RuntimeError(f"sobrescrita esperada em {alvo}")
                return "arquivo voltou ao conteúdo da cópia"

            try:
                if (etapa("Criar arquivos fictícios no prefixo isolado", criar_origem)
                        and etapa("Exportar e verificar a cópia (manifesto, tamanho, SHA-256)", exportar_e_verificar)
                        and etapa("Restaurar em outro prefixo isolado", restaurar_em_prefixo_isolado)
                        and etapa("Restaurar de novo sem duplicar", restaurar_de_novo)
                        and etapa("Arquivo diferente não é sobrescrito sem autorização", conflito_nao_sobrescreve)):
                    etapa("Sobrescrita somente com autorização", sobrescrita_autorizada)
            finally:
                self.limpar(destino, criados, etapa)

        if falhas:
            raise CommandError(f"Teste de backup falhou em {len(falhas)} etapa(s).")
        self.stdout.write(self.style.SUCCESS(
            "Backup e restauração verificados: exportação, integridade, restauração com chaves originais, "
            "proteção contra sobrescrita e limpeza funcionaram."))

    def limpar(self, destino, criados, etapa):
        chaves = sorted(set(criados))

        def remover():
            for chave in chaves:
                destino.delete(chave)  # somente arquivos criados por este teste
            restantes = [chave for chave in chaves if destino.exists(chave)]
            if restantes:
                raise RuntimeError("continuam no armazenamento: " + ", ".join(restantes))
            return f"{len(chaves)} arquivos fictícios removidos e ausência confirmada"

        if chaves:
            etapa("Remover somente os arquivos do teste", remover)
