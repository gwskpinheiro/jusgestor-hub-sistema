"""Configurações de produção (Render) lidas do ambiente.

Valores fictícios; nenhuma conexão é aberta.
"""
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config import ambiente

RENDER = {"RENDER": "true", "RENDER_EXTERNAL_HOSTNAME": "exemplo-ficticio.onrender.com"}


class DebugTests(SimpleTestCase):
    def test_sem_variavel_o_padrao_e_producao(self):
        self.assertFalse(ambiente.booleano({}, "DJANGO_DEBUG"))

    def test_valores_aceitos(self):
        self.assertTrue(ambiente.booleano({"X": "1"}, "X"))
        self.assertFalse(ambiente.booleano({"X": "0"}, "X"))

    def test_valor_invalido(self):
        with self.assertRaises(ImproperlyConfigured):
            ambiente.booleano({"X": "talvez"}, "X")


class HostsECsrfTests(SimpleTestCase):
    def test_padrao_de_desenvolvimento(self):
        self.assertEqual(ambiente.hosts_permitidos({}), ["localhost", "127.0.0.1"])
        self.assertEqual(ambiente.origens_csrf({}), [])

    def test_hostname_do_render_e_incluido_automaticamente(self):
        amb = {**RENDER, "DJANGO_ALLOWED_HOSTS": "jusgestor.exemplo.test"}
        self.assertEqual(ambiente.hosts_permitidos(amb), ["jusgestor.exemplo.test", "exemplo-ficticio.onrender.com"])
        self.assertEqual(ambiente.origens_csrf(amb), ["https://exemplo-ficticio.onrender.com"])

    def test_sem_duplicar(self):
        amb = {**RENDER, "DJANGO_ALLOWED_HOSTS": "exemplo-ficticio.onrender.com",
               "DJANGO_CSRF_TRUSTED_ORIGINS": "https://exemplo-ficticio.onrender.com"}
        self.assertEqual(ambiente.hosts_permitidos(amb), ["exemplo-ficticio.onrender.com"])
        self.assertEqual(ambiente.origens_csrf(amb), ["https://exemplo-ficticio.onrender.com"])

    def test_origem_csrf_exige_esquema(self):
        with self.assertRaises(ImproperlyConfigured):
            ambiente.origens_csrf({"DJANGO_CSRF_TRUSTED_ORIGINS": "exemplo.onrender.com"})


class HttpsTests(SimpleTestCase):
    def test_desligado_por_padrao(self):
        self.assertEqual(ambiente.config_https({}), {})

    def test_ligado(self):
        cfg = ambiente.config_https({"DJANGO_HTTPS": "1"})
        self.assertEqual(cfg["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertTrue(cfg["SECURE_SSL_REDIRECT"])
        self.assertTrue(cfg["SESSION_COOKIE_SECURE"])
        self.assertTrue(cfg["CSRF_COOKIE_SECURE"])
        self.assertEqual(cfg["SECURE_HSTS_SECONDS"], 3600)
        self.assertFalse(cfg["SECURE_HSTS_INCLUDE_SUBDOMAINS"])

    def test_hsts_configuravel(self):
        cfg = ambiente.config_https({"DJANGO_HTTPS": "1", "DJANGO_HSTS_SECONDS": "86400"})
        self.assertEqual(cfg["SECURE_HSTS_SECONDS"], 86400)


class ValidacaoProducaoTests(SimpleTestCase):
    def test_fora_do_render_nao_exige_nada(self):
        ambiente.validar_producao({}, debug=True, https=False, alvo_banco="local", alvo_documentos="local")

    def test_render_com_configuracao_correta(self):
        ambiente.validar_producao(RENDER, debug=False, https=True, alvo_banco="supabase", alvo_documentos="supabase")

    def test_render_recusa_configuracao_insegura(self):
        correto = {"debug": False, "https": True, "alvo_banco": "supabase", "alvo_documentos": "supabase"}
        casos = [
            {**correto, "debug": True},
            {**correto, "https": False},
            {**correto, "alvo_banco": "local"},
            # O disco do Render é temporário: documentos locais seriam perdidos.
            {**correto, "alvo_documentos": "local"},
        ]
        for caso in casos:
            with self.subTest(**caso), self.assertRaises(ImproperlyConfigured):
                ambiente.validar_producao(RENDER, **caso)

    def test_mensagem_explica_o_armazenamento_temporario(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DOCUMENTOS_ARMAZENAMENTO deve ser supabase"):
            ambiente.validar_producao(RENDER, debug=False, https=True, alvo_banco="supabase", alvo_documentos="local")
