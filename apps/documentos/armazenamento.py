"""Validação e gravação privada dos arquivos de documentos (RN04, RF06).

- Extensão, tamanho e conteúdo (assinatura do arquivo) são verificados.
- O arquivo é gravado em DOCUMENTOS_ROOT, fora dos diretórios públicos, com um
  nome gerado pelo sistema; o nome original é guardado apenas para o download.
- O acesso ao arquivo só ocorre pela view de download, que verifica a
  permissão do usuário sobre o documento.
"""
import os
import uuid
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from .models import TAMANHO_MAXIMO, TIPOS_PERMITIDOS, Documento, VersaoDocumento

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


def raiz():
    return Path(settings.DOCUMENTOS_ROOT)


def caminho_absoluto(versao):
    """Resolve o caminho do arquivo e garante que ele está dentro da raiz privada."""
    base = raiz().resolve()
    caminho = (base / versao.caminho_arquivo).resolve()
    if base not in caminho.parents:
        raise ValidationError("Caminho de arquivo inválido.")
    return caminho


def gravar_versao(documento, arquivo, autor):
    """Grava o arquivo e registra uma nova versão do documento."""
    extensao = validar_arquivo(arquivo)
    relativo = Path(str(documento.pk)) / f"{uuid.uuid4().hex}.{extensao}"
    destino = raiz() / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".parcial")
    with open(temporario, "wb") as saida:
        for bloco in arquivo.chunks():
            saida.write(bloco)
    os.replace(temporario, destino)
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
                caminho_arquivo=relativo.as_posix(),
                extensao=extensao,
                tamanho_bytes=arquivo.size,
            )
    except Exception:
        destino.unlink(missing_ok=True)
        raise
