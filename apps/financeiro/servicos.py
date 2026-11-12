"""Operações financeiras com regras de negócio (RN03, RN10).

As operações que alteram mais de uma tabela usam transação: ou tudo é
gravado, ou nada é (Metodologia do artigo, uso de transações do PostgreSQL).
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.horas.models import RegistroHora

from .models import CobrancaHora, LancamentoFinanceiro, SituacaoLancamento, TipoLancamento


def _bloquear(lancamento):
    return LancamentoFinanceiro.objects.select_for_update().get(pk=lancamento.pk)


def quitar(lancamento, data_quitacao):
    """Pendente -> quitado, registrando a data da quitação (RN03)."""
    if data_quitacao is None:
        raise ValidationError("Informe a data da quitação.")
    if data_quitacao > timezone.localdate():
        raise ValidationError("A data da quitação não pode estar no futuro.")
    with transaction.atomic():
        atual = _bloquear(lancamento)
        if atual.situacao != SituacaoLancamento.PENDENTE:
            raise ValidationError("Somente lançamentos pendentes podem ser quitados.")
        atual.situacao = SituacaoLancamento.QUITADO
        atual.data_quitacao = data_quitacao
        atual.save(update_fields=["situacao", "data_quitacao"])
    return atual


def cancelar(lancamento):
    """Pendente -> cancelado. Libera os vínculos com horas, preservando o histórico (RN10)."""
    with transaction.atomic():
        atual = _bloquear(lancamento)
        if atual.situacao != SituacaoLancamento.PENDENTE:
            raise ValidationError("Somente lançamentos pendentes podem ser cancelados.")
        atual.situacao = SituacaoLancamento.CANCELADO
        atual.save(update_fields=["situacao"])
        atual.cobrancas.filter(liberado_em__isnull=True).update(liberado_em=timezone.now())
    return atual


def horas_disponiveis(processo):
    """Registros do processo sem vínculo financeiro ativo."""
    ativa = CobrancaHora.objects.filter(registro_hora=OuterRef("pk"), liberado_em__isnull=True)
    return (RegistroHora.objects.filter(processo=processo).exclude(Exists(ativa))
            .select_related("usuario").order_by("data_atividade"))


def converter_horas(*, administrador, processo, registros, valor, descricao, vencimento):
    """Converte horas de um processo em uma cobrança (receita pendente) — RN10.

    O ADM confirma o valor. Tudo ocorre em uma transação: se algum registro já
    tiver vínculo ativo, nada é gravado.
    """
    ids = sorted({r.pk for r in registros})
    if not ids:
        raise ValidationError("Selecione ao menos um registro de horas.")
    try:
        with transaction.atomic():
            bloqueados = list(RegistroHora.objects.select_for_update().filter(pk__in=ids))
            if len(bloqueados) != len(ids) or any(r.processo_id != processo.pk for r in bloqueados):
                raise ValidationError("Os registros selecionados devem pertencer ao processo informado.")
            if CobrancaHora.objects.filter(registro_hora_id__in=ids, liberado_em__isnull=True).exists():
                raise ValidationError("Algum registro selecionado já está vinculado a uma cobrança ativa.")
            lancamento = LancamentoFinanceiro.objects.create(
                criado_por=administrador,
                cliente=processo.cliente,
                processo=processo,
                descricao=descricao,
                tipo=TipoLancamento.RECEITA,
                valor=valor,
                vencimento=vencimento,
            )
            agora = timezone.now()
            CobrancaHora.objects.bulk_create(
                [CobrancaHora(lancamento=lancamento, registro_hora_id=pk, vinculado_em=agora) for pk in ids]
            )
    except IntegrityError as erro:
        # Índice único parcial: outro usuário vinculou um dos registros ao mesmo tempo.
        raise ValidationError("Algum registro selecionado já está vinculado a uma cobrança ativa.") from erro
    return lancamento
