# Backup e restauração (RNF07)

> **RNF07 Recuperação:** "Preservar integridade no banco. Copiar banco e
> documentos após sessões com alterações e antes de atualizações, manter cópia
> independente e testar restauração." (artigo, Tabela 4)

Os scripts ficam em `scripts/backup/` e rodam no Windows PowerShell 5.1 ou 7.
Só funcionam com `DB_ALVO=local` e com os serviços `db` e `web` em execução.
Não acessam o Supabase nem o Render.

## Quando copiar

- **Ao fim de cada sessão de uso com alterações** (cadastros, documentos,
  lançamentos).
- **Antes de qualquer atualização:** `git pull`, `docker compose build`,
  `migrate` ou troca de versão do PostgreSQL.

Depois de copiar, **teste a restauração** e **leve a pasta para outro
dispositivo** (disco externo ou nuvem pessoal). A pasta `backups\` fica no
mesmo disco dos volumes do Docker. Sozinha, ela **não** é uma cópia
independente.

## 1. Fazer a cópia

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup\backup.ps1
# ou direto em outro dispositivo:
powershell -ExecutionPolicy Bypass -File scripts\backup\backup.ps1 -Destino E:\JusGestor\backups
```

O script cria uma pasta datada, por exemplo `backups\20261112-003601\`, com:

| Arquivo | Conteúdo |
|---|---|
| `banco.dump` | `pg_dump -Fc` do banco local (formato do `pg_restore`) |
| `documentos.tar.gz` | todos os arquivos do volume de documentos |
| `documentos.sha256` | SHA-256 de cada documento |
| `impressao_origem.txt` | contagem e hash de cada tabela, estrutura e órfãos, tirados no momento da cópia |
| `manifesto.txt` | data, versão do `pg_dump` e SHA-256 dos arquivos acima |

Como o script trabalha:
- O banco principal é apenas **lido**.
- A impressão digital é tirada antes e depois do `pg_dump`. Se algo mudar no
  meio, por exemplo alguém usando o sistema, a cópia é refeita (até 3 vezes).
- Os documentos são copiados depois do banco. Assim, todo arquivo citado no
  dump já existe, já que o sistema não apaga arquivos de versões.
- Se algo falhar, a pasta incompleta é apagada.

**A cópia contém dados pessoais e hashes de senha.** Guarde-a em local
protegido. `backups/` está no `.gitignore` e no `.dockerignore`.

## 2. Testar a restauração

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1
# ou uma cópia específica:
powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1 -Backup backups\20261112-003601
```

O teste **nunca** toca no banco principal. Ele cria uma rede Docker interna
(sem internet) e um contêiner PostgreSQL descartável, com a mesma imagem do
serviço `db`. Nesse contêiner, restaura e verifica:

1. o SHA-256 dos arquivos da cópia, conferido com o manifesto;
2. o `pg_restore --exit-on-error` e a extração dos documentos;
3. a contagem e o hash do conteúdo de **cada tabela**, comparados com a origem;
4. as restrições, os índices e as sequências, todas as restrições validadas e
   nenhum registro órfão em nenhuma chave estrangeira;
5. o SHA-256 de cada documento e a existência e o tamanho do arquivo de cada
   versão registrada no banco;
6. a leitura pelo Django, com a **versão do código compatível com o esquema
   da cópia**: o código atual, se as migrações do projeto registradas na cópia
   forem exatamente as do código, ou o commit mais recente cujas migrações
   correspondam (extraído do Git para uma pasta temporária). Exige 0 migrações
   pendentes (`showmigrations`) e contagens pelo ORM iguais às da origem.
   **Nenhuma migração é aplicada** no banco restaurado. O relatório informa as
   migrações do código atual que ainda não estão na cópia;
7. um **controle negativo**: altera de propósito um registro e um arquivo na
   cópia e exige que a verificação acuse a diferença.

