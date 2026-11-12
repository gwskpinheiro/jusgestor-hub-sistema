"""Utilitários compartilhados pelas views."""
from django.core.paginator import Paginator

POR_PAGINA = 25


def paginar(request, queryset, por_pagina=POR_PAGINA):
    return Paginator(queryset, por_pagina).get_page(request.GET.get("pagina"))


def incluir_atual(queryset, modelo, pk):
    """Inclui no queryset de um campo de escolha o valor já gravado no registro,
    para que a edição não seja bloqueada quando esse valor deixou de estar
    disponível (ex.: processo arquivado depois do lançamento)."""
    if pk is None:
        return queryset
    return (queryset | modelo.objects.filter(pk=pk)).distinct()
