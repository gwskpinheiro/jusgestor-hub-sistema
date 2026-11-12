"""Tabelas ``documento`` e ``versao_documento`` (Figura 3)."""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.processos.models import Processo

# RN04: PDF, DOCX, PNG e JPEG até 10 MiB.
TIPOS_PERMITIDOS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
TAMANHO_MAXIMO = 10 * 1024 * 1024


class Documento(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="documentos", verbose_name="cliente")
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="documentos", verbose_name="processo")
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição", null=True, blank=True)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "documento"
        ordering = ["-criado_em"]
        constraints = [
            # RN04: vinculado a um cliente ou processo.
            models.CheckConstraint(
                condition=models.Q(cliente__isnull=False) | models.Q(processo__isnull=False),
                name="documento_vinculado",
            ),
        ]

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse("documentos:detalhe", args=[self.pk])

    @property
    def versao_atual(self):
        return self.versoes.order_by("-numero_versao").first()


class VersaoDocumento(models.Model):
    """Cada envio gera uma nova versão; versões anteriores são preservadas (RN04)."""

    documento = models.ForeignKey(Documento, on_delete=models.PROTECT, related_name="versoes")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="versoes_documento", verbose_name="autor")
    numero_versao = models.PositiveIntegerField("versão")
    nome_arquivo = models.CharField("nome do arquivo", max_length=255)
    # Caminho relativo a DOCUMENTOS_ROOT, gerado pelo sistema (nunca o nome enviado).
    caminho_arquivo = models.TextField("caminho do arquivo")
    extensao = models.CharField("extensão", max_length=5)
    tamanho_bytes = models.BigIntegerField("tamanho (bytes)")
    enviado_em = models.DateTimeField("enviado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "versao_documento"
        ordering = ["-numero_versao"]
        constraints = [
            models.UniqueConstraint(fields=["documento", "numero_versao"], name="versao_documento_numero_unico"),
            models.CheckConstraint(condition=models.Q(extensao__in=list(TIPOS_PERMITIDOS)),
                                   name="versao_documento_extensao_valida"),
            models.CheckConstraint(
                condition=models.Q(tamanho_bytes__gt=0) & models.Q(tamanho_bytes__lte=TAMANHO_MAXIMO),
                name="versao_documento_tamanho_valido",
            ),
        ]

    def __str__(self):
        return f"{self.nome_arquivo} (v{self.numero_versao})"
