"""Tabelas ``processo`` e ``acesso_processo`` (Figura 3)."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.usuarios.models import Perfil


class SituacaoProcesso(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    ENCERRADO = "encerrado", "Encerrado"


class Processo(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="processos", verbose_name="cliente")
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="processos_responsavel", verbose_name="advogado responsável",
    )
    # RN01: quando informado, único no escritório. NULL não conflita no PostgreSQL.
    numero = models.CharField(
        "número processual", max_length=30, null=True, blank=True, unique=True,
        error_messages={"unique": "Já existe um processo com este número no escritório."},
    )
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição", null=True, blank=True)
    situacao = models.CharField("situação", max_length=30, choices=SituacaoProcesso.choices,
                                default=SituacaoProcesso.ATIVO)
    arquivado = models.BooleanField("arquivado", default=False)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "processo"
        ordering = ["-criado_em"]
        constraints = [
            models.CheckConstraint(condition=models.Q(situacao__in=SituacaoProcesso.values),
                                   name="processo_situacao_valida"),
        ]

    def __str__(self):
        return f"{self.numero} — {self.titulo}" if self.numero else self.titulo

    def get_absolute_url(self):
        return reverse("processos:detalhe", args=[self.pk])

    def clean(self):
        # RN01: responsável deve ser ADM ou ADV.
        if self.responsavel_id and self.responsavel.perfil not in (Perfil.ADM, Perfil.ADV):
            raise ValidationError({"responsavel": "O responsável deve ser administrador ou advogado."})


class AcessoProcesso(models.Model):
    """Autorização explícita de um usuário (ADV/AST) sobre um processo (RF09)."""

    pk = models.CompositePrimaryKey("usuario_id", "processo_id")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="acessos_processo")
    processo = models.ForeignKey(Processo, on_delete=models.CASCADE, related_name="acessos")

    class Meta:
        db_table = "acesso_processo"
