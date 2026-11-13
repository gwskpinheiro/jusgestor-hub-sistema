"""Destino dos arquivos de documentos, escolhido por variáveis de ambiente (RF06, RN04).

DOCUMENTOS_ARMAZENAMENTO=local     pasta DOCUMENTOS_ROOT (Docker: volume "documentos")
                                   — padrão, usado no desenvolvimento e nos testes.
DOCUMENTOS_ARMAZENAMENTO=supabase  bucket PRIVADO do Supabase Storage pela API
                                   compatível com S3 (django-storages + boto3)
                                   — destino do sistema publicado no Render.

Nos dois casos o banco guarda a mesma chave relativa ("<documento>/<uuid>.<ext>"),
e os arquivos só chegam ao navegador pelas views do Django, que verificam a
permissão do usuário. O bucket nunca gera URLs públicas.

As funções recebem o mapeamento de ambiente como parâmetro para poderem ser
testadas sem conexão real e sem ler o .env. Credenciais nunca aparecem nas
mensagens de erro.
"""
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from config.banco import e_host_supabase

ARMAZENAMENTO_LOCAL = "local"
ARMAZENAMENTO_SUPABASE = "supabase"
ARMAZENAMENTOS = (ARMAZENAMENTO_LOCAL, ARMAZENAMENTO_SUPABASE)

BACKEND_LOCAL = "apps.documentos.backends.ArmazenamentoLocal"
BACKEND_S3 = "storages.backends.s3.S3Storage"

PREFIXO_PADRAO = "documentos"
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PREFIXO = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*$")
_REGIAO = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")


def _texto(amb, nome, padrao=""):
    return (amb.get(nome) or padrao).strip()


def _obrigatoria(amb, nome):
    valor = _texto(amb, nome)
    if not valor:
        raise ImproperlyConfigured(f"Variável de ambiente obrigatória ausente: {nome}")
    return valor


def alvo_armazenamento(amb):
    alvo = _texto(amb, "DOCUMENTOS_ARMAZENAMENTO", ARMAZENAMENTO_LOCAL).lower()
    if alvo not in ARMAZENAMENTOS:
        raise ImproperlyConfigured(
            f"DOCUMENTOS_ARMAZENAMENTO deve ser um destes valores: {', '.join(ARMAZENAMENTOS)}."
        )
    return alvo


def config_local():
    # A pasta é lida de settings.DOCUMENTOS_ROOT a cada uso (ver apps/documentos/backends.py).
    return {"BACKEND": BACKEND_LOCAL}


def config_supabase(amb):
    """Bucket privado do Supabase Storage pela API S3. Não abre conexão."""
    endpoint = _obrigatoria(amb, "SUPABASE_STORAGE_ENDPOINT").rstrip("/")
    partes = urlsplit(endpoint)
    if partes.scheme != "https" or not e_host_supabase(partes.hostname):
        raise ImproperlyConfigured(
            "SUPABASE_STORAGE_ENDPOINT deve ser o endereço https do Supabase Storage "
            "(Storage > Settings > S3 Connection)."
        )
    regiao = _obrigatoria(amb, "SUPABASE_STORAGE_REGION")
    if not _REGIAO.match(regiao):
        raise ImproperlyConfigured("SUPABASE_STORAGE_REGION inválida (ex.: sa-east-1).")
    bucket = _obrigatoria(amb, "SUPABASE_STORAGE_BUCKET")
    if not _BUCKET.match(bucket):
        raise ImproperlyConfigured("SUPABASE_STORAGE_BUCKET inválido: use letras minúsculas, números, ponto ou hífen.")
    prefixo = _texto(amb, "SUPABASE_STORAGE_PREFIXO", PREFIXO_PADRAO).strip("/")
    if not _PREFIXO.match(prefixo):
        raise ImproperlyConfigured("SUPABASE_STORAGE_PREFIXO inválido: use letras minúsculas, números, _ e -.")
    chave_id = _obrigatoria(amb, "SUPABASE_STORAGE_ACCESS_KEY_ID")
    segredo = _obrigatoria(amb, "SUPABASE_STORAGE_SECRET_ACCESS_KEY")

    # Importado só neste modo: o ambiente local não depende do botocore.
    from botocore.config import Config

    return {
        "BACKEND": BACKEND_S3,
        "OPTIONS": {
            "endpoint_url": endpoint,
            "region_name": regiao,
            "bucket_name": bucket,
            "location": prefixo,
            "access_key": chave_id,
            "secret_key": segredo,
            # Privado: sem ACL pública; nunca sobrescreve (cada versão tem chave nova).
            "default_acl": None,
            "file_overwrite": False,
            # Se algum código chamar url(), o link é assinado e expira em 60 s.
            # O sistema não usa url(): os arquivos saem pelas views do Django.
            "querystring_auth": True,
            "querystring_expire": 60,
            "object_parameters": {"CacheControl": "private, no-store"},
            "client_config": Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                # Somadores de verificação apenas quando o serviço exige: evita
                # incompatibilidades de provedores S3 com o padrão do boto3 >= 1.36.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        },
    }


def config_armazenamento(amb, alvo):
    return config_supabase(amb) if alvo == ARMAZENAMENTO_SUPABASE else config_local()


def verificar_armazenamento_de_teste(alvo, storages):
    """Os testes automatizados só usam o armazenamento local (nunca o Supabase)."""
    backend = storages.get("documentos", {}).get("BACKEND")
    if alvo != ARMAZENAMENTO_LOCAL or backend != BACKEND_LOCAL:
        raise ImproperlyConfigured(
            "Os testes automatizados exigem DOCUMENTOS_ARMAZENAMENTO=local. "
            "Execução interrompida antes de acessar qualquer armazenamento remoto."
        )
