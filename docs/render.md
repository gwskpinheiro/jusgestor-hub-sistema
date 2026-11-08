# Hospedagem no Render

Repositório: `gwskpinheiro/jusgestor-hub-sistema` (branch `main`).

| Ambiente | Servidor | Banco | Configuração |
|---|---|---|---|
| Desenvolvimento | `runserver` no Docker | PostgreSQL do Docker | `.env` local, `DJANGO_DEBUG=1` |
| Testes | executor do Django no Docker | PostgreSQL do Docker (`test_jusgestor`) | sempre `DB_ALVO=local` |
| Produção | Gunicorn no Render (runtime Python nativo) | Supabase (Session Pooler, SSL) | variáveis no painel do Render |

O Dockerfile e o `docker-compose.yml` continuam sendo usados só no
desenvolvimento. O Render instala as dependências e executa o Gunicorn
diretamente.

## 1. Criar o serviço

No Render, crie um **New > Web Service** a partir do repositório do GitHub:

| Campo | Valor |
|---|---|
| Language / Runtime | Python 3 |
| Branch | `main` |
| Root Directory | (vazio) |
| Region | Virginia ou Ohio (EUA, as mais próximas do Supabase `sa-east-1`) |
| Build Command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Start Command | `gunicorn config.wsgi:application` |
| Health Check Path | `/conta/entrar/` |
| Auto-Deploy | desativado até a primeira validação (recomendado) |

- O Gunicorn lê o `gunicorn.conf.py`: porta `PORT` (definida pelo Render),
  `WEB_CONCURRENCY` processos (padrão 2) e logs no painel.
- O `collectstatic` gera os arquivos em `staticfiles/`. O WhiteNoise os serve
  comprimidos e com nomes versionados, com cache de longo prazo.
- **As migrações não rodam no build nem no start.** Elas são aplicadas
  manualmente a partir do ambiente local, na ordem descrita em
  [supabase.md](supabase.md) (seção 5). Assim o isolamento da Data API é
  sempre verificado.

## 2. Variáveis de ambiente (painel > Environment)

Cadastre os valores **somente no painel do Render**. Nada disso vai para o Git.

| Variável | Valor | Observação |
|---|---|---|
| `PYTHON_VERSION` | `3.12.16` | Mesma versão da imagem de desenvolvimento |
| `DJANGO_SECRET_KEY` | **nova** chave aleatória | Não reutilize a chave local |
| `DJANGO_DEBUG` | `0` | |
| `DJANGO_HTTPS` | `1` | Cookies seguros, redirecionamento para HTTPS e HSTS |
| `DB_ALVO` | `supabase` | |
| `SUPABASE_DB_HOST` | host do Session pooler | Mesmos valores do `.env` local |
| `SUPABASE_DB_PORT` | `5432` | |
| `SUPABASE_DB_NAME` | `postgres` | |
| `SUPABASE_DB_USER` | `postgres.<referência-do-projeto>` | |
| `SUPABASE_DB_PASSWORD` | senha do banco | |
| `SUPABASE_DB_SSLMODE` | `require` (ou `verify-full`, ver abaixo) | |
| `DJANGO_ALLOWED_HOSTS` | opcional | Domínios próprios, separados por vírgula |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | opcional | Ex.: `https://meu-dominio.com.br` |
| `DJANGO_HSTS_SECONDS` | opcional (padrão `3600`) | Ampliar só depois de validar o HTTPS |
| `WEB_CONCURRENCY` | opcional (padrão `2`) | Cada processo abre uma conexão com o Supabase |

O Render já define `RENDER=true` e `RENDER_EXTERNAL_HOSTNAME`, por exemplo
`jusgestor-hub-sistema.onrender.com`. Esse endereço é incluído
automaticamente em `ALLOWED_HOSTS` e em `CSRF_TRUSTED_ORIGINS`
(`https://...`).

Para gerar a chave secreta:

```powershell
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### SSL com verificação do certificado (recomendado)

1. Baixe o certificado do Supabase em *Database Settings > SSL Configuration*.
2. No Render, em **Environment > Secret Files**, crie `supabase-ca.crt` com o
   conteúdo do certificado.
3. Defina `SUPABASE_DB_SSLMODE=verify-full` e
   `SUPABASE_DB_SSLROOTCERT=/etc/secrets/supabase-ca.crt`.

## 3. Proteções de produção

Quando `RENDER=true`, a aplicação **se recusa a iniciar** se `DJANGO_DEBUG`
não for `0`, se `DJANGO_HTTPS` não for `1` ou se `DB_ALVO` não for `supabase`
(ver `config/ambiente.py`).

Com `DJANGO_HTTPS=1`:

- HTTP é redirecionado para HTTPS. O Render informa o protocolo original em
  `X-Forwarded-Proto`, aceito via `SECURE_PROXY_SSL_HEADER`.
- Os cookies de sessão e de CSRF são marcados como `Secure`.
- HSTS fica ativo com `max-age` configurável, sem `includeSubDomains` e sem
  `preload`, porque o domínio `onrender.com` não pertence ao projeto. Os
  avisos `security.W005` e `security.W021` do `check --deploy` foram
  silenciados por isso.

## 4. Validação local do modo de produção

A simulação abaixo usa a imagem Docker sem montar a pasta do projeto. O
hostname é fictício e as requisições são apenas `GET` anônimos, que não
alteram o banco.

```powershell
docker compose build web
docker run --rm --env-file .env -e RENDER=true -e RENDER_EXTERNAL_HOSTNAME=jusgestor-teste.onrender.com `
  -e DJANGO_DEBUG=0 -e DJANGO_HTTPS=1 -e DB_ALVO=supabase -e DJANGO_ALLOWED_HOSTS= -e PORT=10000 `
  jusgestor-hub-web sh -c "python manage.py collectstatic --noinput && python manage.py check --deploy"
```

Resultado esperado: `System check identified no issues (2 silenced).`

## 5. Depois do primeiro deploy

1. Acesse `https://<serviço>.onrender.com`. O endereço `http://` deve
   redirecionar para `https://`.
2. Entre com o administrador criado no Supabase.
3. Confira os logs no painel: erros do Django e do Gunicorn aparecem ali.

## 6. Pendências e limitações

- **Documentos (RN04, RF06):** o sistema de arquivos do Render é temporário,
  e os arquivos somem a cada deploy ou reinício. Antes de implementar o
  módulo de documentos, é preciso escolher um armazenamento persistente
  privado (por exemplo, Render Disk em plano pago ou Supabase Storage com
  bucket privado). Isso ainda não está implementado.
- **Plano gratuito:** o serviço "dorme" após um período sem acesso, e o
  primeiro acesso seguinte demora mais.
- **Latência:** o Render não tem região no Brasil, e cada consulta vai dos
  EUA ao Supabase em São Paulo.
- **Backup (RNF07):** rotina de cópia do Supabase ainda a definir.
