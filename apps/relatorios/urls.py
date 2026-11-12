from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.indice, name="indice"),
    path("<slug:tipo>/", views.relatorio, name="relatorio"),
]
