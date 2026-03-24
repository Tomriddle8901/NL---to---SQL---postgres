EXTENSION = pg_ai_query
MODULES = pg_ai_query
DATA = pg_ai_query--1.0.sql

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)