"""Emitir relatórios (RF08; RN09) seguindo o fluxo da Figura 2:

menu Relatórios -> tipo -> filtros -> solicitar geração -> existem dados?
    sim: gerar e exibir (HTML, CSV, impressão pelo navegador)
    não: exibir "Nenhum dado encontrado"
"""
import csv
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.permissoes import perfil_requerido
from apps.usuarios.models import Perfil

from . import forms, geradores


@dataclass(frozen=True)
class TipoRelatorio:
    chave: str
    titulo: str
    descricao: str
    perfis: tuple
    filtro: type
    gerador: object


TIPOS = {
    t.chave: t
    for t in (
        TipoRelatorio("processos", "Processos", "Processos autorizados por situação, responsável e cadastro.",
                      (Perfil.ADM, Perfil.ADV), forms.FiltroProcessos, geradores.processos),
        TipoRelatorio("agenda", "Agenda", "Compromissos, tarefas e prazos com destaques de vencimento.",
                      (Perfil.ADM, Perfil.ADV), forms.FiltroAgenda, geradores.agenda),
        TipoRelatorio("horas", "Horas trabalhadas", "Horas por período e processo, com indicação de cobrança.",
                      (Perfil.ADM, Perfil.ADV), forms.FiltroHoras, geradores.horas),
        # RN09: o financeiro permanece exclusivo de ADM.
        TipoRelatorio("financeiro", "Financeiro", "Receitas e despesas por vencimento e situação.",
                      (Perfil.ADM,), forms.FiltroFinanceiro, geradores.financeiro),
    )
}

PREFIXOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _celula_csv(valor):
    """Evita injeção de fórmulas ao abrir o CSV em planilhas."""
    valor = str(valor)
    return "'" + valor if valor.startswith(PREFIXOS_FORMULA) else valor


def _csv(tipo, resultado):
    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    nome = f"relatorio-{tipo.chave}-{timezone.localdate():%Y%m%d}.csv"
    resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    resposta["Cache-Control"] = "private, no-store"
    resposta.write("﻿")  # BOM: acentos corretos ao abrir no Excel.
    escritor = csv.writer(resposta, delimiter=";")
    escritor.writerow(resultado.colunas)
    for linha in resultado.linhas:
        escritor.writerow([_celula_csv(celula.csv) for celula in linha])
    return resposta


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def indice(request):
    disponiveis = [t for t in TIPOS.values() if request.user.perfil in t.perfis]
    return render(request, "relatorios/indice.html", {"tipos": disponiveis})


@perfil_requerido(Perfil.ADM, Perfil.ADV)
def relatorio(request, tipo):
    definicao = TIPOS.get(tipo)
    if definicao is None:
        raise Http404
    if request.user.perfil not in definicao.perfis:
        raise PermissionDenied
    solicitado = request.GET.get("gerar") == "1"
    form = definicao.filtro(request.GET if solicitado else None, usuario=request.user)
    resultado = None
    if solicitado and form.is_valid():
        resultado = definicao.gerador(request.user, form.cleaned_data)
        if request.GET.get("formato") == "csv" and not resultado.vazio:
            return _csv(definicao, resultado)
    return render(request, "relatorios/relatorio.html", {
        "tipo": definicao, "form": form, "solicitado": solicitado, "resultado": resultado,
        "linhas_html": resultado.linhas[: geradores.LIMITE_HTML] if resultado else [],
        "limite": geradores.LIMITE_HTML, "emitido_em": timezone.localtime(),
    })
