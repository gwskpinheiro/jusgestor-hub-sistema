"""Teste controlado do armazenamento de documentos: gravar, ler e remover UM arquivo.

Uso:
    # armazenamento configurado no sistema (padrão: pasta local)
    docker compose run --rm web python manage.py verificar_armazenamento

    # bucket do Supabase Storage (exige confirmação com o nome do bucket)
    docker compose run --rm web python manage.py verificar_armazenamento \
        --remoto --confirmar jusgestor-documentos

Garantias:
- O teste usa um prefixo exclusivo (``verificacao-conexao/``), separado dos
  documentos, e uma chave aleatória criada pelo próprio teste.
- Somente operações sobre essa chave: verificar existência, gravar, ler,
  remover. Nada é listado; nenhum outro arquivo é lido, alterado ou removido.
- ``--remoto`` usa as variáveis SUPABASE_STORAGE_* sem alterar o
  armazenamento do sistema (DOCUMENTOS_ARMAZENAMENTO continua como está).
- Credenciais nunca são exibidas: mensagens de erro são mascaradas.
- Não acessa o banco de dados.
"""
import hashlib
import os
import time
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from config.armazenamento import config_supabase

PREFIXO_TESTE = "verificacao-conexao"
VARIAVEIS_SECRETAS = ("SUPABASE_STORAGE_ACCESS_KEY_ID", "SUPABASE_STORAGE_SECRET_ACCESS_KEY")


def conteudo_ficticio(marcador):
    """PDF mínimo e fictício (o bucket pode aceitar apenas tipos de documento)."""
    return (
        b"%PDF-1.4\n% JusGestor Hub - teste de conexao do armazenamento (arquivo ficticio)\n"
        + f"% {marcador}\n".encode()
        + b"%%EOF\n"
    )


def criar_armazenamento_remoto(amb):
    """Cliente S3 do Supabase Storage restrito ao prefixo de teste (sem abrir conexão)."""
    from storages.backends.s3 import S3Storage

    opcoes = dict(config_supabase(amb)["OPTIONS"])
    opcoes["location"] = PREFIXO_TESTE  # nunca o prefixo dos documentos
    return S3Storage(**opcoes), opcoes["bucket_name"]


def mascarar(texto, segredos):
    for segredo in segredos:
        if segredo:
            texto = texto.replace(segredo, "***")
    return texto


