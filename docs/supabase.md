# Conexão com o PostgreSQL do Supabase

| Ambiente | Banco | `DB_ALVO` |
|---|---|---|
| Desenvolvimento | PostgreSQL 17 no Docker | `local` (padrão) |
| Testes automatizados | Banco temporário `test_jusgestor` no PostgreSQL do Docker | `local` (**obrigatório**) |
| Sistema publicado | Supabase, via Session Pooler (porta 5432, SSL obrigatório) | `supabase` |

A autenticação continua sendo a do Django (tabela `usuario`). O Supabase Auth
**não** é usado: o Supabase serve apenas como servidor PostgreSQL.

## 1. Obter os parâmetros no Supabase

No painel do projeto, clique em **Connect** e escolha **Session pooler**. Os
campos do `.env` correspondem a:

| Campo no Supabase | Variável no `.env` | Formato esperado |
|---|---|---|
| host | `SUPABASE_DB_HOST` | `aws-0-<região>.pooler.supabase.com` (o prefixo pode ser `aws-1-`) |
| port | `SUPABASE_DB_PORT` | `5432` (Session pooler) |
| database | `SUPABASE_DB_NAME` | `postgres` |
| user | `SUPABASE_DB_USER` | `postgres.<referência-do-projeto>` |
| password | `SUPABASE_DB_PASSWORD` | Senha do banco (pode ser redefinida em *Database Settings*) |

O Session Pooler aceita conexões IPv4 e mantém uma sessão por conexão. Por
isso funciona com o Django sem ajustes especiais. A porta 6543 (Transaction
pooler) **não** é usada.

## 2. Preencher o `.env` local

Edite **somente** o arquivo `.env`, que o Git ignora. Nunca coloque esses
valores no `.env.example`, no código ou em mensagens de commit.

```dotenv
DB_ALVO=local                 # deixe "local" no dia a dia

SUPABASE_DB_HOST=aws-0-<região>.pooler.supabase.com
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.<referência-do-projeto>
SUPABASE_DB_PASSWORD=<senha do banco>
SUPABASE_DB_SSLMODE=require
SUPABASE_DB_SSLROOTCERT=
```

- Se a senha tiver `$`, `#`, espaços ou aspas, coloque o valor entre aspas
  simples (`SUPABASE_DB_PASSWORD='...'`). Sem isso, o Docker Compose pode
  interpretar esses caracteres.
- Mantenha `DB_ALVO=local` no `.env`. Para usar o Supabase pontualmente,
  passe `-e DB_ALVO=supabase` no comando, como no passo 3. Assim o servidor de
  desenvolvimento e os testes nunca apontam para o Supabase por engano.

### SSL

- `require` (padrão): a conexão é sempre criptografada. Os modos `disable`,
  `allow` e `prefer` são recusados pela configuração.
- `verify-full` (recomendado para o sistema publicado): além de criptografar,
  confirma que o servidor é mesmo o Supabase. Para usar:
  1. No painel, em **Database Settings > SSL Configuration**, baixe o certificado.
  2. Salve-o em `certs/supabase-ca.crt`. A pasta `certs/` é ignorada pelo Git.
  3. Configure:
     ```dotenv
     SUPABASE_DB_SSLMODE=verify-full
     SUPABASE_DB_SSLROOTCERT=/app/certs/supabase-ca.crt
     ```
     O caminho é o de dentro do container, porque o projeto é montado em `/app`.

## 3. Testar a conexão (somente leitura)

```powershell
docker compose run --rm -e DB_ALVO=supabase web python manage.py verificar_banco
```

O comando roda numa transação somente leitura. Ele não aplica migrações, não
cria tabelas e não mostra usuário nem senha. Resultado esperado para um
projeto ainda vazio:

```
Alvo: supabase
Servidor: aws-0-<região>.pooler.supabase.com:5432  Banco: postgres
PostgreSQL: 17.x ...
SSL: ativo (sslmode=require)
Tabelas visíveis: 0
Migrações pendentes: 16
Conexão OK. Nenhuma alteração foi feita.
```

| Erro | Causa provável |
|---|---|
| `Variável de ambiente obrigatória ausente: SUPABASE_DB_...` | Campo vazio no `.env` |
| `password authentication failed` | Senha incorreta, ou usuário sem `.<referência-do-projeto>` |
| `timeout` / `could not translate host name` | Host incorreto ou rede bloqueando a porta 5432 |
| `certificate verify failed` | Certificado ausente ou errado com `verify-full` |

Para conferir o banco local, use o mesmo comando sem `-e DB_ALVO=supabase`.

## 4. Proteções para os testes

- `config/test_runner.py` interrompe `manage.py test` **antes de qualquer
  conexão** quando `DB_ALVO` não é `local` ou quando algum host pertence ao
  Supabase (`*.supabase.com` ou `*.supabase.co`).
