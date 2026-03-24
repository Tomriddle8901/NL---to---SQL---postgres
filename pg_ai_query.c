#include "postgres.h"
#include "fmgr.h"
#include "utils/builtins.h"
#include "executor/spi.h"
#include "lib/stringinfo.h"
#include <ctype.h>
#include <string.h>

PG_MODULE_MAGIC;

PG_FUNCTION_INFO_V1(hello_pg_ai);
PG_FUNCTION_INFO_V1(generate_ai_query);

static void
clean_input(const char *input, char *output, size_t output_size)
{
    size_t i = 0, j = 0;
    bool last_was_space = true;

    while (input[i] != '\0' && j < output_size - 1)
    {
        unsigned char ch = (unsigned char) input[i];

        if (isalnum(ch))
        {
            output[j++] = ch;
            last_was_space = false;
        }
        else if (isspace(ch))
        {
            if (!last_was_space)
            {
                output[j++] = ' ';
                last_was_space = true;
            }
        }
        else if (ch == ',' || ch == '.' || ch == '?' || ch == '-' || ch == '_')
        {
            if (!last_was_space && j < output_size - 1)
            {
                output[j++] = ch;
                last_was_space = false;
            }
        }

        i++;
    }

    if (j > 0 && output[j - 1] == ' ')
        j--;

    output[j] = '\0';
}

static void
append_json_escaped(StringInfo buf, const char *value)
{
    const char *p;

    appendStringInfoChar(buf, '"');

    for (p = value; *p != '\0'; p++)
    {
        switch (*p)
        {
            case '\\':
                appendStringInfoString(buf, "\\\\");
                break;
            case '"':
                appendStringInfoString(buf, "\\\"");
                break;
            case '\n':
                appendStringInfoString(buf, "\\n");
                break;
            case '\r':
                appendStringInfoString(buf, "\\r");
                break;
            case '\t':
                appendStringInfoString(buf, "\\t");
                break;
            default:
                appendStringInfoChar(buf, *p);
                break;
        }
    }

    appendStringInfoChar(buf, '"');
}

Datum
hello_pg_ai(PG_FUNCTION_ARGS)
{
    PG_RETURN_TEXT_P(cstring_to_text("Hello from pg_ai_query"));
}

