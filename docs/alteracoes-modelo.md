# Alterações em relação ao modelo relacional do artigo

Referência: Figura 3 — Modelo Relacional, em
`docs/referencias/TCC TADS24 - GUSTAVO PINHEIRO.pdf`.

Este arquivo registra toda diferença entre o modelo do artigo e o banco
implementado, com o motivo de cada uma.

## Tabela `usuario` (fase 1)

| Coluna | Situação | Motivo |
|---|---|---|
| `id`, `nome`, `email`, `perfil`, `ativo`, `trocar_senha`, `criado_em` | Conforme a Figura 3 | — |
| `senha_hash` | Conforme a Figura 3 (`VARCHAR(255)`) | Guarda o hash gerado pelo Django (RNF02). No código, o campo se chama `password`, mas a coluna no banco se chama `senha_hash`. |
| `tentativas_falhas` `SMALLINT ≥ 0` | **Acrescentada** | RF01: contar falhas consecutivas de login. |
| `bloqueado_ate` `TIMESTAMP NULL` | **Acrescentada** | RF01: bloquear o login por 15 minutos após cinco falhas consecutivas. |
| `last_login` `TIMESTAMP NULL` | **Acrescentada** | Exigida pelo sistema de autenticação do Django (`AbstractBaseUser`). |

Restrições acrescentadas:

- `usuario_perfil_valido`: `perfil` só aceita `ADM`, `ADV` e `AST` (RN06).
- `usuario_email_unico_ci`: e-mail único sem diferenciar maiúsculas de
  minúsculas. Os e-mails são gravados em minúsculas.

Tabelas internas criadas pelo Django: `django_session`, `django_content_type`,
`django_migrations`, `auth_permission`, `auth_group` e
`auth_group_permissions`. Elas não fazem parte do modelo do negócio. O sistema
não usa grupos nem permissões do Django: os perfis seguem a coluna `perfil`.

## Campos esmaecidos na Figura 3 (mantidos por decisão do autor)

Três campos aparecem esmaecidos na figura. Todos foram implementados:

- `versao_documento.numero_versao`: versões de documento (RN04, RF06);
- `cobranca_hora.liberado_em`: liberação do vínculo ao cancelar a cobrança (RN10);
- `participante_compromisso.usuario_id`: participantes de compromissos (RF04).

## Tabelas dos módulos (primeira versão integrada)

As 11 tabelas restantes da Figura 3 foram criadas **com os mesmos nomes,
colunas e tipos**: `cliente`, `processo`, `acesso_cliente`,
`acesso_processo`, `compromisso`, `participante_compromisso`, `documento`,
`versao_documento`, `registro_hora`, `lancamento_financeiro` e
`cobranca_hora`. Não foi acrescentada nenhuma coluna.

`acesso_cliente`, `acesso_processo` e `participante_compromisso` usam chave
primária composta, como na figura (`CompositePrimaryKey` do Django 5.2).

### Valores permitidos (a figura indica só o tipo `VARCHAR`)

| Coluna | Valores | Origem |
|---|---|---|
| `processo.situacao` | `ativo`, `encerrado` | Telas (Fig. 4, 5). "Arquivado" usa a coluna `arquivado`. |
| `compromisso.tipo` | `compromisso`, `tarefa`, `prazo` | RF04 |
| `compromisso.situacao` | `pendente`, `concluido`, `cancelado` | RF04 |
| `lancamento_financeiro.tipo` | `receita`, `despesa` | RN03 |
| `lancamento_financeiro.situacao` | `pendente`, `quitado`, `cancelado` | RN03 |
| `versao_documento.extensao` | `pdf`, `docx`, `png`, `jpg`, `jpeg` | RN04 |

### Restrições acrescentadas no banco

| Restrição | Regra |
|---|---|
| `processo.numero` único (vários `NULL` permitidos) | RN01 |
| `cliente_cpf_cnpj_digitos`: 11 ou 14 dígitos, ou vazio | Integridade (o número é gravado sem formatação) |
| `documento_vinculado`: cliente ou processo obrigatório | RN04 |
| `versao_documento_numero_unico` (documento, versão) | RN04 |
| `versao_documento_tamanho_valido`: de 1 byte a 10 MiB | RN04 |
| `registro_hora_minutos_positivos` | RN05 |
| `lancamento_valor_positivo` | RN03 |
| `lancamento_data_quitacao_coerente`: data presente somente quando o lançamento está quitado | RN03 |
| `compromisso_fim_apos_inicio` | Integridade |
| `cobranca_hora_um_vinculo_ativo`: índice único parcial em `registro_hora_id` onde `liberado_em IS NULL` | RN10 |
| Situações e tipos limitados aos valores acima | RN02, RN03 |

As chaves estrangeiras usam `PROTECT`, que impede a exclusão física de
registros com vínculos (RN08). As de autorização e de participação usam
`CASCADE`, porque não guardam histórico.

## Decisões de interpretação (onde o artigo não detalha)

- **Visibilidade (RN07):**
  - ADM vê tudo.
  - ADV vê os processos de que é responsável ou que foram liberados para ele.
  - AST vê os clientes e processos liberados.
  - Acesso a um cliente não libera os processos dele.
  - Registro não autorizado responde 404.
- **Agenda:** o compromisso aparece para o responsável, para os participantes
  e para quem acessa o processo vinculado. Participar não dá acesso ao
  processo.
- **Documentos:** se o documento está ligado a um processo, exige acesso ao
  processo; se está ligado só ao cliente, exige acesso ao cliente.
- **Processos:** ADV que cadastra um processo fica como responsável; só o ADM
  altera o responsável.
- **Horas:** só o autor altera o próprio registro. Não há exclusão. Com
  cobrança ativa, a duração e o processo ficam bloqueados (RN10).
- **Financeiro:** pendente pode ir para quitado ou cancelado; quitado e
  cancelado são finais. Só lançamentos pendentes podem ser editados.
- **Exclusão:** nenhum módulo exclui registros. As lixeiras das telas viraram
  arquivar (clientes e processos), cancelar (agenda e financeiro) ou
  desativar (usuários).
