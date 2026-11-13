"""Restaura os arquivos de uma cópia nas chaves originais (RNF07).

Uso:
    # verificar antes de restaurar
    docker compose run --rm web python manage.py verificar_backup_documentos <pasta>

    # restaurar no bucket, nos caminhos originais (prefixo do manifesto)
    docker compose run --rm web python manage.py restaurar_documentos <pasta> --remoto --confirmar <bucket>

Regras:
- a cópia é verificada inteira antes de qualquer envio;
- arquivo já existente e idêntico: ignorado;
- arquivo existente e DIFERENTE: não é alterado (conflito), a menos que
  --sobrescrever seja usado junto com --confirmar-sobrescrita <bucket> (ou
  "local" no armazenamento local);
- cada arquivo enviado é relido e conferido pelo SHA-256;
- nenhum arquivo fora da cópia é removido.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.documentos.backup_remoto import BackupInvalido, chave_segura, ler_manifesto, restaurar
from apps.documentos.remoto import bucket_configurado, mascarar, obter_armazenamento


class Command(BaseCommand):
    help = "Restaura uma cópia de documentos preservando as chaves, sem sobrescrever sem autorização."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("pasta", help="Pasta da cópia (contém manifesto.json).")
        parser.add_argument("--remoto", action="store_true", help="Restaura no bucket do Supabase Storage.")
        parser.add_argument("--confirmar", metavar="BUCKET", help="Obrigatório com --remoto: nome exato do bucket.")
        parser.add_argument("--prefixo-destino", help="Prefixo de destino (padrão: o prefixo original do manifesto).")
        parser.add_argument("--sobrescrever", action="store_true",
                            help="Substitui arquivos existentes e diferentes (exige --confirmar-sobrescrita).")
        parser.add_argument("--confirmar-sobrescrita", metavar="BUCKET",
                            help='Nome do bucket (ou "local") para autorizar --sobrescrever.')

    def handle(self, *args, pasta, remoto=False, confirmar=None, prefixo_destino=None,
               sobrescrever=False, confirmar_sobrescrita=None, **opcoes):
        if sobrescrever:
            esperado = bucket_configurado() if remoto else "local"
            if not esperado or confirmar_sobrescrita != esperado:
                raise CommandError("Sobrescrita não autorizada: use --confirmar-sobrescrita com o nome do "
                                   "bucket (ou \"local\"). Nada foi restaurado.")
        try:
            manifesto = ler_manifesto(pasta)
            destino_prefixo = (manifesto["prefixo"] if prefixo_destino is None else prefixo_destino).strip().strip("/")
            if destino_prefixo:
                chave_segura(destino_prefixo)
        except BackupInvalido as erro:
            raise CommandError(str(erro)) from None
        armazenamento, destino = obter_armazenamento(remoto, confirmar, "Restauração")
        self.stdout.write(f"Destino: {destino}, prefixo: {destino_prefixo or '(raiz)'}"
                          f"{' (sobrescrita autorizada)' if sobrescrever else ''}")
        try:
            resultado = restaurar(armazenamento, pasta, destino_prefixo, sobrescrever=sobrescrever)
        except BackupInvalido as erro:
            raise CommandError(mascarar(str(erro))) from None
        except Exception as erro:
            raise CommandError(mascarar(f"Falha na restauração ({type(erro).__name__}): {erro}")) from None
        self.stdout.write(
            f"Restaurados: {len(resultado['restaurado'])} | já presentes e idênticos: {len(resultado['identico'])} | "
            f"sobrescritos: {len(resultado['sobrescrito'])} | conflitos: {len(resultado['conflito'])}")
        if resultado["conflito"]:
            for chave in resultado["conflito"]:
                self.stdout.write(self.style.WARNING(f"[CONFLITO] {chave}: existe com conteúdo diferente; mantido."))
            raise CommandError("Restauração incompleta: há arquivos diferentes no destino (não foram alterados).")
        self.stdout.write(self.style.SUCCESS("Restauração concluída: todos os arquivos conferidos pelo SHA-256."))
