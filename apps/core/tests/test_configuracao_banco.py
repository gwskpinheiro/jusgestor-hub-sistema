"""Seleção do banco por variáveis de ambiente e isolamento dos testes.

Nenhum destes testes conecta ao Supabase: os valores são fictícios e as
funções recebem o ambiente como dicionário.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.banco import (
    configurar_banco,
    e_host_supabase,
    verificar_banco_de_teste,
)

LOCAL = {
    "POSTGRES_DB": "jusgestor",
    "POSTGRES_USER": "jusgestor",
    "POSTGRES_PASSWORD": "valor-ficticio-local",
    "POSTGRES_HOST": "db",
}

SUPABASE = {
    "DB_ALVO": "supabase",
    "SUPABASE_DB_HOST": "aws-0-regiao.pooler.supabase.com",
    "SUPABASE_DB_USER": "postgres.referencia-ficticia",
    "SUPABASE_DB_PASSWORD": "valor-ficticio-remoto",
}


class SelecaoDoBancoTests(SimpleTestCase):
    def test_padrao_e_o_banco_local(self):
        cfg = configurar_banco(LOCAL)
        self.assertEqual(cfg["HOST"], "db")
        self.assertEqual(cfg["TEST"]["NAME"], "test_jusgestor")
        self.assertNotIn("OPTIONS", cfg)

    def test_supabase_usa_session_pooler_porta_5432_com_ssl(self):
        cfg = configurar_banco(SUPABASE)
        self.assertEqual(cfg["HOST"], "aws-0-regiao.pooler.supabase.com")
        self.assertEqual(cfg["PORT"], "5432")
        self.assertEqual(cfg["NAME"], "postgres")
        self.assertEqual(cfg["OPTIONS"]["sslmode"], "require")
        self.assertTrue(cfg["CONN_HEALTH_CHECKS"])

    def test_supabase_com_certificado_verifica_o_servidor(self):
        cfg = configurar_banco({**SUPABASE, "SUPABASE_DB_SSLROOTCERT": "/app/certs/supabase-ca.crt"})
        self.assertEqual(cfg["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(cfg["OPTIONS"]["sslrootcert"], "/app/certs/supabase-ca.crt")

    def test_supabase_recusa_sslmode_sem_criptografia(self):
        for modo in ("disable", "allow", "prefer"):
            with self.subTest(modo=modo), self.assertRaises(ImproperlyConfigured):
                configurar_banco({**SUPABASE, "SUPABASE_DB_SSLMODE": modo})

    def test_verify_full_exige_certificado(self):
        with self.assertRaises(ImproperlyConfigured):
            configurar_banco({**SUPABASE, "SUPABASE_DB_SSLMODE": "verify-full"})

    def test_supabase_exige_credenciais(self):
        for faltando in ("SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"):
            amb = {k: v for k, v in SUPABASE.items() if k != faltando}
            with self.subTest(faltando=faltando), self.assertRaisesMessage(ImproperlyConfigured, faltando):
                configurar_banco(amb)

    def test_alvo_invalido(self):
        with self.assertRaises(ImproperlyConfigured):
            configurar_banco({**LOCAL, "DB_ALVO": "producao"})

    def test_porta_invalida(self):
        with self.assertRaises(ImproperlyConfigured):
            configurar_banco({**SUPABASE, "SUPABASE_DB_PORT": "abc"})

    def test_local_nao_aceita_host_do_supabase(self):
        with self.assertRaises(ImproperlyConfigured):
            configurar_banco({**LOCAL, "POSTGRES_HOST": "db.ref.supabase.co"})

    def test_reconhece_hosts_do_supabase(self):
        self.assertTrue(e_host_supabase("aws-0-sa-east-1.pooler.supabase.com"))
        self.assertTrue(e_host_supabase("db.abc.supabase.co"))
        self.assertFalse(e_host_supabase("db"))
        self.assertFalse(e_host_supabase("naosupabase.com"))


class IsolamentoDosTestesTests(SimpleTestCase):
    def test_suite_atual_roda_no_banco_local(self):
        self.assertEqual(settings.BANCO_ALVO, "local")
        self.assertFalse(e_host_supabase(settings.DATABASES["default"]["HOST"]))

    def test_recusa_alvo_supabase(self):
        with self.assertRaises(ImproperlyConfigured):
            verificar_banco_de_teste("supabase", {"default": configurar_banco(SUPABASE)})

    def test_recusa_host_do_supabase_mesmo_com_alvo_local(self):
        with self.assertRaises(ImproperlyConfigured):
            verificar_banco_de_teste("local", {"default": {"HOST": "x.pooler.supabase.com"}})

    def test_aceita_banco_local(self):
        verificar_banco_de_teste("local", {"default": configurar_banco(LOCAL)})