Datum
generate_ai_query(PG_FUNCTION_ARGS)
{
    text *input_text = PG_GETARG_TEXT_PP(0);
    char *input_cstring = text_to_cstring(input_text);

    char cleaned_input[1024];
    char version_result[64];

    StringInfoData json;
    int ret;
    uint64 i;

    clean_input(input_cstring, cleaned_input, sizeof(cleaned_input));

    snprintf(version_result, sizeof(version_result), "%d.%d",
             PG_VERSION_NUM / 10000,
             (PG_VERSION_NUM / 100) % 100);

    initStringInfo(&json);

    appendStringInfoChar(&json, '{');

    appendStringInfoString(&json, "\"cleaned_input\":");
    append_json_escaped(&json, cleaned_input);
    appendStringInfoChar(&json, ',');

    appendStringInfoString(&json, "\"postgres_version\":");
    append_json_escaped(&json, version_result);
    appendStringInfoChar(&json, ',');

    if (SPI_connect() != SPI_OK_CONNECT)
        ereport(ERROR, (errmsg("SPI_connect failed")));

    /*
     * schema: { "table_name": ["col1", "col2"] }
     */
    appendStringInfoString(&json, "\"schema\":{");

    ret = SPI_execute(
        "SELECT c.table_name, c.column_name "
        "FROM information_schema.columns c "
        "JOIN information_schema.tables t "
        "  ON c.table_schema = t.table_schema "
        " AND c.table_name = t.table_name "
        "WHERE c.table_schema = 'public' "
        "  AND t.table_type = 'BASE TABLE' "
        "ORDER BY c.table_name, c.ordinal_position",
        true,
        0
    );

    if (ret != SPI_OK_SELECT)
    {
        SPI_finish();
        ereport(ERROR, (errmsg("Failed to fetch schema columns")));
    }

    {
        char *current_table = NULL;
        bool first_table = true;
        bool first_column = true;

        for (i = 0; i < SPI_processed; i++)
        {
            HeapTuple tuple = SPI_tuptable->vals[i];
            TupleDesc tupdesc = SPI_tuptable->tupdesc;
            char *table_name = SPI_getvalue(tuple, tupdesc, 1);
            char *column_name = SPI_getvalue(tuple, tupdesc, 2);

            if (table_name == NULL || column_name == NULL)
                continue;

            if (current_table == NULL || strcmp(current_table, table_name) != 0)
            {
                if (!first_table)
                    appendStringInfoChar(&json, ']');

                if (!first_table)
                    appendStringInfoChar(&json, ',');

                append_json_escaped(&json, table_name);
                appendStringInfoChar(&json, ':');
                appendStringInfoChar(&json, '[');

                current_table = pstrdup(table_name);
                first_table = false;
                first_column = true;
            }

            if (!first_column)
                appendStringInfoChar(&json, ',');

            append_json_escaped(&json, column_name);
            first_column = false;
        }

        if (!first_table)
            appendStringInfoChar(&json, ']');
    }

    appendStringInfoString(&json, "},");

    /*
     * primary_keys: { "table_name": ["pk1", "pk2"] }
     */
    appendStringInfoString(&json, "\"primary_keys\":{");

    ret = SPI_execute(
        "SELECT tc.table_name, kcu.column_name "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name "
        " AND tc.table_schema = kcu.table_schema "
        "WHERE tc.constraint_type = 'PRIMARY KEY' "
        "  AND tc.table_schema = 'public' "
        "ORDER BY tc.table_name, kcu.ordinal_position",
        true,
        0
    );

    if (ret != SPI_OK_SELECT)
    {
        SPI_finish();
        ereport(ERROR, (errmsg("Failed to fetch primary keys")));
    }

    {
        char *current_table = NULL;
        bool first_table = true;
        bool first_column = true;

        for (i = 0; i < SPI_processed; i++)
        {
            HeapTuple tuple = SPI_tuptable->vals[i];
            TupleDesc tupdesc = SPI_tuptable->tupdesc;
            char *table_name = SPI_getvalue(tuple, tupdesc, 1);
            char *column_name = SPI_getvalue(tuple, tupdesc, 2);

            if (table_name == NULL || column_name == NULL)
                continue;

            if (current_table == NULL || strcmp(current_table, table_name) != 0)
            {
                if (!first_table)
                    appendStringInfoChar(&json, ']');

                if (!first_table)
                    appendStringInfoChar(&json, ',');

                append_json_escaped(&json, table_name);
                appendStringInfoChar(&json, ':');
                appendStringInfoChar(&json, '[');

                current_table = pstrdup(table_name);
                first_table = false;
                first_column = true;
            }

            if (!first_column)
                appendStringInfoChar(&json, ',');

            append_json_escaped(&json, column_name);
            first_column = false;
        }

        if (!first_table)
            appendStringInfoChar(&json, ']');
    }

    appendStringInfoString(&json, "},");

    /*
     * relationships: ["orders.student_id -> students.id"]
     */
    appendStringInfoString(&json, "\"relationships\":[");

    ret = SPI_execute(
        "SELECT tc.table_name AS source_table, "
        "       kcu.column_name AS source_column, "
        "       ccu.table_name AS target_table, "
        "       ccu.column_name AS target_column "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name "
        " AND tc.table_schema = kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON ccu.constraint_name = tc.constraint_name "
        " AND ccu.table_schema = tc.table_schema "
        "WHERE tc.constraint_type = 'FOREIGN KEY' "
        "  AND tc.table_schema = 'public' "
        "ORDER BY tc.table_name, kcu.ordinal_position",
        true,
        0
    );

    if (ret != SPI_OK_SELECT)
    {
        SPI_finish();
        ereport(ERROR, (errmsg("Failed to fetch relationships")));
    }

    for (i = 0; i < SPI_processed; i++)
    {
        HeapTuple tuple = SPI_tuptable->vals[i];
        TupleDesc tupdesc = SPI_tuptable->tupdesc;
        char *source_table = SPI_getvalue(tuple, tupdesc, 1);
        char *source_column = SPI_getvalue(tuple, tupdesc, 2);
        char *target_table = SPI_getvalue(tuple, tupdesc, 3);
        char *target_column = SPI_getvalue(tuple, tupdesc, 4);
        char relation[512];

        if (source_table == NULL || source_column == NULL ||
            target_table == NULL || target_column == NULL)
            continue;

        if (i > 0)
            appendStringInfoChar(&json, ',');

        snprintf(relation, sizeof(relation),
                 "%s.%s -> %s.%s",
                 source_table, source_column, target_table, target_column);

        append_json_escaped(&json, relation);
    }

    appendStringInfoChar(&json, ']');

    SPI_finish();

    appendStringInfoChar(&json, '}');

    PG_RETURN_TEXT_P(cstring_to_text(json.data));
}