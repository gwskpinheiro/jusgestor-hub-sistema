"""Configurações do JusGestor Hub.

Valores sensíveis são lidos de variáveis de ambiente (arquivo .env, fora do
repositório), conforme RNF02.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config import ambiente
from config.banco import alvo_do_banco, configurar_banco

BASE_DIR = Path(__file__).resolve().parent.parent


def env(nome, padrao=None, obrigatorio=False):
    valor = os.environ.get(nome, padrao)
    if obrigatorio and not valor:
        raise ImproperlyConfigured(f"Variável de ambiente obrigatória ausente: {nome}")
    return valor


SECRET_KEY = env("DJANGO_SECRET_KEY", obrigatorio=True)
# Padrão seguro: sem DJANGO_DEBUG=1, o sistema roda em modo de produção.
DEBUG = ambiente.booleano(os.environ, "DJANGO_DEBUG")
ALLOWED_HOSTS = ambiente.hosts_permitidos(os.environ)
CSRF_TRUSTED_ORIGINS = ambiente.origens_csrf(os.environ)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.usuarios",
    "apps.clientes",
    "apps.processos",
    "apps.agenda",
    "apps.documentos",
    "apps.horas",
    "apps.financeiro",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serve os arquivos estáticos em produção (Render), logo após o SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "apps.usuarios.middleware.TrocaSenhaObrigatoriaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.menu",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco escolhido por DB_ALVO: "local" (Docker, padrão) ou "supabase"
# (Session Pooler com SSL). Detalhes em config/banco.py e docs/supabase.md.
BANCO_ALVO = alvo_do_banco(os.environ)
DATABASES = {"default": configurar_banco(os.environ)}

# Os testes só rodam no PostgreSQL local; o executor recusa o Supabase.
TEST_RUNNER = "config.test_runner.RunnerBancoIsolado"

# ---------------------------------------------------------------------------
# Autenticação (RF01, RN06, RN07, RNF02)
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "usuarios.Usuario"
AUTHENTICATION_BACKENDS = ["apps.usuarios.backends.EmailBloqueioBackend"]

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "core:painel"
LOGOUT_REDIRECT_URL = "usuarios:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("email", "nome")}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# RF01: bloquear por 15 minutos após cinco falhas consecutivas.
LOGIN_MAX_TENTATIVAS = 5
LOGIN_MINUTOS_BLOQUEIO = 15

# RF01: expirar a sessão após 30 minutos sem atividade.
# A cada requisição a validade é renovada, de modo que conta a inatividade.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# HTTPS (produção): ativado com DJANGO_HTTPS=1. Cookies seguros, redirecionamento
# para HTTPS e HSTS. Ver config/ambiente.py.
HTTPS = ambiente.booleano(os.environ, "DJANGO_HTTPS")
globals().update(ambiente.config_https(os.environ))

# HSTS sem subdomínios e sem preload: o domínio *.onrender.com não pertence ao
# projeto. Escolha deliberada; ver docs/render.md.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# No Render, recusa iniciar com DEBUG ligado, sem HTTPS ou fora do Supabase.
ambiente.validar_producao(os.environ, DEBUG, HTTPS, BANCO_ALVO)

# ---------------------------------------------------------------------------
# Internacionalização
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Arquivos estáticos e documentos privados
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Em produção, o WhiteNoise serve os arquivos gerados por "collectstatic",
# comprimidos e com nomes versionados (cache de longo prazo). Em
# desenvolvimento e nos testes (DEBUG=1), usa o armazenamento padrão, que não
# exige executar collectstatic.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Documentos ficam fora de STATIC/MEDIA públicos e serão entregues apenas por
# view com verificação de permissão (RN04, RF06) — implementado em fase futura.
DOCUMENTOS_ROOT = Path(env("DOCUMENTOS_ROOT", "/data/documentos"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO"},
        # Erros do Django (inclusive 500) nos logs do Render, também com DEBUG=0.
        "django": {"handlers": ["console"], "level": "ERROR"},
    },
}
