"""Gerenciar clientes (RF03; RN01, RN04, RN07, RN08)."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.acesso import clientes_visiveis, e_adm, processos_visiveis
from apps.core.permissoes import perfil_requerido
from apps.core.utils import paginar
from apps.usuarios.models import Perfil

from .forms import ClienteForm
from .models import AcessoCliente, so_digitos


def lista(request):
    arquivados = request.GET.get("arquivados") == "1"
    busca = request.GET.get("q", "").strip()
    qs = clientes_visiveis(request.user).filter(arquivado=arquivados)
    if busca:
        filtro = Q(nome__icontains=busca) | Q(email__icontains=busca)
        if so_digitos(busca):
            filtro |= Q(cpf_cnpj__contains=so_digitos(busca))
        qs = qs.filter(filtro)
    return render(request, "clientes/lista.html", {
        "pagina": paginar(request, qs), "arquivados": arquivados, "busca": busca,
    })


def novo(request):
    form = ClienteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            cliente = form.save()
            # Quem cadastra recebe acesso ao cadastro (ADM já acessa tudo).
            if not e_adm(request.user):
                AcessoCliente.objects.create(usuario=request.user, cliente=cliente)
        messages.success(request, "Cliente cadastrado.")
        return redirect(cliente)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Novo cliente", "voltar": "clientes:lista",
    })


def detalhe(request, pk):
    cliente = get_object_or_404(clientes_visiveis(request.user), pk=pk)
    # Somente os vínculos permitidos ao usuário (RF03).
    processos = processos_visiveis(request.user).filter(cliente=cliente).select_related("responsavel")
    return render(request, "clientes/detalhe.html", {
        "cliente": cliente, "processos": processos,
    })


def editar(request, pk):
    cliente = get_object_or_404(clientes_visiveis(request.user), pk=pk)
    if cliente.arquivado:
        messages.error(request, "Cliente arquivado não pode ser alterado.")
        return redirect(cliente)
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cliente atualizado.")
        return redirect(cliente)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": f"Editar cliente: {cliente.nome}", "voltar_objeto": cliente,
    })


@require_POST
@perfil_requerido(Perfil.ADM)
def arquivar(request, pk):
    """RN08: arquiva ou reativa, preservando vínculos e histórico."""
    cliente = get_object_or_404(clientes_visiveis(request.user), pk=pk)
    cliente.arquivado = request.POST.get("acao") != "desarquivar"
    cliente.save(update_fields=["arquivado"])
    messages.success(request, "Cliente arquivado." if cliente.arquivado else "Cliente reativado.")
    return redirect(cliente)
