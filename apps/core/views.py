from django.contrib.auth.decorators import login_not_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from apps.agenda.models import pendencias_destacadas
from apps.core.acesso import compromissos_visiveis, e_adm, processos_visiveis, registros_hora_visiveis
from apps.usuarios.models import Perfil


def painel(request):
    """Painel geral (Figura 4). Cada cartão usa apenas dados autorizados ao perfil."""
    usuario = request.user
    agora = timezone.now()
    hoje = timezone.localdate()
    compromissos = compromissos_visiveis(usuario)
    processos = processos_visiveis(usuario)

    # RF04: destaques de vencimento recalculados ao abrir o painel.
    destacados = list(pendencias_destacadas(compromissos, agora).select_related("processo").order_by("inicio")[:10])
    for item in destacados:
        item.destaque_atual = item.destaque(agora)

    contexto = {
        "total_processos": processos.filter(arquivado=False).count(),
        "compromissos_hoje": compromissos.filter(inicio__date=hoje).exclude(situacao="cancelado").count(),
        "ultimos_processos": processos.filter(arquivado=False).select_related("cliente").order_by("-criado_em")[:5],
        "destacados": destacados,
        "atualizado_em": timezone.localtime(agora),
    }
    if usuario.perfil in (Perfil.ADM, Perfil.ADV):
        # ADM: horas da equipe no mês; ADV: apenas as próprias (RN05).
        minutos = (registros_hora_visiveis(usuario)
                   .filter(data_atividade__year=hoje.year, data_atividade__month=hoje.month)
                   .aggregate(t=Sum("minutos"))["t"] or 0)
        contexto["minutos_mes"] = minutos
        contexto["mostra_horas"] = True
        contexto["rotulo_horas"] = "Horas da equipe no mês" if e_adm(usuario) else "Minhas horas no mês"
    if e_adm(usuario):
        # RN03: o financeiro é exclusivo de ADM.
        from apps.financeiro.views import totais
        from apps.financeiro.models import LancamentoFinanceiro

        contexto["saldo"] = totais(LancamentoFinanceiro.objects.all())["saldo"]
        contexto["mostra_saldo"] = True
    return render(request, "core/painel.html", contexto)


@login_not_required
def erro_403(request, exception=None):
    return render(request, "403.html", status=403)


@login_not_required
def erro_404(request, exception=None):
    return render(request, "404.html", status=404)
