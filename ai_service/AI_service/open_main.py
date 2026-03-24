from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, List, Set
from google import genai
from version_docs import build_version_prompt_block, validate_version_rules
import os
import re


app = FastAPI()


class QueryInput(BaseModel):
    cleaned_input: str
    postgres_version: str
    schema: Dict[str, List[str]]
    primary_keys: Dict[str, List[str]]
    relationships: List[str]


class QueryResponse(BaseModel):
    sql: str
    explanation: str
    model_used: str
    status: str


def normalize_natural_language(text: str) -> str:
    text = text.strip()

    replacements = {
        r"\bgive me\b": "show",
        r"\bshow me\b": "show",
        r"\bi want\b": "show",
        r"\bi need\b": "show",

        r"\bbelongs to gender as\b": "gender is",
        r"\bbelongs to gender\b": "gender is",
        r"\bwith gender as\b": "gender is",

        r"\bmore than\b": "greater than",
        r"\bstarting from\b": "starts with",
        r"\bstarts from\b": "starts with",
        r"\bending with\b": "ends with",
        r"\bends from\b": "ends with",

        r"\bhaving\b": "with",
    }

    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return " ".join(text.split())


def format_schema(schema: Dict[str, List[str]]) -> str:
    return "\n".join(f"{table}({', '.join(columns)})" for table, columns in schema.items())


def format_primary_keys(primary_keys: Dict[str, List[str]]) -> str:
    if not primary_keys:
        return "None"
    return "\n".join(f"{table}: {', '.join(keys)}" for table, keys in primary_keys.items())


def format_relationships(relationships: List[str]) -> str:
    return "\n".join(relationships) if relationships else "None"


def build_prompt(data: QueryInput) -> str:
    version_block = build_version_prompt_block(data.postgres_version)

    return f"""
You are an expert NL-to-SQL assistant for PostgreSQL.

Task:
Convert the user's natural-language request into a valid PostgreSQL SQL query.

User Request:
{data.cleaned_input}

PostgreSQL Version:
{data.postgres_version}

Schema:
{format_schema(data.schema)}

Primary Keys:
{format_primary_keys(data.primary_keys)}

Relationships:
{format_relationships(data.relationships)}

{version_block}

Strict Rules:
1. Output ONLY SQL query text
2. Do not add markdown, comments, or explanation
3. Always end the query with a semicolon
4. Use only the tables and columns provided in the schema
5. Do not hallucinate tables, columns, primary keys, or joins
6. If a required relationship is missing, do not assume it
7. If the schema is insufficient to answer safely, return exactly:
   SELECT 'Unable to generate query';
8. Use valid PostgreSQL syntax only
9. Do not include comments such as '-- assuming'
10. If the request requires a join but no relationship is provided, return:
    SELECT 'Unable to generate query';

Examples:
Input: show all students
Output: SELECT * FROM students;

Input: show orders with price greater than 5000
Output: SELECT * FROM orders WHERE price > 5000;

Input: show students whose name starts with A
Output: SELECT * FROM students WHERE name LIKE 'A%';

Input: show name of students whose name ends with x and gender is male
Output: SELECT name FROM students WHERE name LIKE '%x' AND gender = 'male';

Input: show students whose name starts with A and with orders of greater than 5000
If no relationship exists between students and orders, output:
SELECT 'Unable to generate query';

Now generate SQL:
""".strip()


def extract_sql_only(text: str) -> str:
    text = text.strip()
    text = text.replace("```sql", "").replace("```", "").strip()

    lowered = text.lower()
    if "assuming" in lowered or "--" in text or "/*" in text or "*/" in text:
        return "SELECT 'Unable to generate query';"

    match = re.search(r"\b(select|insert|update|delete)\b", text, re.IGNORECASE)
    if not match:
        return "SELECT 'Unable to generate query';"

    sql = text[match.start():].strip()

    if ";" in sql:
        sql = sql.split(";", 1)[0].strip() + ";"
    else:
        sql = sql.strip() + ";"

    return sql


def fallback_sql_logic() -> tuple[str, str]:
    return (
        "SELECT 'Unable to generate query';",
        "Gemini key missing or generation fallback triggered."
    )


def generate_sql_with_llm(data: QueryInput) -> tuple[str, str, str]:
    api_key = os.getenv("GEMINI_API_KEY")

    normalized_input = normalize_natural_language(data.cleaned_input)
    normalized_data = QueryInput(
        cleaned_input=normalized_input,
        postgres_version=data.postgres_version,
        schema=data.schema,
        primary_keys=data.primary_keys,
        relationships=data.relationships
    )

    if not api_key:
        sql, explanation = fallback_sql_logic()
        return sql, explanation, "fallback-engine"

    try:
        client = genai.Client(api_key=api_key)
        prompt = build_prompt(normalized_data)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        raw_output = (response.text or "").strip()
        cleaned_sql = extract_sql_only(raw_output)

        return (
            cleaned_sql,
            f"Generated using Gemini | normalized_input: {normalized_input}",
            "gemini-2.5-flash"
        )
    except Exception as e:
        return (
            "SELECT 'Unable to generate query';",
            f"LLM generation failed: {str(e)}",
            "llm-error-handler"
        )


