"""Registrar horas (RF07; RN05, RN07, RN10)."""
from django.contrib import messages
from django.db.models import Exists, OuterRef, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from apps.core.acesso import e_adm, processos_visiveis, registros_hora_visiveis
from apps.core.permissoes import perfil_requerido
from apps.core.utils import paginar
from apps.financeiro.models import CobrancaHora
from apps.usuarios.models import Perfil, Usuario

from .forms import RegistroHoraForm
from .models import RegistroHora


def com_situacao_cobranca(qs):
    ativa = CobrancaHora.objects.filter(registro_hora=OuterRef("pk"), liberado_em__isnull=True)
    return qs.annotate(cobrado=Exists(ativa))


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def lista(request):
    usuario = request.user
    adm = e_adm(usuario)
    # Visão individual por padrão; ADM pode consultar a equipe (RF07).
    visao = request.GET.get("visao", "minhas")
    qs = registros_hora_visiveis(usuario).select_related("usuario", "processo")
    filtro_usuario = request.GET.get("usuario", "")
    if not adm or visao != "equipe":
        visao = "minhas"
        qs = qs.filter(usuario=usuario)
    elif filtro_usuario.isdigit():
        qs = qs.filter(usuario_id=int(filtro_usuario))
    processo = request.GET.get("processo", "")
    if processo.isdigit():
        qs = qs.filter(processo_id=int(processo))
    de, ate = parse_date(request.GET.get("de", "") or ""), parse_date(request.GET.get("ate", "") or "")
    if de:
        qs = qs.filter(data_atividade__gte=de)
    if ate:
        qs = qs.filter(data_atividade__lte=ate)
    qs = com_situacao_cobranca(qs)
    return render(request, "horas/lista.html", {
        "pagina": paginar(request, qs),
        "total_minutos": qs.aggregate(total=Sum("minutos"))["total"] or 0,
        "visao": visao, "adm": adm,
        "usuarios": Usuario.objects.filter(perfil__in=[Perfil.ADM, Perfil.ADV]) if adm else [],
        "processos": processos_visiveis(usuario).order_by("titulo"),
        "filtros": {"usuario": filtro_usuario, "processo": processo,
                    "de": request.GET.get("de", ""), "ate": request.GET.get("ate", "")},
    })


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def novo(request):
    form = RegistroHoraForm(request.POST or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        registro = form.save(commit=False)
        registro.usuario = request.user  # RN05: sempre as próprias horas.
        registro.save()
        messages.success(request, "Horas registradas.")
        return redirect("horas:lista")
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Registrar horas", "voltar": "horas:lista",
    })


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def editar(request, pk):
    # Somente o autor altera o próprio registro; o ADM apenas consulta os da equipe.
    registro = get_object_or_404(RegistroHora.objects.filter(usuario=request.user), pk=pk)
    form = RegistroHoraForm(request.POST or None, instance=registro, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Registro de horas atualizado.")
        return redirect("horas:lista")
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Editar registro de horas", "voltar": "horas:lista",
        "aviso": "Este registro está vinculado a uma cobrança ativa." if form.cobranca else "",
    })
