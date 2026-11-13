"""Gerenciar documentos (RF06; RN04, RN07, RN08)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.acesso import documentos_visiveis
from apps.core.utils import paginar

from .armazenamento import caminho_absoluto, gravar_versao
from .forms import DocumentoEdicaoForm, DocumentoForm, NovaVersaoForm
from .models import TIPOS_PERMITIDOS, VersaoDocumento


def lista(request):
    busca = request.GET.get("q", "").strip()
    qs = documentos_visiveis(request.user).select_related("cliente", "processo").prefetch_related("versoes")
    if busca:
        qs = qs.filter(Q(titulo__icontains=busca) | Q(cliente__nome__icontains=busca)
                       | Q(processo__titulo__icontains=busca) | Q(processo__numero__icontains=busca))
    return render(request, "documentos/lista.html", {"pagina": paginar(request, qs), "busca": busca})


def novo(request):
    # Pré-seleção vinda da página do cliente/processo; a escolha só é aceita
    # se estiver entre os registros autorizados (queryset do formulário).
    inicial = {k: request.GET[k] for k in ("cliente", "processo") if request.GET.get(k, "").isdigit()}
    form = DocumentoForm(request.POST or None, request.FILES or None, usuario=request.user, initial=inicial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            documento = form.save()
            gravar_versao(documento, form.cleaned_data["arquivo"], request.user)
        messages.success(request, "Documento enviado.")
        return redirect(documento)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": "Enviar documento", "voltar": "documentos:lista",
    })


def detalhe(request, pk):
    documento = get_object_or_404(
        documentos_visiveis(request.user).select_related("cliente", "processo"), pk=pk
    )
    return render(request, "documentos/detalhe.html", {
        "documento": documento,
        "versoes": documento.versoes.select_related("autor"),
        "form_versao": NovaVersaoForm(),
    })


def editar(request, pk):
    documento = get_object_or_404(documentos_visiveis(request.user), pk=pk)
    form = DocumentoEdicaoForm(request.POST or None, instance=documento)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Documento atualizado.")
        return redirect(documento)
    return render(request, "core/form_generico.html", {
        "form": form, "titulo": f"Editar documento: {documento}", "voltar_objeto": documento,
    })


@require_POST
def nova_versao(request, pk):
    documento = get_object_or_404(documentos_visiveis(request.user), pk=pk)
    form = NovaVersaoForm(request.POST, request.FILES)
    if form.is_valid():
        versao = gravar_versao(documento, form.cleaned_data["arquivo"], request.user)
        messages.success(request, f"Versão {versao.numero_versao} enviada. As versões anteriores foram mantidas.")
        return redirect(documento)
    return render(request, "documentos/detalhe.html", {
        "documento": documento, "versoes": documento.versoes.select_related("autor"), "form_versao": form,
    }, status=400)


def _versao_autorizada(request, pk):
    """Versão de um documento que o usuário pode consultar; caso contrário, 404 (RN07)."""
    return get_object_or_404(
        VersaoDocumento.objects.select_related("documento"),
        pk=pk, documento__in=documentos_visiveis(request.user),
    )


def _responder_arquivo(versao, anexo):
    try:
        caminho = caminho_absoluto(versao)
        arquivo = open(caminho, "rb")
    except (OSError, ValidationError):
        raise Http404("Arquivo não encontrado.")
    resposta = FileResponse(
        arquivo, as_attachment=anexo, filename=versao.nome_arquivo,
        content_type=TIPOS_PERMITIDOS.get(versao.extensao, "application/octet-stream"),
    )
    # Arquivo privado: sem cache compartilhado e sem adivinhação de tipo pelo navegador.
    resposta["Cache-Control"] = "private, no-store"
    resposta["X-Content-Type-Options"] = "nosniff"
    return resposta


def baixar(request, pk):
    """Download protegido: verifica no servidor a permissão sobre o documento."""
    return _responder_arquivo(_versao_autorizada(request, pk), anexo=True)


def visualizar(request, pk):
    """Exibe PDF, PNG ou JPEG no navegador (nova aba), com as mesmas verificações
    do download. DOCX e outros tipos não são exibidos: use "Baixar"."""
    versao = _versao_autorizada(request, pk)
    if not versao.visualizavel:
        raise Http404("Este tipo de arquivo não pode ser visualizado no navegador.")
    return _responder_arquivo(versao, anexo=False)