- Com `DB_ALVO=local`, `POSTGRES_HOST` não aceita um host do Supabase.
- O banco de teste se chama `test_jusgestor` e fica no PostgreSQL do Docker.
  O Django cria e apaga esse banco a cada execução. O banco `jusgestor`, com o
  administrador e os demais dados locais, não é tocado.

## 5. Isolamento da Data API (obrigatório antes do primeiro `migrate`)

No Supabase, toda tabela criada no schema `public` recebe por padrão todos os
privilégios para os papéis `anon` e `authenticated`, que são os papéis da API
REST. Sem correção, quem tivesse a chave pública `anon` poderia ler a tabela
`usuario` ou inserir um administrador. O JusGestor Hub não usa essa API.

Proteção adotada:

1. **Data API desativada** no painel (*Project Settings > Data API*).
2. **Privilégios revogados** somente de `anon` e `authenticated`. O papel
   usado pelo Django (`postgres`) mantém todos os seus privilégios:
   - antes do primeiro `migrate`, pelo comando `proteger_data_api`, que
     altera os privilégios padrão para que as tabelas já nasçam protegidas;
   - na migração `core.0001_isolar_data_api`, que repete a revogação ao fim
     de cada `migrate` em um banco novo. No PostgreSQL local, onde esses papéis
     não existem, ela não faz nada.

Ordem para preparar um Supabase novo:

```powershell
docker compose run --rm -e DB_ALVO=supabase web python manage.py proteger_data_api --verificar
docker compose run --rm -e DB_ALVO=supabase web python manage.py proteger_data_api
docker compose run --rm -e DB_ALVO=supabase web python manage.py migrate
docker compose run --rm -e DB_ALVO=supabase web python manage.py proteger_data_api --verificar   # esperado: 0 e 0
docker compose run --rm -e DB_ALVO=supabase web python manage.py verificar_banco                 # esperado: 0 pendentes
```

Novas tabelas criadas por migrações futuras também nascem sem acesso para
`anon` e `authenticated`, por causa dos privilégios padrão já revogados.
Mesmo assim, rode `proteger_data_api --verificar` depois de cada `migrate`
no Supabase.

O Security Advisor do Supabase pode avisar sobre "RLS disabled" nas tabelas
do Django. Com os privilégios revogados e a Data API desligada, essas tabelas
não ficam acessíveis pela API.

## 6. Situação

- Migrações aplicadas no Supabase em 08/11/2026, com a Data API isolada.
- Administrador criado no Supabase e login validado em 08/11/2026, incluindo troca obrigatória da senha temporária.
- Pendente: publicar o Django (servidor de produção, `DEBUG=0`, `ALLOWED_HOSTS` e HTTPS já
  preparados) e configurar o Storage dos documentos (seção 7).

## 7. Storage dos documentos (preparado no código, ainda não configurado)

O código já grava e lê os documentos por uma camada de armazenamento
(`config/armazenamento.py` e `apps/documentos/armazenamento.py`):

- `DOCUMENTOS_ARMAZENAMENTO=local` (padrão): pasta `DOCUMENTOS_ROOT`,
  usada no desenvolvimento e **sempre** nos testes;
- `DOCUMENTOS_ARMAZENAMENTO=supabase`: bucket privado do Supabase Storage
  pela API compatível com S3 (`django-storages` + `boto3`), obrigatório no
  Render.

O banco guarda a mesma chave nos dois casos (`<documento>/<uuid>.<ext>`); no
bucket, os arquivos ficam sob `SUPABASE_STORAGE_PREFIXO` (padrão
`documentos/`). Os arquivos nunca são servidos por link direto ao bucket:
download e "Visualizar" passam pelas views do Django, que verificam a
permissão do usuário.

Para ativar (etapa futura, sem mudança de código):

1. **Bucket privado:** Storage > New bucket, com "Public bucket" **desligado**,
   limite de tamanho de 10 MB e tipos permitidos `application/pdf`,
   `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
   `image/png` e `image/jpeg`. Não crie políticas (RLS) para `anon` ou
   `authenticated`.
2. **Acesso S3:** Storage > Settings > S3 Connection: copie o endpoint e a
   região e crie um par de chaves de acesso. As chaves dão acesso total ao
   Storage do projeto e ignoram as políticas: guarde-as somente no `.env`
   local e nas variáveis do Render.
3. **Variáveis:** preencha `SUPABASE_STORAGE_*` (ver `.env.example`).
4. **Teste de conexão:** grava, lê (com conferência SHA-256) e remove um
   único PDF fictício no prefixo exclusivo `verificacao-conexao/`, sem listar
   nem tocar nos documentos e sem mudar `DOCUMENTOS_ARMAZENAMENTO`:

   ```powershell
   docker compose run --rm web python manage.py verificar_armazenamento --remoto --confirmar <nome-do-bucket>
   ```

   Executado com sucesso em 12/11/2026 no bucket `jusgestor-documentos`.
5. **Backup:** o backup do banco do Supabase **não inclui** os arquivos do
   Storage; a cópia dos documentos precisa de rotina própria (ainda a criar).
