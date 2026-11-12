"""Tabela ``registro_hora`` (Figura 3)."""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.processos.models import Processo


class RegistroHora(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                related_name="registros_hora", verbose_name="usuário")
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, related_name="registros_hora",
                                 verbose_name="processo")
    atividade = models.TextField("atividade")
    data_atividade = models.DateField("data da atividade")
    minutos = models.PositiveIntegerField("minutos")
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "registro_hora"
        ordering = ["-data_atividade", "-criado_em"]
        constraints = [
            models.CheckConstraint(condition=models.Q(minutos__gt=0), name="registro_hora_minutos_positivos"),
        ]

    def __str__(self):
        return f"{self.data_atividade:%d/%m/%Y} — {self.minutos} min"

    def get_absolute_url(self):
        return reverse("horas:editar", args=[self.pk])

