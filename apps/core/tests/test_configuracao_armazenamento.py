"""Seleção do armazenamento de documentos por variáveis de ambiente (sem rede).

Nenhum teste conecta ao Supabase: as credenciais abaixo são fictícias e o
cliente S3 é apenas instanciado (o boto3 não acessa a rede ao ser criado).
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config import armazenamento as cfg

SEGREDO = "segredo-ficticio-nao-usar-0123456789"
SUPABASE = {
    "DOCUMENTOS_ARMAZENAMENTO": "supabase",
    "SUPABASE_STORAGE_ENDPOINT": "https://projetoficticio.storage.supabase.co/storage/v1/s3",
    "SUPABASE_STORAGE_REGION": "sa-east-1",
    "SUPABASE_STORAGE_BUCKET": "documentos-privados",
    "SUPABASE_STORAGE_ACCESS_KEY_ID": "chave-ficticia",
    "SUPABASE_STORAGE_SECRET_ACCESS_KEY": SEGREDO,
}


class AlvoTests(SimpleTestCase):
    def test_padrao_e_local(self):
        self.assertEqual(cfg.alvo_armazenamento({}), "local")
        self.assertEqual(cfg.alvo_armazenamento({"DOCUMENTOS_ARMAZENAMENTO": " Supabase "}), "supabase")

    def test_valor_invalido(self):
        for valor in ("s3", "disco", "render"):
            with self.subTest(valor=valor), self.assertRaises(ImproperlyConfigured):
                cfg.alvo_armazenamento({"DOCUMENTOS_ARMAZENAMENTO": valor})

    def test_local_usa_backend_privado(self):
        self.assertEqual(cfg.config_armazenamento({}, "local"), {"BACKEND": cfg.BACKEND_LOCAL})

    def test_execucao_dos_testes_usa_armazenamento_local(self):
        self.assertEqual(settings.DOCUMENTOS_ARMAZENAMENTO, "local")
        self.assertEqual(settings.STORAGES["documentos"]["BACKEND"], cfg.BACKEND_LOCAL)


class SupabaseConfigTests(SimpleTestCase):
    def test_configuracao_privada(self):
        c = cfg.config_armazenamento(SUPABASE, "supabase")
        self.assertEqual(c["BACKEND"], "storages.backends.s3.S3Storage")
        op = c["OPTIONS"]
        self.assertEqual(op["bucket_name"], "documentos-privados")
        self.assertEqual(op["location"], "documentos")
        self.assertIsNone(op["default_acl"])          # sem ACL pública
        self.assertFalse(op["file_overwrite"])        # versões nunca sobrescritas
        self.assertTrue(op["querystring_auth"])       # nenhum link sem assinatura
        self.assertEqual(op["querystring_expire"], 60)
        self.assertEqual(op["object_parameters"], {"CacheControl": "private, no-store"})
        self.assertEqual(op["client_config"].s3, {"addressing_style": "path"})
        self.assertEqual(op["client_config"].request_checksum_calculation, "when_required")

    def test_variaveis_obrigatorias(self):
        for nome in ("SUPABASE_STORAGE_ENDPOINT", "SUPABASE_STORAGE_REGION", "SUPABASE_STORAGE_BUCKET",
                     "SUPABASE_STORAGE_ACCESS_KEY_ID", "SUPABASE_STORAGE_SECRET_ACCESS_KEY"):
            with self.subTest(variavel=nome):
                amb = {**SUPABASE, nome: "  "}
                with self.assertRaisesMessage(ImproperlyConfigured, nome) as ctx:
                    cfg.config_supabase(amb)
                self.assertNotIn(SEGREDO, str(ctx.exception))

    def test_recusa_endpoint_inseguro_ou_de_outro_dominio(self):
        for endpoint in ("http://projetoficticio.storage.supabase.co/storage/v1/s3",
                         "https://s3.amazonaws.com", "https://supabase.co.exemplo.test/s3", "projeto.supabase.co"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ImproperlyConfigured) as ctx:
                cfg.config_supabase({**SUPABASE, "SUPABASE_STORAGE_ENDPOINT": endpoint})
            self.assertNotIn(SEGREDO, str(ctx.exception))

    def test_recusa_bucket_regiao_e_prefixo_invalidos(self):
        casos = {
            "SUPABASE_STORAGE_BUCKET": ("Documentos", "a", "docs/privados", "../x"),
            "SUPABASE_STORAGE_REGION": ("sao paulo", "sa-east"),
            "SUPABASE_STORAGE_PREFIXO": ("../fora", "a//b", "Docs", "a/../b"),
        }
        for nome, valores in casos.items():
            for valor in valores:
                with self.subTest(variavel=nome, valor=valor), self.assertRaises(ImproperlyConfigured):
                    cfg.config_supabase({**SUPABASE, nome: valor})

    def test_prefixo_configuravel(self):
        op = cfg.config_supabase({**SUPABASE, "SUPABASE_STORAGE_PREFIXO": "/jusgestor/documentos/"})["OPTIONS"]
        self.assertEqual(op["location"], "jusgestor/documentos")

    def test_cliente_s3_instanciado_sem_rede(self):
        from storages.backends.s3 import S3Storage

        armazenamento = S3Storage(**cfg.config_supabase(SUPABASE)["OPTIONS"])
        cliente = armazenamento.connection.meta.client  # criado localmente, sem requisição
        self.assertEqual(cliente.meta.endpoint_url, SUPABASE["SUPABASE_STORAGE_ENDPOINT"])
        self.assertEqual(cliente.meta.region_name, "sa-east-1")
        self.assertEqual(cliente.meta.config.s3["addressing_style"], "path")
        # Se url() fosse chamado, o link seria assinado e expiraria em 60 s.
        link = armazenamento.url("1/" + "a" * 32 + ".pdf")
        self.assertIn("X-Amz-Expires=60", link)
        self.assertIn("/documentos-privados/documentos/1/", link)
        self.assertNotIn(SEGREDO, link)


class GuardaDosTestesTests(SimpleTestCase):
    def test_aceita_somente_local(self):
        cfg.verificar_armazenamento_de_teste("local", {"documentos": {"BACKEND": cfg.BACKEND_LOCAL}})
        for alvo, backend in (("supabase", cfg.BACKEND_LOCAL), ("local", cfg.BACKEND_S3), ("supabase", cfg.BACKEND_S3)):
            with self.subTest(alvo=alvo, backend=backend), self.assertRaises(ImproperlyConfigured):
                cfg.verificar_armazenamento_de_teste(alvo, {"documentos": {"BACKEND": backend}})
