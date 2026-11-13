"""Gerenciar usuários (RF09; RN06, RN07, RN08) — exclusivo do ADM."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.core.permissoes import perfil_requerido

from . import servicos
from .forms_gestao import AcessosForm, UsuarioForm
from .models import Perfil, Usuario

somente_adm = perfil_requerido(Perfil.ADM)


def _mostrar_senha(request, usuario, senha, motivo):
    """Exibe a senha temporária uma única vez, sem gravá-la em mensagens ou cookies."""
    return render(request, "gestao_usuarios/senha_temporaria.html", {
        "usuario_alvo": usuario, "senha": senha, "motivo": motivo,
    })


@somente_adm
def lista(request):
    situacao = request.GET.get("situacao", "ativos")
    qs = Usuario.objects.all()
    if situacao == "ativos":
        qs = qs.filter(ativo=True)
    elif situacao == "inativos":
        qs = qs.filter(ativo=False)
    return render(request, "gestao_usuarios/lista.html", {"usuarios": qs, "situacao": situacao})


@never_cache
@somente_adm
def novo(request):
    form = UsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario, senha = servicos.criar_usuario(
            nome=form.cleaned_data["nome"], email=form.cleaned_data["email"], perfil=form.cleaned_data["perfil"]
        )
        return _mostrar_senha(request, usuario, senha, "Conta criada.")
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Novo usuário", "voltar": "gestao_usuarios:lista",
        "aviso": "Uma senha temporária será gerada e exibida uma única vez. A troca é exigida no primeiro acesso.",
    })


@somente_adm
def editar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    nome, estava_ativo = usuario.nome, usuario.ativo
    form = UsuarioForm(request.POST or None, instance=usuario)
    if request.method == "POST" and form.is_valid():
        try:
            servicos.salvar_usuario(form.instance)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Usuário atualizado.")
            return redirect("gestao_usuarios:lista")
    contexto = {"form": form, "titulo": f"Editar usuário: {nome}", "voltar": "gestao_usuarios:lista"}
    if estava_ativo:
        # Confirmação no navegador apenas quando a caixa "ativo" for desmarcada.
        contexto["confirmacao"] = {
            "se_desmarcar": "ativo", "titulo": "Desativar usuário", "botao": "Desativar e salvar", "perigo": True,
            "mensagem": f"Desativar a conta de {nome}? O acesso ao sistema será bloqueado; "
                        "o cadastro e o histórico são mantidos e a conta pode ser reativada.",
        }
    return render(request, "core/form_generico.html", contexto)


@never_cache
@require_POST
@somente_adm
def redefinir_senha(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    senha = servicos.redefinir_senha(usuario)
    if usuario.pk == request.user.pk:
        # Mantém a sessão atual; a troca obrigatória será exigida em seguida.
        update_session_auth_hash(request, usuario)
    return _mostrar_senha(request, usuario, senha, "Senha redefinida. As sessões abertas desta conta foram encerradas.")


@somente_adm
def acessos(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.perfil == Perfil.ADM:
        return render(request, "gestao_usuarios/acessos.html", {"usuario_alvo": usuario, "form": None})
    inicial = {
        "clientes": list(usuario.acessos_cliente.values_list("cliente_id", flat=True)),
        "processos": list(usuario.acessos_processo.values_list("processo_id", flat=True)),
    }
    # Todos os campos são opcionais: um POST sem itens marcados revoga todos os acessos,
    # por isso o formulário é vinculado pelo método, e não pelo conteúdo do POST.
    form = AcessosForm(request.POST if request.method == "POST" else None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            servicos.definir_acessos(usuario, form.cleaned_data["clientes"], form.cleaned_data["processos"])
        messages.success(request, "Acessos atualizados.")
        return redirect("gestao_usuarios:lista")
    responsavel = usuario.processos_responsavel.all() if usuario.perfil == Perfil.ADV else []
    return render(request, "gestao_usuarios/acessos.html", {
        "usuario_alvo": usuario, "form": form, "responsavel_por": responsavel,
    })
