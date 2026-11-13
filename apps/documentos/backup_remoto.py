"""Exportação, verificação e restauração dos arquivos de documentos (RNF07).

Funciona com qualquer armazenamento do Django (pasta local, Supabase Storage via
S3, armazenamento simulado nos testes). Estrutura de uma cópia:

    <pasta>/
      arquivos/<chave>          cópia de cada arquivo, com a chave original
      manifesto.json            origem, prefixo, data e, para cada arquivo:
                                chave, tamanho e SHA-256
      manifesto.sha256          mesma lista no formato do "sha256sum -c"
      manifesto.json.sha256     SHA-256 do próprio manifesto (detecta alteração)

As chaves no manifesto são relativas ao prefixo exportado. Com o prefixo dos
documentos (SUPABASE_STORAGE_PREFIXO), elas são iguais a
versao_documento.caminho_arquivo, o que mantém os vínculos com o banco.

Regras de segurança:
- chaves com "..", caminhos absolutos ou caracteres fora de [A-Za-z0-9._-]
  são recusadas (na exportação e na restauração);
- a exportação nunca grava em uma pasta que já tenha conteúdo;
- a restauração verifica a cópia inteira antes de enviar qualquer arquivo e
  nunca sobrescreve um arquivo diferente sem autorização explícita.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from django.core.files.base import File
from django.utils import timezone

FORMATO = 1
MANIFESTO = "manifesto.json"
LISTA_SHA256 = "manifesto.sha256"
SHA_DO_MANIFESTO = "manifesto.json.sha256"
PASTA_ARQUIVOS = "arquivos"
BLOCO = 1024 * 1024
_SEGMENTO = re.compile(r"^[A-Za-z0-9._-]+$")


class BackupInvalido(Exception):
    """Cópia ausente, alterada ou insegura; nenhuma restauração é feita."""


def juntar(*partes):
    return "/".join(p.strip("/") for p in partes if p and p.strip("/"))


def chave_segura(chave):
    partes = (chave or "").split("/")
    if (not chave or chave.startswith("/") or "\\" in chave
            or any(p in ("", ".", "..") or not _SEGMENTO.match(p) for p in partes)):
        raise BackupInvalido(f"Chave de arquivo insegura ou inválida: {chave!r}")
    return chave


def percorrer(destino, prefixo):
    """Chaves de todos os arquivos sob o prefixo (somente dentro dele)."""
    try:
        pastas, arquivos = destino.listdir(prefixo)
    except FileNotFoundError:
        return
    for nome in sorted(arquivos):
        yield juntar(prefixo, nome)
    for pasta in sorted(pastas):
        yield from percorrer(destino, juntar(prefixo, pasta))


def _copiar(origem, saida):
    resumo, tamanho = hashlib.sha256(), 0
    for bloco in iter(lambda: origem.read(BLOCO), b""):
        resumo.update(bloco)
        saida.write(bloco)
        tamanho += len(bloco)
    return tamanho, resumo.hexdigest()


def sha256_de_arquivo(caminho):
    resumo = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(BLOCO), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def sha256_no_armazenamento(destino, chave):
    resumo = hashlib.sha256()
    with destino.open(chave, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(BLOCO), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _proteger(caminho, modo):
    try:
        os.chmod(caminho, modo)  # sem efeito em alguns volumes do Windows
    except OSError:
        pass


def exportar(destino, prefixo, pasta, origem_descricao):
    """Copia todos os arquivos sob o prefixo para a pasta local. Retorna o manifesto."""
    pasta = Path(pasta)
    if pasta.exists() and any(pasta.iterdir()):
        raise BackupInvalido(f"A pasta de destino já existe e não está vazia: {pasta}")
    arquivos = pasta / PASTA_ARQUIVOS
    arquivos.mkdir(parents=True, exist_ok=True)
    _proteger(pasta, 0o700)
    itens = []
    for chave_completa in percorrer(destino, prefixo):
        relativa = chave_completa[len(prefixo):].lstrip("/") if prefixo else chave_completa
        chave_segura(relativa)
        alvo = arquivos / relativa
        alvo.parent.mkdir(parents=True, exist_ok=True)
        parcial = alvo.with_name(alvo.name + ".parcial")
        with destino.open(chave_completa, "rb") as origem, open(parcial, "wb") as saida:
            tamanho, resumo = _copiar(origem, saida)
        os.replace(parcial, alvo)
        _proteger(alvo, 0o600)
        itens.append({"chave": relativa, "tamanho": tamanho, "sha256": resumo})
    manifesto = {
        "formato": FORMATO,
        "origem": origem_descricao,
        "prefixo": prefixo,
        "criado_em": timezone.localtime().isoformat(timespec="seconds"),
        "total_arquivos": len(itens),
        "total_bytes": sum(i["tamanho"] for i in itens),
        "arquivos": itens,
    }
    caminho_manifesto = pasta / MANIFESTO
    caminho_manifesto.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (pasta / LISTA_SHA256).write_text(
        "".join(f"{i['sha256']}  {PASTA_ARQUIVOS}/{i['chave']}\n" for i in itens), encoding="utf-8")
    (pasta / SHA_DO_MANIFESTO).write_text(f"{sha256_de_arquivo(caminho_manifesto)}  {MANIFESTO}\n", encoding="utf-8")
    for nome in (MANIFESTO, LISTA_SHA256, SHA_DO_MANIFESTO):
        _proteger(pasta / nome, 0o600)
    return manifesto


def ler_manifesto(pasta):
    pasta = Path(pasta)
    caminho = pasta / MANIFESTO
    if not caminho.is_file():
        raise BackupInvalido(f"Manifesto não encontrado em {pasta}.")
    registrado = (pasta / SHA_DO_MANIFESTO).read_text(encoding="utf-8").split()[0] \
        if (pasta / SHA_DO_MANIFESTO).is_file() else None
    if registrado != sha256_de_arquivo(caminho):
        raise BackupInvalido("O manifesto foi alterado ou está sem o arquivo de conferência.")
    manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    if manifesto.get("formato") != FORMATO:
        raise BackupInvalido("Formato de manifesto desconhecido.")
    return manifesto


def verificar(pasta):
    """Confere cada arquivo da cópia. Retorna (manifesto, lista de problemas)."""
    pasta = Path(pasta)
    manifesto = ler_manifesto(pasta)
    problemas, esperados = [], set()
    for item in manifesto["arquivos"]:
        try:
            chave = chave_segura(item["chave"])
        except BackupInvalido as erro:
            problemas.append(str(erro))
            continue
        esperados.add(chave)
        caminho = pasta / PASTA_ARQUIVOS / chave
        if not caminho.is_file():
            problemas.append(f"{chave}: arquivo ausente")
        elif caminho.stat().st_size != item["tamanho"]:
            problemas.append(f"{chave}: tamanho diferente do manifesto")
        elif sha256_de_arquivo(caminho) != item["sha256"]:
            problemas.append(f"{chave}: SHA-256 diferente do manifesto")
    raiz = pasta / PASTA_ARQUIVOS
    if raiz.is_dir():
        for caminho in sorted(p for p in raiz.rglob("*") if p.is_file()):
            relativa = caminho.relative_to(raiz).as_posix()
            if relativa not in esperados:
                problemas.append(f"{relativa}: arquivo fora do manifesto")
    if manifesto["total_arquivos"] != len(manifesto["arquivos"]):
        problemas.append("total_arquivos não confere com a lista do manifesto")
    return manifesto, problemas


def restaurar(destino, pasta, prefixo_destino, sobrescrever=False):
    """Envia os arquivos da cópia para o armazenamento, nas chaves originais
    (ou sob prefixo_destino). Retorna {"restaurado": [...], "identico": [...],
    "conflito": [...], "sobrescrito": [...]}.
    """
    pasta = Path(pasta)
    manifesto, problemas = verificar(pasta)
    if problemas:
        raise BackupInvalido("A cópia não passou na verificação; nada foi restaurado: " + "; ".join(problemas[:5]))
    resultado = {"restaurado": [], "identico": [], "conflito": [], "sobrescrito": []}
    for item in manifesto["arquivos"]:
        relativa = item["chave"]
        chave = juntar(prefixo_destino, relativa)
        local = pasta / PASTA_ARQUIVOS / relativa
        if destino.exists(chave):
            if sha256_no_armazenamento(destino, chave) == item["sha256"]:
                resultado["identico"].append(chave)
                continue
            if not sobrescrever:
                resultado["conflito"].append(chave)  # arquivo diferente: mantido como está
                continue
            destino.delete(chave)
            situacao = "sobrescrito"
        else:
            situacao = "restaurado"
        with open(local, "rb") as conteudo:
            salvo = destino.save(chave, File(conteudo, name=Path(relativa).name))
        if salvo != chave:
            destino.delete(salvo)  # o armazenamento renomeou: desfaz o envio
            raise BackupInvalido(f"{chave}: o armazenamento gravou com outro nome; envio desfeito.")
        if sha256_no_armazenamento(destino, chave) != item["sha256"]:
            raise BackupInvalido(f"{chave}: conteúdo restaurado difere da cópia.")
        resultado[situacao].append(chave)
    return resultado
