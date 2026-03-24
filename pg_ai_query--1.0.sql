CREATE FUNCTION hello_pg_ai()
RETURNS text
AS 'MODULE_PATHNAME', 'hello_pg_ai'
LANGUAGE C STRICT;

CREATE FUNCTION generate_ai_query(text)
RETURNS text
AS 'MODULE_PATHNAME', 'generate_ai_query'
LANGUAGE C STRICT;