"""Configurações de execução (desenvolvimento x produção) lidas do ambiente.

As funções recebem o mapeamento de ambiente como parâmetro para poderem ser
testadas sem alterar o processo. Valores secretos nunca são definidos aqui.

No Render, a variável RENDER=true e o RENDER_EXTERNAL_HOSTNAME
(ex.: jusgestor-hub-sistema.onrender.com) são definidos pela própria
plataforma.
"""
from django.core.exceptions import ImproperlyConfigured

from config.armazenamento import ARMAZENAMENTO_SUPABASE
from config.banco import ALVO_SUPABASE


def booleano(amb, nome, padrao=False):
    valor = (amb.get(nome) or "").strip().lower()
    if not valor:
        return padrao
    if valor in ("1", "true", "sim", "yes", "on"):
        return True
    if valor in ("0", "false", "nao", "não", "no", "off"):
        return False
    raise ImproperlyConfigured(f"{nome} deve ser 1 ou 0.")


def lista(amb, nome, padrao=""):
    return [item.strip() for item in (amb.get(nome) or padrao).split(",") if item.strip()]


def inteiro(amb, nome, padrao):
    valor = (amb.get(nome) or "").strip() or str(padrao)
    if not valor.isdigit():
        raise ImproperlyConfigured(f"{nome} deve ser um número inteiro não negativo.")
    return int(valor)


def no_render(amb):
    return booleano(amb, "RENDER")


def hosts_permitidos(amb):
    hosts = lista(amb, "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
    externo = (amb.get("RENDER_EXTERNAL_HOSTNAME") or "").strip()
    if externo and externo not in hosts:
        hosts.append(externo)
    return hosts


def origens_csrf(amb):
    origens = lista(amb, "DJANGO_CSRF_TRUSTED_ORIGINS")
    for origem in origens:
        if not origem.startswith(("https://", "http://")):
            raise ImproperlyConfigured(
                "DJANGO_CSRF_TRUSTED_ORIGINS deve conter origens completas, ex.: https://exemplo.onrender.com"
            )
    externo = (amb.get("RENDER_EXTERNAL_HOSTNAME") or "").strip()
    if externo and f"https://{externo}" not in origens:
        origens.append(f"https://{externo}")
    return origens


def config_https(amb):
    """Configurações do Django para sites servidos somente por HTTPS.

    O Render encerra o TLS no proxy e encaminha a requisição informando o
    protocolo original em X-Forwarded-Proto; por isso SECURE_PROXY_SSL_HEADER.
    """
    if not booleano(amb, "DJANGO_HTTPS"):
        return {}
    return {
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
        "SECURE_SSL_REDIRECT": True,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        # Começa com 1 hora; pode ser ampliado depois de validar o domínio.
        "SECURE_HSTS_SECONDS": inteiro(amb, "DJANGO_HSTS_SECONDS", 3600),
        # O domínio *.onrender.com não é controlado pelo projeto.
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SECURE_HSTS_PRELOAD": False,
    }


def validar_producao(amb, debug, https, alvo_banco, *, alvo_documentos):
    """No Render, recusa iniciar com configuração insegura."""
    if not no_render(amb):
        return
    problemas = []
    if debug:
        problemas.append("DJANGO_DEBUG deve ser 0")
    if not https:
        problemas.append("DJANGO_HTTPS deve ser 1")
    if alvo_banco != ALVO_SUPABASE:
        problemas.append("DB_ALVO deve ser supabase")
    # O disco do Render é temporário: documentos gravados nele somem a cada deploy.
    if alvo_documentos != ARMAZENAMENTO_SUPABASE:
        problemas.append("DOCUMENTOS_ARMAZENAMENTO deve ser supabase (o disco do Render é temporário)")
    if problemas:
        raise ImproperlyConfigured("Configuração de produção inválida: " + "; ".join(problemas) + ".")
