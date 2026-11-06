from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """Obriga a troca da senha temporária antes de usar o sistema (RF01).

    Enquanto ``trocar_senha`` estiver marcado, qualquer página redireciona para
    a tela de troca de senha; apenas ela, o logout e os arquivos estáticos
    permanecem acessíveis.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated and usuario.trocar_senha:
            permitidos = {reverse("usuarios:trocar_senha"), reverse("usuarios:logout")}
            caminho = request.path_info
            if caminho not in permitidos and not caminho.startswith("/" + settings.STATIC_URL.lstrip("/")):
                return redirect("usuarios:trocar_senha")
        return self.get_response(request)
