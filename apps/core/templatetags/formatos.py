"""Filtros de exibição: moeda, duração e documentos de identificação."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def moeda(valor):
    """1234.5 -> 'R$ 1.234,50'."""
    if valor is None or valor == "":
        return "—"
    try:
        numero = Decimal(valor).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return valor
    sinal = "-" if numero < 0 else ""
    inteiro, centavos = f"{abs(numero):.2f}".split(".")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"{sinal}R$ {'.'.join(grupos)},{centavos}"


@register.filter
def duracao(minutos):
    """150 -> '2h30'."""
    if minutos in (None, ""):
        return "—"
    minutos = int(minutos)
    return f"{minutos // 60}h{minutos % 60:02d}"


@register.filter
def cpf_cnpj(valor):
    if not valor:
        return "—"
    if len(valor) == 11:
        return f"{valor[:3]}.{valor[3:6]}.{valor[6:9]}-{valor[9:]}"
    if len(valor) == 14:
        return f"{valor[:2]}.{valor[2:5]}.{valor[5:8]}/{valor[8:12]}-{valor[12:]}"
    return valor


@register.filter
def tamanho_arquivo(bytes_):
    bytes_ = int(bytes_ or 0)
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KiB".replace(".", ",")
    return f"{bytes_ / (1024 * 1024):.1f} MiB".replace(".", ",")