No fim, o contêiner, a rede, o volume e a pasta temporária são removidos. A
cópia é apenas lida; o relatório fica em `backups\restauracoes\`. O código de
saída é 0 quando a restauração foi comprovada e 1 quando houve falha.

Observação sobre a ordenação (impressão digital): os hashes concatenam as
linhas em ordem, e a ordem de textos depende da collation do banco. O Supabase
usa uma collation da família C e o PostgreSQL do Docker usa `en_US.utf8`, que
ignora pontuação (`(10,` vem antes de `(2,`): o mesmo conteúdo gerava hashes
diferentes em tabelas com 10 ou mais linhas. Desde o formato 2 (linha
`formato|impressao|2|ordenacao=C`), toda ordenação de texto usa `COLLATE "C"`
e a impressão é idêntica em qualquer servidor. Cópias antigas (formato 1) são
conferidas com a ordenação padrão do servidor local e com `C`, e só passam se
**todas** as linhas corresponderem com uma delas.

Observação sobre as restrições: ao recriar um `CHECK (campo IN (...))` de
coluna `varchar`, o PostgreSQL devolve a regra com as conversões de tipo em
outra posição, mas com os mesmos valores. Por isso a comparação usa a
definição sem conversões `::varchar`/`::text` e sem parênteses (ver
`verificar_banco.sql`).

## 3. Restaurar de verdade (perda de dados)

> Procedimento **manual e destrutivo**: substitui o banco principal. Ele nunca
> foi executado sobre o banco do sistema. Os comandos dos passos 3 e 4 foram
> ensaiados em 12/11/2026 em contêineres e volume descartáveis, e o resultado
> foi idêntico à cópia. Siga na ordem.

1. Se o banco atual ainda abrir, faça uma cópia dele (`backup.ps1`).
2. Teste a cópia escolhida com `testar_restauracao.ps1`. Só continue se o
   resultado for OK.
3. Restaure o banco, trocando `<PASTA>` pela pasta da cópia:

   ```powershell
   docker compose stop web
   docker compose cp <PASTA>\banco.dump db:/tmp/restaurar.dump
   docker compose exec -T db sh -c 'dropdb -U $POSTGRES_USER --force $POSTGRES_DB && createdb -U $POSTGRES_USER $POSTGRES_DB && pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --no-owner --exit-on-error /tmp/restaurar.dump; rm -f /tmp/restaurar.dump'
   ```

4. Restaure os documentos. Os arquivos têm nomes únicos e são adicionados à
   pasta:

   ```powershell
   docker compose run --rm --no-deps -v "<PASTA>:/restaurar:ro" web tar -xzf /restaurar/documentos.tar.gz -C /data/documentos
   ```

5. Suba e confira:

   ```powershell
   docker compose start web
   docker compose run --rm web python manage.py verificar_banco
   ```

## 4. Documentos do sistema publicado (Supabase Storage)

No sistema publicado, os arquivos ficam no bucket privado do Supabase Storage
(`DOCUMENTOS_ARMAZENAMENTO=supabase`). **O backup do banco do Supabase não
inclui esses arquivos**: eles têm comandos próprios, que acessam o bucket
somente com `--remoto --confirmar <nome do bucket>` e usam as chaves S3 do
`.env` sem exibi-las.

| Comando | O que faz |
|---|---|
| `exportar_documentos` | Copia os arquivos do prefixo dos documentos para `backups/documentos/<origem>-<data>/`, com as **chaves originais** (iguais a `versao_documento.caminho_arquivo`). Somente leitura no bucket. Recusa pasta já usada. |
| `verificar_backup_documentos` | Confere o manifesto (que não pode ter sido alterado) e o tamanho e o SHA-256 de cada arquivo; aponta arquivos fora do manifesto. |
| `restaurar_documentos` | Verifica a cópia inteira e envia os arquivos **nos caminhos originais**. Arquivo já existente e idêntico é ignorado; **arquivo diferente nunca é sobrescrito** sem `--sobrescrever --confirmar-sobrescrita <bucket>`. Cada envio é relido e conferido. |
| `testar_backup_documentos` | Teste completo só com arquivos fictícios em `verificacao-backup/<id>/`: cria, exporta, verifica, restaura, testa conflito e sobrescrita autorizada, e remove apenas o que criou. |

Estrutura da cópia:

```
backups/documentos/supabase-AAAAMMDD-HHMMSS/
  arquivos/<documento>/<uuid>.<ext>   cópia de cada arquivo
  manifesto.json                      origem, prefixo, data; chave, tamanho e SHA-256 de cada arquivo
  manifesto.sha256                    mesma lista no formato do "sha256sum -c"
  manifesto.json.sha256               SHA-256 do próprio manifesto
```

### Backup real (não executado até a autorização)

Faça junto com o backup do banco do Supabase (para que arquivos e registros
correspondam ao mesmo momento) e evite envios de documentos durante a cópia:

```powershell
docker compose run --rm web python manage.py exportar_documentos --remoto --confirmar jusgestor-documentos
docker compose run --rm web python manage.py verificar_backup_documentos backups/documentos/<pasta-criada>
```

Depois, copie a pasta para **outro dispositivo** (cópia independente). Ela
contém documentos privados: `backups/` está no `.gitignore` e no
`.dockerignore`, mas o disco onde ela fica também precisa ser protegido.

### Restauração real

1. `verificar_backup_documentos <pasta>`: só continue se estiver íntegra.
2. Opcional e recomendado: ensaiar num prefixo isolado, sem tocar nos
   documentos:
   `restaurar_documentos <pasta> --remoto --confirmar jusgestor-documentos --prefixo-destino ensaio-restauracao`
   (e remover esse prefixo depois, pelo painel).
3. Restaurar nos caminhos originais (o prefixo do manifesto):
   `restaurar_documentos <pasta> --remoto --confirmar jusgestor-documentos`
4. Se houver **conflitos**, o comando para sem alterar nada nesses arquivos.
   Só use `--sobrescrever --confirmar-sobrescrita jusgestor-documentos` depois
   de decidir que a versão da cópia deve substituir a do bucket.

### Teste realizado

`testar_backup_documentos --remoto` executado com sucesso em 12/11/2026 no
bucket `jusgestor-documentos`, com 3 arquivos fictícios (PDF, PNG e DOCX) em
prefixo isolado: exportação, verificação, restauração com chaves originais,
proteção contra sobrescrita, sobrescrita autorizada e remoção dos 6 arquivos
criados pelo teste. Nenhum documento real foi listado, lido ou alterado.

## 5. Banco do sistema publicado (PostgreSQL do Supabase)

`scripts\backup\backup_supabase.ps1` executa o `pg_dump` num contêiner
PostgreSQL descartável (mesma imagem do serviço `db`), com as variáveis
`SUPABASE_DB_*` do `.env` lidas **dentro do contêiner**: as credenciais não
passam pela linha de comando nem aparecem na saída.

| Proteção | Como |
|---|---|
| Confirmação explícita | `-Projeto <referência>` precisa ser igual à referência em `SUPABASE_DB_USER` (`postgres.<referência>`) |
| Destino certo | `SUPABASE_DB_HOST` precisa ser `*.supabase.com` ou `*.supabase.co` |
| Conexão criptografada | `SUPABASE_DB_SSLMODE` precisa ser `require`, `verify-ca` ou `verify-full` (com certificado em `certs\`) |
| Somente leitura | impressão digital em `BEGIN ... READ ONLY`; `pg_dump` usa transação `REPEATABLE READ, READ ONLY`; nenhum comando de escrita |
| Cópia consistente | impressão digital antes e depois do dump (até 3 tentativas); o dump só é mantido se forem iguais |
| Escopo | somente o esquema `public` (tabelas do sistema), sem dono e sem privilégios (`--no-owner --no-privileges`) |
| Não sobrescrever | cada execução cria `backups\supabase\AAAAMMDD-HHMMSS\`; pasta existente é recusada; cópia incompleta é apagada |
| Privacidade | `backups\` no `.gitignore` e no `.dockerignore`; pasta restrita ao usuário atual (`icacls`); segredos mascarados na saída |
| Restauração | **somente** no PostgreSQL local descartável do `testar_restauracao.ps1`, em rede interna sem internet e com as variáveis do Supabase vazias |

Conteúdo da cópia: `banco.dump`, `impressao_origem.txt` e `manifesto.txt`
(origem, versões do servidor e do `pg_dump`, tabelas, registros e SHA-256).
Os arquivos dos documentos **não** estão no banco: use `exportar_documentos`
(seção 4) logo em seguida, para que banco e arquivos correspondam.

### Validar a rotina sem acessar o Supabase

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup\testar_rotina_backup_supabase.ps1
```

Executa as recusas de segurança, um **ensaio** do mesmo procedimento contra o
PostgreSQL local (`backup_supabase.ps1 -Ensaio`), a restauração na instância
descartável, a verificação de não sobrescrita e a recusa de uma cópia
adulterada. Validado em 12/11/2026.

### Primeiro backup real (aguarda autorização)

```powershell
# 1. banco (somente leitura no Supabase)
powershell -ExecutionPolicy Bypass -File scripts\backup\backup_supabase.ps1 -Projeto <referencia-do-projeto>
# 2. restaurar e conferir num PostgreSQL local descartável
powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1 -Backup backups\supabase\<pasta-criada>
# 3. documentos do Storage (seção 4)
docker compose run --rm web python manage.py exportar_documentos --remoto --confirmar jusgestor-documentos
docker compose run --rm web python manage.py verificar_backup_documentos backups/documentos/<pasta-criada>
```

Depois, copie as duas pastas para outro dispositivo.

Restaurar **no Supabase** não faz parte desta rotina: recuperar o sistema
publicado (por exemplo, num novo projeto Supabase) é um procedimento à parte,
a ser decidido e autorizado caso a caso. Nota técnica para esse caso: o dump
de um esquema traz `CREATE SCHEMA public`; restaure com uma lista sem esse item
(`pg_restore -l banco.dump | grep -v ' SCHEMA - public ' > itens.lista` e
`pg_restore -L itens.lista ...`), como faz `restaurar_teste.sh`.

## O que o RNF07 ainda depende de você

| Parte do RNF07 | Situação |
|---|---|
| Preservar integridade no banco | Restrições, FKs com `PROTECT` e transações no sistema; validadas também na cópia restaurada |
| Copiar banco **e documentos** (local) | `backup.ps1` |
| Copiar **documentos** do sistema publicado | `exportar_documentos --remoto` (pronto e testado; cópia real aguarda autorização) |
| Copiar o **banco** do sistema publicado (Supabase) | `backup_supabase.ps1` (pronto e validado por ensaio local; cópia real aguarda autorização) |
| Testar restauração | `testar_restauracao.ps1` (cópias local e do Supabase), `testar_rotina_backup_supabase.ps1` e `testar_backup_documentos --remoto` (arquivos) |
| Copiar **após sessões com alterações e antes de atualizações** | Rotina **manual**. Não há agendamento automático |
| Manter **cópia independente** | **Manual**: levar as pastas para outro dispositivo |
