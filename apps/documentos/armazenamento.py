"""Validação e gravação privada dos arquivos de documentos (RN04, RF06).

- Extensão, tamanho e conteúdo (assinatura do arquivo) são verificados.
- O arquivo é gravado no armazenamento "documentos" (pasta local ou bucket
  privado do Supabase Storage, ver config/armazenamento.py), fora dos
  diretórios públicos, com um nome gerado pelo sistema; o nome original é
  guardado apenas para o download.
- O acesso ao arquivo só ocorre pelas views de download e visualização, que
  verificam a permissão do usuário sobre o documento.
"""
import logging
import re
import uuid
import zipfile
from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.storage import storages
from django.db import transaction
from django.db.models import Max

from .models import TAMANHO_MAXIMO, TIPOS_PERMITIDOS, Documento, VersaoDocumento

logger = logging.getLogger(__name__)

ASSINATURAS = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}


def _extensao(nome):
    return Path(nome or "").suffix.lower().lstrip(".")


def _nome_seguro(nome):
    """Remove caminhos e caracteres de controle do nome original."""
    nome = Path(str(nome).replace("\\", "/")).name
    nome = "".join(c for c in nome if c.isprintable() and c not in '"<>|')
    return (nome or "arquivo")[:255]


def _docx_valido(arquivo):
    try:
        with zipfile.ZipFile(arquivo) as zip_:
            return "word/document.xml" in zip_.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    finally:
        arquivo.seek(0)


def validar_arquivo(arquivo):
    """Retorna a extensão normalizada ou lança ValidationError."""
    if arquivo is None:
        raise ValidationError("Selecione um arquivo.")
    extensao = _extensao(arquivo.name)
    if extensao not in TIPOS_PERMITIDOS:
        raise ValidationError("Tipo de arquivo não permitido. Envie PDF, DOCX, PNG ou JPEG.")
    if arquivo.size == 0:
        raise ValidationError("O arquivo está vazio.")
    if arquivo.size > TAMANHO_MAXIMO:
        raise ValidationError("O arquivo excede o limite de 10 MiB.")
    arquivo.seek(0)
    inicio = arquivo.read(8)
    arquivo.seek(0)
    if extensao == "docx":
        valido = inicio.startswith(b"PK\x03\x04") and _docx_valido(arquivo)
    else:
        valido = inicio.startswith(ASSINATURAS[extensao])
    if not valido:
        raise ValidationError("O conteúdo do arquivo não corresponde a um arquivo PDF, DOCX, PNG ou JPEG válido.")
    return extensao


# ---------------------------------------------------------------------------
# Destino dos arquivos (pasta local ou Supabase Storage, ver config/armazenamento.py)
# ---------------------------------------------------------------------------

# Chave gravada em versao_documento.caminho_arquivo: "<id do documento>/<uuid>.<ext>".
# É a mesma em qualquer destino; o prefixo do bucket fica na configuração.
_CHAVE = re.compile(r"(?P<documento>[1-9][0-9]*)/[0-9a-f]{32}\.(?P<extensao>pdf|docx|png|jpg|jpeg)")


class ArquivoIndisponivel(Exception):
    """O arquivo não existe ou o registro aponta para uma chave inválida (resposta 404)."""


class ArmazenamentoIndisponivel(Exception):
    """O destino de armazenamento falhou (rede, credenciais, serviço fora do ar)."""

    mensagem = "Não foi possível acessar o armazenamento de documentos. Tente novamente em instantes."

    def __init__(self, mensagem=None):
        super().__init__(mensagem or self.mensagem)


def armazenamento():
    return storages["documentos"]


def gerar_chave(documento, extensao):
    return f"{documento.pk}/{uuid.uuid4().hex}.{extensao}"


def chave_da_versao(versao):
    """Valida a chave gravada no banco antes de qualquer acesso ao armazenamento.

    Recusa caminhos absolutos, "..", barras invertidas e chaves de outro documento
    ou de outra extensão: um registro adulterado nunca alcança outro arquivo.
    """
    chave = versao.caminho_arquivo or ""
    encontrado = _CHAVE.fullmatch(chave)
    if (not encontrado or int(encontrado["documento"]) != versao.documento_id
            or encontrado["extensao"] != versao.extensao):
        raise ArquivoIndisponivel("Chave de arquivo inválida.")
    return chave


def abrir_versao(versao):
    """Abre o arquivo de uma versão para leitura (a autorização é verificada antes, na view)."""
    chave = chave_da_versao(versao)
    try:
        return armazenamento().open(chave, "rb")
    except (FileNotFoundError, SuspiciousFileOperation) as erro:
        raise ArquivoIndisponivel("Arquivo não encontrado.") from erro
    except Exception as erro:
        logger.exception("Falha ao ler a versão %s no armazenamento de documentos.", versao.pk)
        raise ArmazenamentoIndisponivel() from erro


def _remover(destino, chave):
    try:
        destino.delete(chave)
    except Exception:
        logger.exception("Não foi possível remover o arquivo órfão %s.", chave)


def gravar_versao(documento, arquivo, autor):
    """Grava o arquivo e registra uma nova versão do documento.

    O arquivo é gravado antes do registro: se a gravação falhar, nada é
    registrado; se o registro falhar, o arquivo gravado é removido. Versões
    anteriores nunca são sobrescritas (cada versão recebe uma chave nova).
    """
    extensao = validar_arquivo(arquivo)
    chave = gerar_chave(documento, extensao)
    destino = armazenamento()
    # Tipo gravado no armazenamento: o da extensão já validada pelo conteúdo,
    # nunca o informado pelo navegador (que pode faltar ou estar errado).
    arquivo.content_type = TIPOS_PERMITIDOS[extensao]
    arquivo.seek(0)
    try:
        salvo = destino.save(chave, arquivo)
    except Exception as erro:
        _remover(destino, chave)
        logger.exception("Falha ao gravar o arquivo do documento %s.", documento.pk)
        raise ArmazenamentoIndisponivel() from erro
    if salvo != chave:
        # O destino renomeou o arquivo (chave já existente): não registra nada.
        _remover(destino, salvo)
        raise ArmazenamentoIndisponivel()
    try:
        with transaction.atomic():
            # Bloqueia o documento para numerar as versões sem conflito.
            Documento.objects.select_for_update().filter(pk=documento.pk).first()
            ultima = documento.versoes.aggregate(n=Max("numero_versao"))["n"] or 0
            return VersaoDocumento.objects.create(
                documento=documento,
                autor=autor,
                numero_versao=ultima + 1,
                nome_arquivo=_nome_seguro(arquivo.name),
                caminho_arquivo=chave,
                extensao=extensao,
                tamanho_bytes=arquivo.size,
            )
    except Exception:
        _remover(destino, chave)
        raise
