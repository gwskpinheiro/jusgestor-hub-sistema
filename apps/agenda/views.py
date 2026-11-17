"""Controlar agenda (RF04; RN02, RN07)."""
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.core.acesso import compromissos_visiveis, processos_visiveis
from apps.core.utils import paginar

from . import calendario as cal
from .forms import CompromissoForm
from .models import SituacaoCompromisso, TipoCompromisso, pendencias_destacadas

# Parâmetros da listagem: endereços antigos de /agenda/?situacao=... continuam válidos.
PARAMETROS_DA_LISTA = {"situacao", "tipo", "de", "ate", "meus", "pagina"}


def _limite(data, fim_do_dia=False):
    return timezone.make_aware(datetime.combine(data, time.max if fim_do_dia else time.min))


def calendario(request):
    """Visualização principal da agenda: calendário por dia, semana, mês ou ano (RF04)."""
    if "visao" not in request.GET and PARAMETROS_DA_LISTA & set(request.GET):
        return redirect(f"{reverse('agenda:lista')}?{request.GET.urlencode()}")
    agora = timezone.now()
    hoje = timezone.localdate()
    visao = cal.ler_visao(request.GET.get("visao"))
    referencia = cal.ler_data(request.GET.get("data"), hoje)
    periodo = cal.periodo(visao, referencia)
    qs = compromissos_visiveis(request.user)  # RN07: só o que o usuário pode consultar
    contexto = {"visao": visao, "periodo": periodo, "hoje": hoje, "visoes": _links_visoes(referencia)}
    if visao == "mes":
        inicio, fim = cal.intervalo_grade_mes(referencia)
        itens = cal.compromissos_no_intervalo(qs, inicio, fim, agora)
        contexto["semanas"] = cal.grade_mes(referencia, cal.por_dia(itens), hoje)
        contexto["dias_da_semana"] = cal.DIAS_DA_SEMANA
        contexto["total"] = sum(1 for i in itens if i.inicio_local.month == referencia.month)
    elif visao == "ano":
        contexto["meses"] = cal.resumo_ano(qs, referencia.year, hoje)
        contexto["dias_da_semana"] = cal.DIAS_DA_SEMANA
        contexto["total"] = sum(m["total"] for m in contexto["meses"])
    else:
        itens = cal.compromissos_no_intervalo(qs, periodo.inicio, periodo.fim, agora)
        dias = [periodo.inicio + timedelta(days=n) for n in range((periodo.fim - periodo.inicio).days)]
        por_dia = cal.por_dia(itens)
        contexto["dias"] = [{"data": d, "hoje": d == hoje, "rotulo": cal.DIAS_DA_SEMANA[d.weekday()],
                             "eventos": por_dia.get(d, [])} for d in dias]
        contexto["linhas"] = cal.grade_horas(dias, por_dia)
        contexto["total"] = len(itens)
    return render(request, "agenda/calendario.html", contexto)


def _links_visoes(referencia):
    base = reverse("agenda:calendario")
    return [{"visao": v, "rotulo": rotulo, "url": f"{base}?{urlencode({'visao': v, 'data': referencia.isoformat()})}"}
            for v, rotulo in (("dia", "Dia"), ("semana", "Semana"), ("mes", "Mês"), ("ano", "Ano"))]


def lista(request):
    usuario = request.user
    situacao = request.GET.get("situacao", SituacaoCompromisso.PENDENTE)
    tipo = request.GET.get("tipo", "")
    de, ate = parse_date(request.GET.get("de", "") or ""), parse_date(request.GET.get("ate", "") or "")
    qs = compromissos_visiveis(usuario).select_related("responsavel", "processo")
    if situacao in SituacaoCompromisso.values:
        qs = qs.filter(situacao=situacao)
    if tipo in TipoCompromisso.values:
        qs = qs.filter(tipo=tipo)
    if request.GET.get("meus") == "1":
        qs = qs.filter(responsavel=usuario)
    if de:
        qs = qs.filter(inicio__gte=_limite(de))
    if ate:
        qs = qs.filter(inicio__lte=_limite(ate, fim_do_dia=True))
    agora = timezone.now()
    pagina = paginar(request, qs.order_by("inicio"))
    # Destaques recalculados a cada abertura da agenda (RF04).
    for compromisso in pagina:
        compromisso.destaque_atual = compromisso.destaque(agora)
    return render(request, "agenda/lista.html", {
        "pagina": pagina, "situacao": situacao, "tipo": tipo,
        "de": request.GET.get("de", ""), "ate": request.GET.get("ate", ""), "meus": request.GET.get("meus") == "1",
        "situacoes": SituacaoCompromisso.choices, "tipos": TipoCompromisso.choices,
        "total_destacados": pendencias_destacadas(compromissos_visiveis(usuario), agora).count(),
        "visoes": _links_visoes(timezone.localdate()),
    })


def novo(request):
    form = CompromissoForm(request.POST or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        compromisso = form.save()
        messages.success(request, "Compromisso registrado.")
        return redirect(compromisso)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Novo compromisso", "voltar": "agenda:calendario",
    })


def detalhe(request, pk):
    usuario = request.user
    compromisso = get_object_or_404(
        compromissos_visiveis(usuario).select_related("responsavel", "processo"), pk=pk
    )
    return render(request, "agenda/detalhe.html", {
        "compromisso": compromisso,
        "destaque": compromisso.destaque(),
        "participantes": compromisso.participantes.select_related("usuario"),
        # Participar não concede acesso ao processo: o link só aparece para quem o acessa.
        "ve_processo": compromisso.processo_id is not None
        and processos_visiveis(usuario).filter(pk=compromisso.processo_id).exists(),
    })


def editar(request, pk):
    compromisso = get_object_or_404(compromissos_visiveis(request.user), pk=pk)
    form = CompromissoForm(request.POST or None, instance=compromisso, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compromisso atualizado.")
        return redirect(compromisso)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": f"Editar compromisso: {compromisso}", "voltar_objeto": compromisso,
    })


@require_POST
def alterar_situacao(request, pk):
    """Concluir, cancelar ou reabrir — sem exclusão do registro."""
    compromisso = get_object_or_404(compromissos_visiveis(request.user), pk=pk)
    nova = request.POST.get("situacao")
    if nova in SituacaoCompromisso.values:
        compromisso.situacao = nova
        compromisso.save(update_fields=["situacao"])
        messages.success(request, f"Situação alterada para {compromisso.get_situacao_display().lower()}.")
    return redirect(request.POST.get("voltar") == "lista" and "agenda:lista" or compromisso)
