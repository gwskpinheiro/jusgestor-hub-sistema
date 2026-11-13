"""Verifica a integridade de uma cópia criada por exportar_documentos (RNF07).

Uso:
    docker compose run --rm web python manage.py verificar_backup_documentos backups/documentos/<pasta>

Confere o manifesto (que não pode ter sido alterado) e, para cada arquivo,
presença, tamanho e SHA-256; aponta arquivos fora do manifesto. Não acessa
nenhum armazenamento.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.documentos.backup_remoto import BackupInvalido, verificar


class Command(BaseCommand):
    help = "Verifica tamanho e SHA-256 de cada arquivo de uma cópia de documentos."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("pasta", help="Pasta da cópia (contém manifesto.json).")

    def handle(self, *args, pasta, **opcoes):
        try:
            manifesto, problemas = verificar(pasta)
        except BackupInvalido as erro:
            raise CommandError(str(erro)) from None
        self.stdout.write(f"Origem: {manifesto['origem']}, prefixo: {manifesto['prefixo'] or '(raiz)'}, "
                          f"criada em {manifesto['criado_em']}")
        if problemas:
            for problema in problemas:
                self.stdout.write(self.style.ERROR(f"[FALHA] {problema}"))
            raise CommandError(f"Cópia com {len(problemas)} problema(s).")
        self.stdout.write(self.style.SUCCESS(
            f"Cópia íntegra: {manifesto['total_arquivos']} arquivo(s), {manifesto['total_bytes']} bytes, "
            "tamanho e SHA-256 conferidos."))
