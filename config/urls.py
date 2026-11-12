from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("conta/", include("apps.usuarios.urls")),
    path("clientes/", include("apps.clientes.urls")),
]

handler403 = "apps.core.views.erro_403"
handler404 = "apps.core.views.erro_404"
