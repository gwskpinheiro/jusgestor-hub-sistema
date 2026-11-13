"""Backends de armazenamento dos documentos (configurados em config/armazenamento.py)."""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ArmazenamentoLocal(FileSystemStorage):
    """Arquivos em DOCUMENTOS_ROOT, fora das pastas públicas.

    A pasta é lida de settings a cada uso (e não guardada em cache), para
    acompanhar mudanças de DOCUMENTOS_ROOT (por exemplo, pastas temporárias
    nos testes). Não há URL pública: url() falha de propósito, e os arquivos
    só saem pelas views que verificam a permissão.
    """

    @property
    def base_location(self):
        return os.fspath(settings.DOCUMENTOS_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError("Documentos privados não têm URL pública; use as views de download.")
