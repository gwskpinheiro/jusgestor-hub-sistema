"""Gerenciar processos (RF02; RN01, RN07, RN08)."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.acesso import (
    compromissos_visiveis,
    documentos_visiveis,
    e_adm,
    pode_editar_processo,
    processos_visiveis,
)
from apps.core.permissoes import perfil_requerido
from apps.core.utils import paginar
from apps.usuarios.models import Perfil

from .forms import ProcessoForm
from .models import SituacaoProcesso


def lista(request):
    arquivados = request.GET.get("arquivados") == "1"
    situacao = request.GET.get("situacao", "")
    busca = request.GET.get("q", "").strip()
    qs = processos_visiveis(request.user).filter(arquivado=arquivados).select_related("cliente", "responsavel")
    if situacao in SituacaoProcesso.values:
        qs = qs.filter(situacao=situacao)
    if busca:
        qs = qs.filter(Q(numero__icontains=busca) | Q(titulo__icontains=busca) | Q(cliente__nome__icontains=busca))
    return render(request, "processos/lista.html", {
        "pagina": paginar(request, qs), "arquivados": arquivados, "busca": busca,
        "situacao": situacao, "situacoes": SituacaoProcesso.choices,
        "pode_cadastrar": request.user.perfil in (Perfil.ADM, Perfil.ADV),
    })


def _salvar(request, form, mensagem):
    try:
        with transaction.atomic():
            processo = form.save(commit=False)
            if not e_adm(request.user) and not processo.pk:
                processo.responsavel = request.user
            processo.save()
    except IntegrityError:
        # Concorrência: outro cadastro gravou o mesmo número entre a validação e a gravação.
        form.add_error("numero", "Já existe um processo com este número no escritório.")
        return None
    messages.success(request, mensagem)
    return processo


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def novo(request):
    form = ProcessoForm(request.POST or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        processo = _salvar(request, form, "Processo cadastrado.")
        if processo:
            return redirect(processo)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Novo processo", "voltar": "processos:lista",
    })


def detalhe(request, pk):
    usuario = request.user
    processo = get_object_or_404(
        processos_visiveis(usuario).select_related("cliente", "responsavel"), pk=pk
    )
    contexto = {
        "processo": processo,
        "pode_editar": pode_editar_processo(usuario, processo),
        "consulta_basica": usuario.perfil == Perfil.AST,
        "documentos": documentos_visiveis(usuario).filter(processo=processo).order_by("-criado_em"),
        "compromissos": compromissos_visiveis(usuario).filter(processo=processo)
        .select_related("responsavel").order_by("-inicio")[:10],
    }
    return render(request, "processos/detalhe.html", contexto)


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def editar(request, pk):
    processo = get_object_or_404(processos_visiveis(request.user), pk=pk)
    if not pode_editar_processo(request.user, processo):
        if processo.arquivado:
            messages.error(request, "Processo arquivado não pode ser alterado.")
            return redirect(processo)
        raise Http404
    form = ProcessoForm(request.POST or None, instance=processo, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        if _salvar(request, form, "Processo atualizado."):
            return redirect(processo)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": f"Editar processo: {processo}", "voltar_objeto": processo,
    })


@require_POST
@perfil_requerido(Perfil.ADM)
def arquivar(request, pk):
    """RN08: arquiva ou reativa; documentos, horas e lançamentos continuam vinculados."""
    processo = get_object_or_404(processos_visiveis(request.user), pk=pk)
    processo.arquivado = request.POST.get("acao") != "desarquivar"
    processo.save(update_fields=["arquivado"])
    messages.success(request, "Processo arquivado." if processo.arquivado else "Processo reativado.")
    return redirect(processo)
