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

Três campos aparecem esmaecidos na figura, mas serão implementados nas fases
correspondentes:

- `versao_documento.numero_versao`: versões de documento (RN04, RF06);
- `cobranca_hora.liberado_em`: liberação do vínculo ao cancelar a cobrança (RN10);
- `participante_compromisso.usuario_id`: participantes de compromissos (RF04).
