"""SQL tool for the Copilot: schema context for the LLM, a safety guard, and a safe runner.

question ──▶ (LLM writes SQL using the schema context) ──▶ is_safe_sql ──▶ run_sql ──▶ rows
"""
import datetime as dt
import decimal
import re

import mlflow
from mlflow.entities import SpanType

ALLOWED_SCHEMA = "gold"
EXCLUDED_TABLES = {"documents", "document_chunks"}   # text for RAG, not for SQL
MAX_ROWS = 200


# ------------------------------------------------------------------ schema context
def get_schema_context(spark, catalog: str, schema: str = ALLOWED_SCHEMA, max_values: int = 15) -> str:
    """Describe every gold table and column (with their Unity Catalog comments) as text for the LLM."""
    tables = spark.sql(f"""
        SELECT table_name, comment FROM {catalog}.information_schema.tables
        WHERE table_schema = '{schema}' ORDER BY table_name""").collect()
    cols = spark.sql(f"""
        SELECT table_name, column_name, data_type, comment FROM {catalog}.information_schema.columns
        WHERE table_schema = '{schema}' ORDER BY table_name, ordinal_position""").collect()

    by_table = {}
    for c in cols:
        by_table.setdefault(c.table_name, []).append(c)

    blocks = []
    for t in tables:
        if t.table_name in EXCLUDED_TABLES:
            continue
        columns = by_table.get(t.table_name, [])
        values = _categorical_values(spark, f"{schema}.{t.table_name}", columns, max_values)
        lines = [f"TABLE {schema}.{t.table_name}" + (f"  -- {t.comment}" if t.comment else "")]
        for c in columns:
            line = f"  {c.column_name} {c.data_type}"
            if c.comment:
                line += f"  -- {c.comment}"
            if c.column_name in values:
                line += f"  [values: {', '.join(values[c.column_name])}]"
            lines.append(line)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _categorical_values(spark, table: str, columns, max_values: int) -> dict:
    """For short text columns (depot, model, status...) list the real values, so the LLM doesn't guess."""
    text_cols = [c.column_name for c in columns if c.data_type.upper() == "STRING"]
    if not text_cols:
        return {}
    # 1st query: how many distinct values does each text column have?
    counts = spark.sql("SELECT " + ", ".join(f"approx_count_distinct(`{c}`) AS `{c}`" for c in text_cols)
                       + f" FROM {table}").first().asDict()
    small = [c for c in text_cols if counts[c] <= max_values]
    if not small:
        return {}
    # 2nd query: collect the values, only for the low-cardinality columns
    row = spark.sql("SELECT " + ", ".join(f"collect_set(`{c}`) AS `{c}`" for c in small)
                    + f" FROM {table}").first().asDict()
    return {c: sorted(str(v) for v in row[c]) for c in small}


# ------------------------------------------------------------------ safety guard
_FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|"
                        r"optimize|vacuum|call|refresh|msck|restore|clone)\b", re.I)
