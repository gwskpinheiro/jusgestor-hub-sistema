import mimetypes

from django.apps import AppConfig


class DocumentosConfig(AppConfig):
    name = "apps.documentos"
    label = "documentos"
    verbose_name = "Documentos"

    def ready(self):
        # Garante o tipo MIME dos formatos aceitos (RN04) mesmo em sistemas sem
        # /etc/mime.types (ex.: imagem python:slim, que não conhece .docx). O
        # armazenamento S3 usa esse tipo ao gravar, e o bucket aceita apenas
        # os tipos de documento.
        from .models import TIPOS_PERMITIDOS

        for extensao, tipo in TIPOS_PERMITIDOS.items():
            mimetypes.add_type(tipo, f".{extensao}")
