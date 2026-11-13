"""Acesso controlado ao Supabase Storage pelos comandos de manutenção.

Os comandos usam o armazenamento local por padrão. O bucket só é acessado com
--remoto e --confirmar <nome exato do bucket>, e o armazenamento do sistema
(DOCUMENTOS_ARMAZENAMENTO) não é alterado. Credenciais nunca são exibidas.
"""
import os

from django.core.management.base import CommandError

from config.armazenamento import config_supabase

VARIAVEIS_SECRETAS = ("SUPABASE_STORAGE_ACCESS_KEY_ID", "SUPABASE_STORAGE_SECRET_ACCESS_KEY")


def mascarar(texto):
    for nome in VARIAVEIS_SECRETAS:
        segredo = os.environ.get(nome) or ""
        if segredo:
            texto = texto.replace(segredo, "***")
    return texto


def bucket_configurado():
    return (os.environ.get("SUPABASE_STORAGE_BUCKET") or "").strip()


def prefixo_dos_documentos():
    return (os.environ.get("SUPABASE_STORAGE_PREFIXO") or "documentos").strip().strip("/")


def criar_cliente(amb, location=""):
    """Cliente S3 com a raiz do bucket (ou o prefixo indicado). Não abre conexão."""
    from storages.backends.s3 import S3Storage

    opcoes = dict(config_supabase(amb)["OPTIONS"])
    opcoes["location"] = location
    return S3Storage(**opcoes)


def obter_armazenamento(remoto, confirmar, acao):
    """(armazenamento, descrição): o do sistema (padrão) ou o bucket, se --remoto."""
    if remoto:
        destino, bucket = preparar_remoto(confirmar, acao)
        return destino, f"supabase:{bucket}"
    from django.conf import settings
    from django.core.files.storage import storages

    return storages["documentos"], f"sistema:{settings.DOCUMENTOS_ARMAZENAMENTO}"


def preparar_remoto(confirmar, acao):
    """Valida a confirmação e as variáveis; devolve (armazenamento, bucket)."""
    bucket = bucket_configurado()
    if not confirmar:
        raise CommandError(f"{acao} no Supabase Storage não executado: confirme com --confirmar <nome do bucket>.")
    if not bucket or confirmar != bucket:
        raise CommandError(f"{acao} não executado: --confirmar não corresponde a SUPABASE_STORAGE_BUCKET.")
    faltando = [nome for nome in VARIAVEIS_SECRETAS if not (os.environ.get(nome) or "").strip()]
    if faltando:
        raise CommandError(f"{acao} não executado: preencha no .env " + " e ".join(faltando) + ".")
    try:
        return criar_cliente(os.environ), bucket
    except Exception as erro:
        raise CommandError(mascarar(f"Configuração do Supabase Storage inválida: {erro}")) from None
