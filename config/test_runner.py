from django.conf import settings
from django.test.runner import DiscoverRunner

from config.banco import verificar_banco_de_teste


class RunnerBancoIsolado(DiscoverRunner):
    """Executor de testes que recusa qualquer banco que não seja o PostgreSQL local.

    A verificação ocorre antes de qualquer conexão, para que o Django nunca
    tente criar um banco de teste no Supabase.
    """

    def run_tests(self, *args, **kwargs):
        verificar_banco_de_teste(settings.BANCO_ALVO, settings.DATABASES)
        return super().run_tests(*args, **kwargs)
