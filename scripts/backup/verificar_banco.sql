-- Impressão digital do banco, SOMENTE LEITURA (RNF07).
--
-- Usada para comparar o banco de origem (no momento do backup) com o banco
-- restaurado. Saída (psql -At): tipo|nome|quantidade|hash
-- Não exibe o conteúdo dos registros: apenas contagens e hashes MD5.
--
--   tabela      cada tabela do esquema public: nº de registros e hash do conteúdo
--   estrutura   restrições, índices, sequências e FKs não validadas
--   orfaos      registros que apontam para um pai inexistente, por chave estrangeira

\set ON_ERROR_STOP on
SET TimeZone = 'UTC';
SET DateStyle = 'ISO, YMD';
SET IntervalStyle = 'postgres';
SET extra_float_digits = 3;
SET bytea_output = 'hex';
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;

-- 1. Tabelas: contagem e hash de todas as linhas (ordenadas pelo texto da linha).
SELECT 'SELECT * FROM (' || string_agg(format(
         $f$SELECT 'tabela'::text AS tipo, %L::text AS nome, count(*)::text AS qtd, md5(coalesce(string_agg(t::text, E'\n' ORDER BY t::text), '')) AS hash FROM public.%I t$f$,
         tablename, tablename), ' UNION ALL ') || ') x ORDER BY nome'
FROM pg_tables
WHERE schemaname = 'public'
\gexec

-- 2. Estrutura.
-- Restrições: tabela, nome, tipo e definição normalizada. A normalização remove
-- conversões ::character varying / ::text e parênteses, porque o PostgreSQL, ao
-- recriar um CHECK (campo IN (...)) em coluna varchar a partir do pg_dump, devolve
-- a mesma regra com as conversões em outra posição:
--   origem:     ARRAY['a'::character varying, ...])::text[]
--   restaurado: ARRAY[('a'::character varying)::text, ...]
-- (mesmos valores permitidos). Nomes, colunas, valores e operadores continuam comparados.
SELECT 'estrutura', 'restricoes', count(*)::text,
       md5(coalesce(string_agg(conrelid::regclass::text || ' ' || conname || ' ' || contype::text || ' '
                               || regexp_replace(pg_get_constraintdef(oid), '::(character varying|text)(\[\])?|[()]', '', 'g'),
                               E'\n' ORDER BY conrelid::regclass::text, conname), ''))
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace;

SELECT 'estrutura', 'indices', count(*)::text,
       md5(coalesce(string_agg(indexdef, E'\n' ORDER BY indexname), ''))
FROM pg_indexes
WHERE schemaname = 'public';

SELECT 'estrutura', 'sequencias', count(*)::text,
       md5(coalesce(string_agg(sequencename || '=' || coalesce(last_value::text, '-'), E'\n' ORDER BY sequencename), ''))
FROM pg_sequences
WHERE schemaname = 'public';

-- Restrições (CHECK, FK, UNIQUE...) ainda não validadas contra os dados (esperado: 0).
SELECT 'estrutura', 'restricoes_nao_validadas', count(*)::text, '-'
FROM pg_constraint
WHERE NOT convalidated AND connamespace = 'public'::regnamespace;

-- 3. Relacionamentos: órfãos em cada chave estrangeira (esperado: 0 em todas).
SELECT coalesce('SELECT * FROM (' || string_agg(format(
         $f$SELECT 'orfaos'::text, %L::text, count(*)::text, '-'::text FROM %s f WHERE f.%I IS NOT NULL AND NOT EXISTS (SELECT 1 FROM %s p WHERE p.%I = f.%I)$f$,
         c.conname, c.conrelid::regclass, a.attname, c.confrelid::regclass, af.attname, a.attname), ' UNION ALL ') || ') x ORDER BY 2',
       $f$SELECT 'orfaos', '-', '0', '-'$f$)
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
WHERE c.contype = 'f'
  AND c.connamespace = 'public'::regnamespace
  AND array_length(c.conkey, 1) = 1
\gexec

COMMIT;