def validate_sql_basic(sql: str) -> tuple[bool, str]:
    sql_lower = sql.lower().strip()

    if not sql_lower:
        return False, "Empty SQL generated."

    allowed_starts = ("select", "insert", "update", "delete")
    if not sql_lower.startswith(allowed_starts):
        return False, "Generated output is not a supported SQL statement."

    blocked = ["drop ", "alter ", "truncate ", "grant ", "revoke "]
    for keyword in blocked:
        if keyword in sql_lower:
            return False, f"Blocked unsupported SQL command: {keyword.strip()}"

    if "--" in sql or "/*" in sql or "*/" in sql:
        return False, "Comments are not allowed in SQL output."

    return True, "SQL passed basic validation."


def extract_tables_from_sql(sql: str) -> Set[str]:
    tables = set()

    patterns = [
        r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"\bjoin\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"\bupdate\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"\binto\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"\bdelete\s+from\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, sql, flags=re.IGNORECASE)
        for match in matches:
            tables.add(match.lower())

    return tables


def extract_selected_columns(sql: str) -> List[str]:
    match = re.search(r"\bselect\s+(.*?)\s+\bfrom\b", sql, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []

    column_part = match.group(1).strip()

    if column_part == "*":
        return ["*"]

    columns = []
    for col in column_part.split(","):
        col = col.strip()
        col = re.sub(r"\s+as\s+[a-zA-Z_][a-zA-Z0-9_]*", "", col, flags=re.IGNORECASE)

        if "." in col:
            col = col.split(".")[-1]

        func_match = re.match(r"[a-zA-Z_][a-zA-Z0-9_]*\((.*?)\)", col)
        if func_match:
            inner = func_match.group(1).strip()
            if "." in inner:
                inner = inner.split(".")[-1]
            col = inner

        columns.append(col)

    return columns


def extract_where_columns(sql: str) -> List[str]:
    columns = []

    where_match = re.search(
        r"\bwhere\s+(.*?)(\bgroup\b|\border\b|\bhaving\b|;|$)",
        sql,
        flags=re.IGNORECASE | re.DOTALL
    )
    if not where_match:
        return columns

    where_part = where_match.group(1)

    patterns = [
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s*=",
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s*>",
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s*<",
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s+like\b",
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s+between\b",
        r"([a-zA-Z_][a-zA-Z0-9_\.]*)\s+in\b",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, where_part, flags=re.IGNORECASE)
        for match in matches:
            if "." in match:
                match = match.split(".")[-1]
            columns.append(match)

    return columns


def validate_tables_exist(sql: str, schema: Dict[str, List[str]]) -> tuple[bool, str]:
    sql_tables = extract_tables_from_sql(sql)
    schema_tables = {table.lower() for table in schema.keys()}

    for table in sql_tables:
        if table not in schema_tables:
            return False, f"Invalid table detected: {table}"

    return True, "All tables are valid."


def validate_columns_exist(sql: str, schema: Dict[str, List[str]]) -> tuple[bool, str]:
    sql_tables = extract_tables_from_sql(sql)

    if len(sql_tables) != 1:
        return True, "Column validation skipped for multi-table query."

    table = next(iter(sql_tables))
    schema_columns = {col.lower() for col in schema.get(table, [])}

    all_columns = extract_selected_columns(sql) + extract_where_columns(sql)

    for col in all_columns:
        if col == "*":
            continue
        if col.lower() not in schema_columns:
            return False, f"Invalid column '{col}' for table '{table}'."

    return True, "All columns are valid."


def validate_full_sql(sql: str, data: QueryInput) -> tuple[bool, str]:
    is_valid_basic, basic_msg = validate_sql_basic(sql)
    if not is_valid_basic:
        return False, basic_msg

    is_valid_version, version_msg = validate_version_rules(sql, data.postgres_version)
    if not is_valid_version:
        return False, version_msg

    is_valid_tables, table_msg = validate_tables_exist(sql, data.schema)
    if not is_valid_tables:
        return False, table_msg

    is_valid_columns, column_msg = validate_columns_exist(sql, data.schema)
    if not is_valid_columns:
        return False, column_msg

    return True, "SQL passed full validation."


@app.post("/generate-sql", response_model=QueryResponse)
def generate_sql(data: QueryInput):
    try:
        sql, explanation, model_used = generate_sql_with_llm(data)

        is_valid, validation_msg = validate_full_sql(sql, data)
        if not is_valid:
            return QueryResponse(
                sql="SELECT 'Unable to generate query';",
                explanation=validation_msg,
                model_used="validation-layer",
                status="blocked"
            )

        return QueryResponse(
            sql=sql,
            explanation=explanation,
            model_used=model_used,
            status="success"
        )
    except Exception as e:
        return QueryResponse(
            sql="SELECT 'Unable to generate query';",
            explanation=f"Internal processing error: {str(e)}",
            model_used="endpoint-error-handler",
            status="blocked"
        )