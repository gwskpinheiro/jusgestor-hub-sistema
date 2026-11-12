"""Tabelas ``lancamento_financeiro`` e ``cobranca_hora`` (Figura 3)."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.processos.models import Processo


class TipoLancamento(models.TextChoices):
    RECEITA = "receita", "Receita"
    DESPESA = "despesa", "Despesa"


class SituacaoLancamento(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    QUITADO = "quitado", "Quitado"
    CANCELADO = "cancelado", "Cancelado"


class LancamentoFinanceiro(models.Model):
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="lancamentos_criados", verbose_name="criado por")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="lancamentos", verbose_name="cliente")
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="lancamentos", verbose_name="processo")
    descricao = models.TextField("descrição")
    tipo = models.CharField("tipo", max_length=10, choices=TipoLancamento.choices)
    valor = models.DecimalField("valor (R$)", max_digits=12, decimal_places=2)
    vencimento = models.DateField("vencimento")
    situacao = models.CharField("situação", max_length=20, choices=SituacaoLancamento.choices,
                                default=SituacaoLancamento.PENDENTE)
    data_quitacao = models.DateField("data da quitação", null=True, blank=True)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "lancamento_financeiro"
        ordering = ["-vencimento", "-criado_em"]
        constraints = [
            # RN03: valor positivo, receita ou despesa, situações definidas.
            models.CheckConstraint(condition=models.Q(valor__gt=Decimal("0")), name="lancamento_valor_positivo"),
            models.CheckConstraint(condition=models.Q(tipo__in=TipoLancamento.values), name="lancamento_tipo_valido"),
            models.CheckConstraint(condition=models.Q(situacao__in=SituacaoLancamento.values),
                                   name="lancamento_situacao_valida"),
            # RN03: a data da quitação existe somente quando o lançamento está quitado.
            models.CheckConstraint(
                condition=(models.Q(situacao=SituacaoLancamento.QUITADO, data_quitacao__isnull=False)
                           | (~models.Q(situacao=SituacaoLancamento.QUITADO) & models.Q(data_quitacao__isnull=True))),
                name="lancamento_data_quitacao_coerente",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.descricao[:60]}"

    def get_absolute_url(self):
        return reverse("financeiro:detalhe", args=[self.pk])

    @property
    def pendente(self):
        return self.situacao == SituacaoLancamento.PENDENTE


class CobrancaHora(models.Model):
    """Vínculo entre horas registradas e um lançamento (RN10).

    ``liberado_em`` preenchido indica vínculo encerrado (lançamento cancelado);
    o registro é mantido como histórico.
    """

    lancamento = models.ForeignKey(LancamentoFinanceiro, on_delete=models.PROTECT, related_name="cobrancas")
    registro_hora = models.ForeignKey("horas.RegistroHora", on_delete=models.PROTECT, related_name="cobrancas")
    vinculado_em = models.DateTimeField("vinculado em", default=timezone.now)
    liberado_em = models.DateTimeField("liberado em", null=True, blank=True)

    class Meta:
        db_table = "cobranca_hora"
        constraints = [
            # RN10: cada registro de horas admite um único vínculo financeiro ativo.
            models.UniqueConstraint(fields=["registro_hora"], condition=models.Q(liberado_em__isnull=True),
                                    name="cobranca_hora_um_vinculo_ativo"),
        ]

    @property
    def ativa(self):
        return self.liberado_em is None