_OTHER_SCHEMAS = re.compile(r"\b(eval|bronze|silver|system|information_schema)\s*\.", re.I)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([`\w.]+)", re.I)


def is_safe_sql(sql: str):
    """Return (ok, reason). Only a single read-only SELECT over gold tables passes."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    if ";" in s:
        return False, "multiple statements are not allowed"
    if not re.match(r"^(select|with)\b", s, re.I):
        return False, "only SELECT queries are allowed"
    m = _FORBIDDEN.search(s)
    if m:
        return False, f"forbidden keyword: {m.group(1).upper()}"
    m = _OTHER_SCHEMAS.search(s)
    if m:
        return False, f"only gold tables may be queried (found {m.group(1)})"
    for ref in _TABLE_REF.findall(s):
        parts = ref.replace("`", "").lower().split(".")
        if len(parts) == 1:
            continue          # CTE name, or a column in EXTRACT(MONTH FROM col)
        if parts[-2] != ALLOWED_SCHEMA or parts[-1] in EXCLUDED_TABLES:
            return False, f"table not allowed: {ref}"
    return True, "ok"


# ------------------------------------------------------------------ runner
def run_sql(spark, sql: str, max_rows: int = MAX_ROWS) -> dict:
    """Check, run, and return rows as plain Python (never raises: errors come back as text)."""
    with mlflow.start_span(name="run_sql", span_type=SpanType.TOOL) as span:
        span.set_inputs({"sql": sql, "max_rows": max_rows})
        result = _run(spark, sql, max_rows)
        span.set_outputs({k: result[k] for k in ("ok", "row_count", "truncated", "error") if k in result})
        return result


def _run(spark, sql: str, max_rows: int) -> dict:
    ok, reason = is_safe_sql(sql)
    if not ok:
        return {"ok": False, "sql": sql, "error": f"Blocked: {reason}"}
    try:
        df = spark.sql(sql.strip().rstrip(";"))
        rows = df.limit(max_rows + 1).collect()      # one extra row tells us if we cut anything off
    except Exception as e:
        return {"ok": False, "sql": sql, "error": str(e).split("\n")[0][:500]}
    return {"ok": True, "sql": sql, "columns": df.columns,
            "rows": [_jsonable(r.asDict()) for r in rows[:max_rows]],
            "row_count": min(len(rows), max_rows),
            "truncated": len(rows) > max_rows}


def _jsonable(d: dict) -> dict:
    """Dates, decimals and arrays -> plain types the LLM (and JSON) can read."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (dt.date, dt.datetime)):
            v = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            v = float(v)
        elif isinstance(v, list):
            v = [x if isinstance(x, (int, float, str, type(None))) else str(x) for x in v]
        out[k] = v
    return out

# ------------------------------------------------------------------ LLM: question -> SQL
SQL_SYSTEM_PROMPT = """You write Databricks SQL (Spark SQL) for a truck fleet operations assistant.

Rules:
- Use ONLY the tables and columns in the schema below. Always write tables as gold.<table_name>.
- Write ONE read-only SELECT query (WITH/CTEs allowed). Never modify data.
- Trucks are identified by unit_no, e.g. 'GOT-028'. Use the exact values shown in [values: ...].
- For "status", "right now" or "needs attention" questions, prefer gold.vehicle_current_status.
- local_date and month are DATE columns (month = first day of the month). Timestamps are UTC.
- Costs are in each depot's currency: never add EUR and USD together; group by currency.
- For rankings add ORDER BY, and LIMIT 50 unless the user asks for everything.
- If the question cannot be answered from these tables, return exactly: CANNOT_ANSWER
Return only the SQL. No explanation, no markdown.

Business glossary:
- Depot codes: GOT = Gothenburg, HAM = Hamburg, RTM = Rotterdam, CHI = Chicago.
- "Fuel consumption" / "fuel use" = l_per_100km (litres per 100 km).
- "Peers" = trucks of the same model and duty cycle in the same month.

Schema:
{schema}"""

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)


def generate_sql(question: str, schema_context: str, client, model: str = "gpt-4o-mini",
                 previous_sql: str = None, error: str = None) -> str:
    """Ask the LLM for SQL. If a previous attempt failed, show it the SQL and the error to fix."""
    messages = [{"role": "system", "content": SQL_SYSTEM_PROMPT.format(schema=schema_context)},
                {"role": "user", "content": question}]
    if previous_sql and error:
        messages += [{"role": "assistant", "content": previous_sql},
                     {"role": "user", "content": f"That query failed with: {error}\nFix it. Return only the SQL."}]
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
    text = resp.choices[0].message.content.strip()
    m = _FENCE.search(text)                      # in case the model wraps it in ```sql ... ```
    return (m.group(1) if m else text).strip().rstrip(";")


def ask_sql(question: str, spark, client, schema_context: str, model: str = "gpt-4o-mini",
            max_attempts: int = 2) -> dict:
    """Question -> SQL -> rows, retrying once with the error message if the SQL fails."""
    with mlflow.start_span(name="ask_sql", span_type=SpanType.CHAIN) as span:
        span.set_inputs({"question": question, "model": model})
        sql, error, result = None, None, {}
        for attempt in range(1, max_attempts + 1):
            sql = generate_sql(question, schema_context, client, model, previous_sql=sql, error=error)
            if sql.strip().upper() == "CANNOT_ANSWER":
                result = {"ok": False, "sql": None, "error": "The fleet tables cannot answer this question.",
                          "cannot_answer": True}
                break
            result = run_sql(spark, sql)
            if result["ok"]:
                break
            error = result["error"]
        result.update({"question": question, "attempts": attempt})
        span.set_outputs({k: result.get(k) for k in ("ok", "sql", "row_count", "attempts", "error")})
        return result