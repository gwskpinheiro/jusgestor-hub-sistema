from django.conf import settings
from django.test.runner import DiscoverRunner

from config.armazenamento import verificar_armazenamento_de_teste
from config.banco import verificar_banco_de_teste


class RunnerBancoIsolado(DiscoverRunner):
    """Executor de testes que recusa qualquer banco ou armazenamento de documentos
    que não seja local.

    A verificação ocorre antes de qualquer conexão, para que o Django nunca
    tente criar um banco de teste no Supabase nem gravar arquivos no Supabase
    Storage.
    """

    def run_tests(self, *args, **kwargs):
        verificar_banco_de_teste(settings.BANCO_ALVO, settings.DATABASES)
        verificar_armazenamento_de_teste(settings.DOCUMENTOS_ARMAZENAMENTO, settings.STORAGES)
        return super().run_tests(*args, **kwargs)
