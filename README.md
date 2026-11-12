# JusGestor Hub

Sistema web de gestão jurídica para advogados autônomos e pequenos escritórios.
É o Trabalho de Conclusão de Curso de Análise e Desenvolvimento de Sistemas
(IFPR, campus Paranaguá).

A especificação completa (regras de negócio, requisitos, diagramas e telas)
está no artigo, em `docs/referencias/`.

**Tecnologias:** Python 3.12, Django 5.2 LTS, PostgreSQL 17, HTML, CSS,
JavaScript e Docker Compose.

## Situação atual: primeira versão integrada dos módulos

Implementado e coberto por testes automatizados (PostgreSQL local):

| Módulo | Requisitos |
|---|---|
| Autenticação | RF01 |
| Clientes | RF03 |
| Processos | RF02 |
| Agenda | RF04 |
| Financeiro | RF05 |
| Documentos | RF06 |
| Horas trabalhadas | RF07 |
| Relatórios | RF08 |
| Usuários e acessos | RF09 |

As regras RN01 a RN10 são verificadas no servidor e por registro. As decisões
de interpretação estão em
[docs/alteracoes-modelo.md](docs/alteracoes-modelo.md).

Pendente:
- RNF07: os scripts de cópia e de teste de restauração estão prontos
  ([docs/backup.md](docs/backup.md)), mas a rotina de copiar após cada sessão
  com alterações e manter a cópia em outro dispositivo depende do usuário;
- armazenamento persistente de documentos no Render;
- migrações destes módulos no Supabase;
- conferência visual em navegador (Chrome e Firefox, 360 e 1366 px) e
  medição de desempenho (RNF04).

## Pré-requisitos

- Windows com Docker Desktop (WSL 2) e Docker Compose.
- Git.

## Instalação

1. Crie o arquivo `.env` a partir do modelo:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Gere valores aleatórios para `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD` e
   preencha o `.env`:

   ```powershell
   docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   O `.env` contém credenciais e **não** é versionado (RNF02).

3. Construa as imagens, aplique as migrações e suba o sistema:

   ```powershell
   docker compose build
   docker compose up -d db
   docker compose run --rm web python manage.py migrate
   docker compose up -d
   ```

4. Crie o primeiro administrador. A senha temporária é gerada
   aleatoriamente, aparece uma única vez e precisa ser trocada no primeiro
   acesso:

   ```powershell
   docker compose exec web python manage.py criar_admin --email adm@exemplo.test --nome "Nome do Administrador"
   ```

5. Acesse **http://127.0.0.1:8000** pelo Chrome ou pelo Firefox.

A porta só é publicada em `127.0.0.1` e o banco não é exposto fora da rede do
Compose (RNF03).

## Bancos de dados

A variável `DB_ALVO` do `.env` escolhe o banco:

- `local` (padrão): PostgreSQL do Docker, para desenvolvimento e testes.
- `supabase`: PostgreSQL do Supabase (Session Pooler, SSL obrigatório), para
  o sistema publicado.

Os testes automatizados só rodam com `local`; com outro valor, o executor de
testes interrompe a execução antes de conectar. Para preencher e testar a
conexão com o Supabase, veja [docs/supabase.md](docs/supabase.md).

```powershell
docker compose run --rm web python manage.py verificar_banco                      # banco local
docker compose run --rm -e DB_ALVO=supabase web python manage.py verificar_banco  # Supabase (somente leitura)
```

## Produção (Render)

Em produção, o sistema roda com Gunicorn e WhiteNoise no Render, usando o
banco do Supabase. Os comandos de build e start, as variáveis de ambiente e
as proteções estão em [docs/render.md](docs/render.md).

## Testes

```powershell
docker compose run --rm web python manage.py test
```

Os testes usam um banco temporário (`test_jusgestor`) e apenas dados
fictícios (RNF08).

## Comandos úteis

| Ação | Comando |
|---|---|
| Ver logs | `docker compose logs -f web` |
| Parar | `docker compose down` |
| Criar migrações | `docker compose run --rm web python manage.py makemigrations` |
| Aplicar migrações | `docker compose run --rm web python manage.py migrate` |
| Dados fictícios (clientes, processos, agenda) + medição do RNF04, só banco local | `docker compose exec web python manage.py popular_dados_teste --medir --http` |

`docker compose down -v` **apaga** o banco e os documentos (volumes). Só use
depois de fazer uma cópia de segurança.

## Backup e restauração (RNF07)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup\backup.ps1               # copia banco e documentos para backups\
powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1   # restaura numa instância descartável e compara
```

Copie após cada sessão com alterações e antes de atualizações, e guarde a
pasta gerada em outro dispositivo. Detalhes e a restauração real estão em
[docs/backup.md](docs/backup.md).

## Estrutura

```
config/              configurações, URLs, WSGI, seleção do banco (banco.py),
                     produção/HTTPS (ambiente.py) e executor de testes
gunicorn.conf.py     servidor de produção
apps/core/           layout, painel, menu por perfil, verificações de perfil
apps/usuarios/       modelo de usuário, autenticação, bloqueio, troca de senha
templates/           páginas HTML (templates Django)
static/css, static/js
docs/referencias/    artigo do TCC (não modificar)
docs/alteracoes-modelo.md  diferenças em relação ao modelo relacional do artigo
docs/supabase.md     conexão com o PostgreSQL do Supabase
docs/render.md       hospedagem no Render
docs/backup.md       backup e teste de restauração (RNF07)
scripts/backup/      scripts de cópia e de teste de restauração
```

## Perfis e permissões

| Perfil | Código | Acesso |
|---|---|---|
| Administrador/Gestor | `ADM` | Todos os registros, usuários e financeiro |
| Advogado | `ADV` | Processos sob sua responsabilidade ou autorizados; horas próprias; relatórios autorizados |
| Assistente/Secretaria | `AST` | Clientes e processos autorizados pelo ADM; agenda; documentos |

Todas as verificações são feitas no servidor (RN07). Esconder um item do menu
não substitui essa verificação.
