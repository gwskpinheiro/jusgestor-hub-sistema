"""Exporta os arquivos de documentos para uma pasta local, com manifesto SHA-256 (RNF07).

Uso:
    # documentos do armazenamento do sistema (padrão: pasta local)
    docker compose run --rm web python manage.py exportar_documentos

    # documentos do bucket do Supabase Storage (prefixo SUPABASE_STORAGE_PREFIXO)
    docker compose run --rm web python manage.py exportar_documentos --remoto --confirmar <bucket>

A cópia é criada em backups/documentos/<origem>-<data>/ (fora do Git e da imagem
Docker) e verificada ao final. Somente leitura no armazenamento de origem.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.documentos.backup_remoto import BackupInvalido, chave_segura, exportar, verificar
from apps.documentos.remoto import mascarar, obter_armazenamento, prefixo_dos_documentos


class Command(BaseCommand):
    help = "Exporta os arquivos de documentos para uma pasta local protegida, com manifesto SHA-256."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--remoto", action="store_true", help="Exporta do bucket do Supabase Storage.")
        parser.add_argument("--confirmar", metavar="BUCKET", help="Obrigatório com --remoto: nome exato do bucket.")
        parser.add_argument("--prefixo", help="Prefixo a exportar (padrão: prefixo dos documentos).")
        parser.add_argument("--destino", help="Pasta da cópia (padrão: backups/documentos/<origem>-<data>/).")

    def handle(self, *args, remoto=False, confirmar=None, prefixo=None, destino=None, **opcoes):
        armazenamento, origem = obter_armazenamento(remoto, confirmar, "Exportação")
        if prefixo is None:
            prefixo = prefixo_dos_documentos() if remoto else ""
        prefixo = prefixo.strip().strip("/")
        if destino:
            pasta = Path(destino)
        else:
            rotulo = "supabase" if remoto else "local"
            pasta = Path(settings.BASE_DIR) / "backups" / "documentos" / f"{rotulo}-{timezone.localtime():%Y%m%d-%H%M%S}"
        try:
            if prefixo:
                chave_segura(prefixo)
            self.stdout.write(f"Origem: {origem}, prefixo: {prefixo or '(raiz)'}")
            manifesto = exportar(armazenamento, prefixo, pasta, origem)
            _, problemas = verificar(pasta)
        except BackupInvalido as erro:
            raise CommandError(mascarar(str(erro))) from None
        except Exception as erro:
            raise CommandError(mascarar(f"Falha na exportação ({type(erro).__name__}): {erro}")) from None
        if problemas:
            raise CommandError("A cópia não passou na verificação: " + "; ".join(problemas[:5]))
        self.stdout.write(self.style.SUCCESS(
            f"Exportados {manifesto['total_arquivos']} arquivo(s), {manifesto['total_bytes']} bytes; "
            f"tamanho e SHA-256 conferidos."))
        self.stdout.write(f"Cópia: {pasta}")
        self.stdout.write("A cópia contém documentos privados: guarde-a em local protegido e em outro dispositivo.")