class Command(BaseCommand):
    help = "Grava, lê e remove um arquivo fictício para testar o armazenamento de documentos."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--remoto", action="store_true",
                            help="Testa o bucket do Supabase Storage (variáveis SUPABASE_STORAGE_*).")
        parser.add_argument("--confirmar", metavar="BUCKET",
                            help="Obrigatório com --remoto: nome exato do bucket configurado.")

    def handle(self, *args, remoto=False, confirmar=None, **opcoes):
        segredos = [os.environ.get(nome, "") for nome in VARIAVEIS_SECRETAS]
        try:
            if remoto:
                destino, descricao = self.preparar_remoto(confirmar)
            else:
                destino = storages["documentos"]
                descricao = f"armazenamento do sistema ({settings.DOCUMENTOS_ARMAZENAMENTO}), prefixo {PREFIXO_TESTE}/"
            self.executar(destino, descricao, segredos, prefixar=not remoto)
        except CommandError as erro:
            raise CommandError(mascarar(str(erro), segredos)) from None

    def preparar_remoto(self, confirmar):
        bucket = (os.environ.get("SUPABASE_STORAGE_BUCKET") or "").strip()
        if not confirmar:
            raise CommandError(
                "Teste remoto não executado: confirme com --confirmar <nome do bucket>. "
                "Será gravado, lido e removido um único arquivo fictício no prefixo "
                f"{PREFIXO_TESTE}/."
            )
        if not bucket or confirmar != bucket:
            raise CommandError("Teste remoto não executado: --confirmar não corresponde a SUPABASE_STORAGE_BUCKET.")
        faltando = [nome for nome in VARIAVEIS_SECRETAS if not (os.environ.get(nome) or "").strip()]
        if faltando:
            raise CommandError("Teste remoto não executado: preencha no .env " + " e ".join(faltando) + ".")
        try:
            destino, bucket = criar_armazenamento_remoto(os.environ)
        except Exception as erro:  # configuração inválida (endpoint, região...)
            raise CommandError(f"Configuração do Supabase Storage inválida: {erro}") from None
        return destino, f"Supabase Storage, bucket {bucket}, prefixo {PREFIXO_TESTE}/"

    def executar(self, destino, descricao, segredos, prefixar):
        marcador = f"{timezone.now():%Y-%m-%dT%H:%M:%S%z} {uuid.uuid4().hex}"
        conteudo = conteudo_ficticio(marcador)
        esperado = hashlib.sha256(conteudo).hexdigest()
        nome = f"{uuid.uuid4().hex}.pdf"
        chave = f"{PREFIXO_TESTE}/{nome}" if prefixar else nome  # no remoto, o prefixo vem do cliente
        self.stdout.write(f"Destino: {descricao}")
        self.stdout.write(f"Arquivo de teste: {PREFIXO_TESTE}/{nome} ({len(conteudo)} bytes, fictício)")

        resultados = []
        gravado = removido = False

        def etapa(titulo, funcao):
            inicio = time.perf_counter()
            try:
                detalhe = funcao()
            except Exception as erro:
                texto = mascarar(f"{type(erro).__name__}: {erro}", segredos)
                resultados.append((False, titulo, texto))
                self.stdout.write(self.style.ERROR(f"[FALHA] {titulo}: {texto}"))
                return False
            ms = (time.perf_counter() - inicio) * 1000
            resultados.append((True, titulo, detalhe))
            self.stdout.write(self.style.SUCCESS(f"[OK]    {titulo}") + f" ({ms:.0f} ms){' - ' + detalhe if detalhe else ''}")
            return True

        def antes():
            if destino.exists(chave):
                raise RuntimeError("a chave de teste já existe; nada foi gravado")
            return "chave livre"

        def gravar():
            salvo = destino.save(chave, ContentFile(conteudo, name=nome))
            if salvo != chave:
                raise RuntimeError(f"o armazenamento gravou com outro nome ({salvo})")
            return ""

        def confirmar_gravacao():
            if not destino.exists(chave):
                raise RuntimeError("o arquivo gravado não foi encontrado")
            return ""

        def ler():
            with destino.open(chave, "rb") as arquivo:
                lido = arquivo.read()
            obtido = hashlib.sha256(lido).hexdigest()
            if lido != conteudo:
                raise RuntimeError(f"conteúdo diferente do original (SHA-256 {obtido[:12]}… ≠ {esperado[:12]}…)")
            return f"{len(lido)} bytes, SHA-256 idêntico ({esperado[:12]}…)"

        def remover():
            destino.delete(chave)  # somente a chave criada por este teste
            return ""

        def confirmar_remocao():
            if destino.exists(chave):
                raise RuntimeError("o arquivo de teste continua no armazenamento")
            return ""

        try:
            if etapa("Chave de teste livre antes da gravação", antes) and etapa("Gravação", gravar):
                gravado = True
                etapa("Arquivo encontrado após a gravação", confirmar_gravacao)
                etapa("Leitura e integridade", ler)
        finally:
            if gravado:
                removido = etapa("Remoção do arquivo de teste", remover) and etapa("Arquivo ausente após a remoção", confirmar_remocao)

        falhas = [r for r in resultados if not r[0]]
        if gravado and not removido:
            self.stdout.write(self.style.WARNING(
                f"Atenção: remova manualmente apenas {PREFIXO_TESTE}/{nome}, se ainda existir."))
        if falhas:
            raise CommandError(f"Teste do armazenamento falhou em {len(falhas)} etapa(s).")
        self.stdout.write(self.style.SUCCESS(
            "Armazenamento verificado: gravação, leitura, integridade e remoção funcionaram."))
