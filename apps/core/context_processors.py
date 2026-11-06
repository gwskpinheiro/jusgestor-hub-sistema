from django.urls import reverse

from .menu import itens_para


def menu(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    itens = []
    for item in itens_para(usuario):
        href = reverse(item.url) if item.url else None
        itens.append(
            {
                "rotulo": item.rotulo,
                "icone": item.icone,
                "href": href,
                "ativo": href is not None and request.path == href,
            }
        )
    return {"menu_itens": itens}
