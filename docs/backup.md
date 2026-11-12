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
6. a leitura pelo Django: `verificar_banco` sem migrações pendentes e as
   contagens pelo ORM iguais às da origem;
7. um **controle negativo**: altera de propósito um registro e um arquivo na
   cópia e exige que a verificação acuse a diferença.

No fim, o contêiner, a rede e o volume são removidos. O relatório fica em
`restauracao_<data>.txt`, dentro da pasta da cópia. O código de saída é 0
quando a restauração foi comprovada e 1 quando houve falha.

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

## O que o RNF07 ainda depende de você

| Parte do RNF07 | Situação |
|---|---|
| Preservar integridade no banco | Restrições, FKs com `PROTECT` e transações no sistema; validadas também na cópia restaurada |
| Copiar banco **e documentos** | `backup.ps1` |
| Testar restauração | `testar_restauracao.ps1` |
| Copiar **após sessões com alterações e antes de atualizações** | Rotina **manual**. Não há agendamento automático |
| Manter **cópia independente** | **Manual**: levar a pasta para outro dispositivo ou usar `-Destino` |

Fora do escopo local: o sistema publicado (Supabase e Render) tem
armazenamento e backups próprios, que não são cobertos por estes scripts. Os
documentos no Render ainda não têm armazenamento persistente.
