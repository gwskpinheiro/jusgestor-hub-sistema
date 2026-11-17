"""Ícones SVG simples, desenhados para o layout (sem bibliotecas externas)."""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_ICONES = {
    "painel": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
              '<rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "processos": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "clientes": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/>'
                '<circle cx="17" cy="9" r="2.5"/><path d="M17 14c2.7 0 4.5 2 4.5 5"/>',
    "agenda": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "financeiro": '<rect x="2.5" y="6" width="19" height="13" rx="2"/><path d="M2.5 10h19"/><circle cx="16.5" cy="14.5" r="1.3"/>',
    "documentos": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h7M9 17h7"/>',
    "horas": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "relatorios": '<path d="M4 20h16"/><rect x="6" y="11" width="3" height="7"/><rect x="11" y="6" width="3" height="12"/>'
                  '<rect x="16" y="13" width="3" height="5"/>',
    "usuarios": '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20c0-3.6 2.9-6 6.5-6 1.5 0 2.9.4 4 1.2"/>'
                '<circle cx="18" cy="17" r="2.2"/><path d="M18 13.5v1.3M18 19.2v1.3M14.5 17h1.3M20.2 17h1.3"/>',
    "sair": '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H4"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "marca": '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0zM8 21h8"/>',
    # Tipos de evento da agenda (a cor nunca é o único indicador: há ícone e rótulo).
    "compromisso": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'
                   '<circle cx="12" cy="15.5" r="2"/>',
    "tarefa": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "prazo": '<path d="M7 3h10M7 21h10M8 3v3a4 4 0 0 0 1.6 3.2L12 11l2.4-1.8A4 4 0 0 0 16 6V3'
             'M8 21v-3a4 4 0 0 1 1.6-3.2L12 13l2.4 1.8A4 4 0 0 1 16 18v3"/>',
    # Tema e navegação.
    "lua": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "sol": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
}


@register.simple_tag
def icone(nome, classe="icone"):
    caminho = _ICONES.get(nome, "")
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>',
        classe,
        mark_safe(caminho),
    )
