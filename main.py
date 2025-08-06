from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
import pandas as pd
from test import llmcall

app = FastAPI()

DB_PATH = "employees.db"  # Your SQLite database file

class QueryRequest(BaseModel):
    user_query: str

@app.post("/ask")
def ask_llm(request: QueryRequest):
    #Get SQL query from LLM
    sql_query = llmcall(request.user_query)
    print(f"Generated SQL: {sql_query}")

    # Execute SQL on SQLite
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql(sql_query, conn)
    except Exception as e:
        conn.close()
        return {"error": str(e), "sql_query": sql_query}
    conn.close()

    # Return results as JSON
    return {
        "sql_query": sql_query,
        "rows_returned": len(df),
        "data": df.to_dict(orient="records")
    }
