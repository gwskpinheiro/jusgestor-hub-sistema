from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.core.seguranca_banco import PAPEIS_DATA_API, comandos_revogacao, revogar_data_api


class ComandosRevogacaoTests(SimpleTestCase):
    def test_afeta_somente_os_papeis_da_data_api(self):
        for sql in comandos_revogacao(["anon", "authenticated"]):
            with self.subTest(sql=sql):
                self.assertIn("REVOKE", sql)
                self.assertTrue(sql.endswith("FROM anon, authenticated"))
                self.assertIn("SCHEMA public", sql)
                self.assertNotIn("GRANT", sql.replace("REVOKE", ""))
                for papel in ("postgres", "service_role", "PUBLIC"):
                    self.assertNotIn(papel, sql)

    def test_papeis_previstos(self):
        self.assertEqual(PAPEIS_DATA_API, ("anon", "authenticated"))


class RevogacaoNoBancoLocalTests(TestCase):
    def test_sem_papeis_da_data_api_nada_e_executado(self):
        with connection.cursor() as cursor:
            self.assertEqual(revogar_data_api(cursor), [])
