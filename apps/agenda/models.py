"""Tabelas ``compromisso`` e ``participante_compromisso`` (Figura 3)."""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.processos.models import Processo


class TipoCompromisso(models.TextChoices):
    COMPROMISSO = "compromisso", "Compromisso"
    TAREFA = "tarefa", "Tarefa"
    PRAZO = "prazo", "Prazo"


class SituacaoCompromisso(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    CONCLUIDO = "concluido", "Concluído"
    CANCELADO = "cancelado", "Cancelado"


class Destaque(models.TextChoices):
    VENCIDO = "vencido", "Vencido"
    PROXIMO = "proximo", "Próximas 24 horas"


class Compromisso(models.Model):
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="compromissos_responsavel", verbose_name="responsável",
    )
    processo = models.ForeignKey(
        Processo, on_delete=models.PROTECT, null=True, blank=True,
        related_name="compromissos", verbose_name="processo",
    )
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição", null=True, blank=True)
    tipo = models.CharField("tipo", max_length=20, choices=TipoCompromisso.choices, default=TipoCompromisso.COMPROMISSO)
    inicio = models.DateTimeField("data e hora")
    fim = models.DateTimeField("término", null=True, blank=True)
    situacao = models.CharField("situação", max_length=20, choices=SituacaoCompromisso.choices,
                                default=SituacaoCompromisso.PENDENTE)

    class Meta:
        db_table = "compromisso"
        ordering = ["inicio"]
        constraints = [
            models.CheckConstraint(condition=models.Q(tipo__in=TipoCompromisso.values), name="compromisso_tipo_valido"),
            models.CheckConstraint(condition=models.Q(situacao__in=SituacaoCompromisso.values),
                                   name="compromisso_situacao_valida"),
            models.CheckConstraint(condition=models.Q(fim__isnull=True) | models.Q(fim__gte=models.F("inicio")),
                                   name="compromisso_fim_apos_inicio"),
        ]

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse("agenda:detalhe", args=[self.pk])

    def destaque(self, agora=None):
        """RN02: destaca pendências vencidas e das próximas 24 horas.

        Calculado no momento da consulta (ao abrir/atualizar agenda e painel,
        RF04). Não calcula prazos legais: usa apenas as datas informadas.
        """
        if self.situacao != SituacaoCompromisso.PENDENTE:
            return None
        agora = agora or timezone.now()
        if (self.fim or self.inicio) < agora:
            return Destaque.VENCIDO
        if self.inicio <= agora + timedelta(hours=24):
            return Destaque.PROXIMO
        return None


class ParticipanteCompromisso(models.Model):
    pk = models.CompositePrimaryKey("compromisso_id", "usuario_id")
    compromisso = models.ForeignKey(Compromisso, on_delete=models.CASCADE, related_name="participantes")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="participacoes")

    class Meta:
        db_table = "participante_compromisso"


def pendencias_destacadas(qs, agora=None):
    """Compromissos pendentes vencidos ou das próximas 24 horas, para agenda e painel."""
    agora = agora or timezone.now()
    return qs.filter(situacao=SituacaoCompromisso.PENDENTE, inicio__lte=agora + timedelta(hours=24))
