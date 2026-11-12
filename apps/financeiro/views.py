"""Controlar financeiro (RF05; RN03, RN07, RN10) — exclusivo do ADM."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.core.permissoes import perfil_requerido
from apps.core.utils import paginar
from apps.processos.models import Processo
from apps.usuarios.models import Perfil

from . import servicos
from .forms import CobrancaHorasForm, EscolhaProcessoForm, LancamentoForm, QuitacaoForm
from .models import LancamentoFinanceiro, SituacaoLancamento, TipoLancamento

somente_adm = perfil_requerido(Perfil.ADM)


def totais(qs):
    """Receitas e despesas quitadas, saldo e valores pendentes."""
    def soma(**filtro):
        return qs.filter(**filtro).aggregate(t=Sum("valor"))["t"] or 0

    receitas = soma(tipo=TipoLancamento.RECEITA, situacao=SituacaoLancamento.QUITADO)
    despesas = soma(tipo=TipoLancamento.DESPESA, situacao=SituacaoLancamento.QUITADO)
    return {
        "receitas": receitas, "despesas": despesas, "saldo": receitas - despesas,
        "a_receber": soma(tipo=TipoLancamento.RECEITA, situacao=SituacaoLancamento.PENDENTE),
        "a_pagar": soma(tipo=TipoLancamento.DESPESA, situacao=SituacaoLancamento.PENDENTE),
    }


@somente_adm
def lista(request):
    qs = LancamentoFinanceiro.objects.select_related("cliente", "processo")
    tipo, situacao = request.GET.get("tipo", ""), request.GET.get("situacao", "")
    busca = request.GET.get("q", "").strip()
    if tipo in TipoLancamento.values:
        qs = qs.filter(tipo=tipo)
    if situacao in SituacaoLancamento.values:
        qs = qs.filter(situacao=situacao)
    de, ate = parse_date(request.GET.get("de", "") or ""), parse_date(request.GET.get("ate", "") or "")
    if de:
        qs = qs.filter(vencimento__gte=de)
    if ate:
        qs = qs.filter(vencimento__lte=ate)
    if busca:
        qs = qs.filter(Q(descricao__icontains=busca) | Q(cliente__nome__icontains=busca)
                       | Q(processo__titulo__icontains=busca))
    return render(request, "financeiro/lista.html", {
        "pagina": paginar(request, qs), "totais": totais(qs),
        "tipos": TipoLancamento.choices, "situacoes": SituacaoLancamento.choices,
        "filtros": {"tipo": tipo, "situacao": situacao, "q": busca,
                    "de": request.GET.get("de", ""), "ate": request.GET.get("ate", "")},
    })


@somente_adm
def novo(request):
    form = LancamentoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lancamento = form.save(commit=False)
        lancamento.criado_por = request.user
        lancamento.save()
        messages.success(request, "Lançamento registrado.")
        return redirect(lancamento)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Novo lançamento", "voltar": "financeiro:lista",
    })


@somente_adm
def detalhe(request, pk):
    lancamento = get_object_or_404(
        LancamentoFinanceiro.objects.select_related("cliente", "processo", "criado_por"), pk=pk
    )
    return render(request, "financeiro/detalhe.html", {
        "lancamento": lancamento,
        "cobrancas": lancamento.cobrancas.select_related("registro_hora__usuario").order_by("registro_hora__data_atividade"),
        "form_quitacao": QuitacaoForm(),
    })


@somente_adm
def editar(request, pk):
    lancamento = get_object_or_404(LancamentoFinanceiro, pk=pk)
    if not lancamento.pendente:
        messages.error(request, "Somente lançamentos pendentes podem ser alterados.")
        return redirect(lancamento)
    form = LancamentoForm(request.POST or None, instance=lancamento)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lançamento atualizado.")
        return redirect(lancamento)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Editar lançamento", "voltar_objeto": lancamento,
    })


@require_POST
@somente_adm
def quitar(request, pk):
    lancamento = get_object_or_404(LancamentoFinanceiro, pk=pk)
    form = QuitacaoForm(request.POST)
    if form.is_valid():
        try:
            servicos.quitar(lancamento, form.cleaned_data["data_quitacao"])
            messages.success(request, "Lançamento quitado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        messages.error(request, "Informe uma data de quitação válida.")
    return redirect(lancamento)


@require_POST
@somente_adm
def cancelar(request, pk):
    lancamento = get_object_or_404(LancamentoFinanceiro, pk=pk)
    try:
        servicos.cancelar(lancamento)
        messages.success(request, "Lançamento cancelado. As horas vinculadas foram liberadas e o histórico foi mantido.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect(lancamento)


@somente_adm
def cobrar_horas(request):
    """Conversão confirmada de horas em cobrança (RF05, RN10)."""
    escolha = EscolhaProcessoForm(request.GET or None)
    processo = None
    if escolha.is_valid():
        processo = escolha.cleaned_data["processo"]
    elif request.method == "POST":
        processo = get_object_or_404(Processo, pk=request.POST.get("processo"))
    form = None
    if processo:
        disponiveis = servicos.horas_disponiveis(processo)
        form = CobrancaHorasForm(request.POST or None, disponiveis=disponiveis, processo=processo)
        if request.method == "POST" and form.is_valid():
            try:
                lancamento = servicos.converter_horas(
                    administrador=request.user, processo=processo,
                    registros=form.cleaned_data["registros"], valor=form.cleaned_data["valor"],
                    descricao=form.cleaned_data["descricao"], vencimento=form.cleaned_data["vencimento"],
                )
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Cobrança gerada a partir das horas selecionadas.")
                return redirect(lancamento)
        total = disponiveis.aggregate(t=Sum("minutos"))["t"] or 0
    return render(request, "financeiro/cobrar_horas.html", {
        "escolha": escolha, "processo": processo, "form": form,
        "total_disponivel": total if processo else 0,
    })
