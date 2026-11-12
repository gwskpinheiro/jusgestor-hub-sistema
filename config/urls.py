from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("conta/", include("apps.usuarios.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("processos/", include("apps.processos.urls")),
    path("agenda/", include("apps.agenda.urls")),
    path("documentos/", include("apps.documentos.urls")),
    path("horas/", include("apps.horas.urls")),
    path("financeiro/", include("apps.financeiro.urls")),
    path("relatorios/", include("apps.relatorios.urls")),
    path("usuarios/", include("apps.usuarios.urls_gestao")),
]

handler403 = "apps.core.views.erro_403"
handler404 = "apps.core.views.erro_404"
