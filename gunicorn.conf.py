"""Configuração do Gunicorn (servidor de produção).

O Gunicorn carrega este arquivo automaticamente quando iniciado na raiz do
projeto:  gunicorn config.wsgi:application

PORT é definida pelo Render. WEB_CONCURRENCY pode ser ajustada no painel
conforme a memória do plano (cada processo abre sua conexão com o Supabase).
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30

# Logs no stdout/stderr, exibidos no painel do Render.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

# O proxy do Render informa o protocolo original (HTTPS) em X-Forwarded-Proto.
forwarded_allow_ips = "*"
