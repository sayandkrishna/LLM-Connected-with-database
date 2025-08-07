from fastapi import FastAPI, HTTPException, status, Header
from pydantic import BaseModel
import pandas as pd
import psycopg2
from psycopg2 import sql
import json
import time
from typing import List, Dict, Optional
import hashlib
import os
import requests
from test import llmcall

# --- New Imports and Setup for .env file ---
from dotenv import load_dotenv

# Load environment variables from a .env file.
# This should be at the very top of your application.
load_dotenv()

# Create the FastAPI app instance
app = FastAPI()

# Default Database configuration (used for authentication and schema caching)
# Now loaded from environment variables
DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_DATABASE", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "port": int(os.getenv("DB_PORT", 5432))
}

# In-memory storage for simple token-based authentication
user_tokens: dict[str, str] = {}

# --- Helper Functions ---

def setup_database_tables():
    """Create the necessary database tables if they don't exist."""
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        
        # Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create db_credentials table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS db_credentials (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                db_name VARCHAR(50) NOT NULL,
                db_host VARCHAR(255) NOT NULL,
                db_database VARCHAR(255) NOT NULL,
                db_user VARCHAR(255) NOT NULL,
                db_password VARCHAR(255) NOT NULL,
                db_port INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, db_name),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        
        conn.commit()
        print("Database tables created successfully")
    except psycopg2.Error as e:
        print(f"Database setup error: {e}")
        raise
    finally:
        if conn:
            cur.close()
            conn.close()

def hash_password(password: str) -> str:
    """Hashes a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection(db_config: Dict) -> psycopg2.extensions.connection:
    """Establishes a new database connection."""
    return psycopg2.connect(**db_config)

def get_all_table_names(db_config: Dict) -> list[str]:
    """Retrieves all public table names from a database."""
    conn = None
    table_names = []
    try:
        conn = get_db_connection(db_config)
        cur = conn.cursor()
        cur.execute(sql.SQL("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_catalog = %s
            AND table_schema = 'public';
        """), (db_config["database"],))
        table_names = [row[0] for row in cur.fetchall()]
    except psycopg2.Error as e:
        print(f"Database error during table name retrieval: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
    return table_names

def get_schema_for_table(db_config: Dict, table_name: str) -> list[dict]:
    """Retrieves schema information for a given table."""
    conn = None
    schema = []
    try:
        conn = get_db_connection(db_config)
        cur = conn.cursor()
        cur.execute(sql.SQL("""
            SELECT
                column_name, data_type, is_nullable, character_maximum_length, numeric_precision
            FROM information_schema.columns
            WHERE table_catalog = %s AND table_name = %s
            ORDER BY ordinal_position;
        """), (db_config["database"], table_name))
        rows = cur.fetchall()
        for row in rows:
            schema.append({
                "column_name": row[0],
                "data_type": row[1],
                "is_nullable": True if row[2] == 'YES' else False,
                "character_maximum_length": row[3],
                "numeric_precision": row[4]
            })
    except psycopg2.Error as e:
        print(f"Database error during schema retrieval for {table_name}: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
    return schema

def get_user_db_credentials(cur: psycopg2.extensions.cursor, user_id: str, db_name: str) -> Optional[Dict]:
    """Retrieves specific database credentials for a user and db_name using an existing cursor."""
    try:
        cur.execute(
            "SELECT db_host, db_database, db_user, db_password, db_port FROM db_credentials WHERE user_id = %s AND db_name = %s",
            (user_id, db_name)
        )
        creds = cur.fetchone()
        if creds:
            return {
                "host": creds[0],
                "database": creds[1],
                "user": creds[2],
                "password": creds[3],
                "port": creds[4]
            }
        return None
    except psycopg2.Error as e:
        print(f"Database error retrieving credentials for user {user_id}, db {db_name}: {e}")
        return None

def get_all_user_db_schemas(user_id: str) -> Dict:
    """Retrieves all database schemas for a given user's saved databases using a single connection."""
    all_schemas = {}
    conn = None
    try:
        # First, get the schemas for the default database
        default_db_schemas = {}
        table_names = get_all_table_names(DEFAULT_DB_CONFIG)
        for table_name in table_names:
            default_db_schemas[table_name] = get_schema_for_table(DEFAULT_DB_CONFIG, table_name)
        all_schemas[DEFAULT_DB_CONFIG["database"]] = default_db_schemas

        # Then, get schemas for all other saved databases using a single connection for efficiency
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT db_name FROM db_credentials WHERE user_id = %s", (user_id,))
        db_name_aliases = [row[0] for row in cur.fetchall()]
        
        for db_name_alias in db_name_aliases:
            db_config = get_user_db_credentials(cur, user_id, db_name_alias)
            if db_config:
                db_schemas = {}
                table_names = get_all_table_names(db_config)
                for table_name in table_names:
                    db_schemas[table_name] = get_schema_for_table(db_config, table_name)
                all_schemas[db_name_alias] = db_schemas
    
    except psycopg2.Error as e:
        print(f"Database error while retrieving schemas for user {user_id}: {e}")
        return {}
    except Exception as e:
        print(f"An unexpected error occurred while retrieving schemas: {e}")
        return {}
    finally:
        if conn:
            cur.close()
            conn.close()
    return all_schemas

def get_current_user_id(token: str):
    """Simple token validation to get the user ID."""
    user_id = user_tokens.get(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user_id

# --- FastAPI Models ---
class SignupRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class DbConfigRequest(BaseModel):
    db_name: str
    db_host: str
    db_database: str
    db_user: str
    db_password: str
    db_port: int

class QueryRequest(BaseModel):
    user_query: str

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Create database tables on application startup."""
    try:
        setup_database_tables()
        print("Application startup completed successfully")
    except Exception as e:
        print(f"Startup error: {e}")
        raise

# --- FastAPI Endpoints ---

@app.post("/signup", tags=["Authentication"])
async def signup(request: SignupRequest):
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        password_hash = hash_password(request.password)
        cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (request.username, password_hash))
        user_id = cur.fetchone()[0]
        conn.commit()
        return {"message": "User created successfully", "user_id": str(user_id)}
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    except Exception as e:
        print(f"Signup error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if conn:
            cur.close()
            conn.close()

@app.post("/login", tags=["Authentication"])
async def login(request: LoginRequest):
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (request.username,))
        result = cur.fetchone()
        if result and result[1] == hash_password(request.password):
            user_id = str(result[0])
            token = os.urandom(24).hex()
            user_tokens[token] = user_id
            return {"message": "Login successful", "user_id": user_id, "token": token}
        raise HTTPException(status_code=401, detail="Invalid username or password")
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if conn:
            cur.close()
            conn.close()

@app.post("/save-db-config", tags=["Database Management"])
async def save_db_config(request: DbConfigRequest, token: str = Header(...)):
    user_id = get_current_user_id(token)
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO db_credentials (user_id, db_name, db_host, db_database, db_user, db_password, db_port)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, db_name) DO UPDATE SET
            db_host = EXCLUDED.db_host,
            db_database = EXCLUDED.db_database,
            db_user = EXCLUDED.db_user,
            db_password = EXCLUDED.db_password,
            db_port = EXCLUDED.db_port;
        """, (user_id, request.db_name, request.db_host, request.db_database, request.db_user, request.db_password, request.db_port))
        conn.commit()
        return {"message": "Database credentials saved successfully"}
    except Exception as e:
        print(f"Error saving DB config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if conn:
            cur.close()
            conn.close()

@app.post("/ask", tags=["LLM Interaction"])
async def ask_llm(request: QueryRequest, token: str = Header(None)):
    user_id = get_current_user_id(token)
    
    # 1. Retrieve all known schemas for this user's databases
    print(f"Retrieving schemas for user: {user_id}")
    all_user_schemas = get_all_user_db_schemas(user_id)
    if not all_user_schemas:
        raise HTTPException(status_code=500, detail="No database schemas found for this user.")

    # 2. Call the LLM to generate SQL from the natural language query and schemas
    llm_response_str = ""
    try:
        # Pass the full schema dictionary to the LLM for context
        llm_response_str = llmcall(request.user_query, all_user_schemas)
        llm_output = json.loads(llm_response_str)
        inferred_db_name = llm_output.get("db")
        inferred_table = llm_output.get("table")
        sql_query = llm_output.get("query")

        if not inferred_db_name or not inferred_table or not sql_query:
            raise ValueError("LLM did not return a valid 'db', 'table', and 'query' in its JSON output.")

        print(f"LLM inferred DB: {inferred_db_name}, Table: {inferred_table}, Generated SQL: {sql_query}")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"LLM returned an invalid response. Error: {e}")
    except Exception as e:
        print(f"Error calling LLM: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during LLM processing: {e}")

    # 3. Validate the LLM's inference and get the correct database configuration
    current_db_config = {}
    if inferred_db_name == DEFAULT_DB_CONFIG["database"]:
        current_db_config = DEFAULT_DB_CONFIG
    else:
        # Here we need a new connection just for this specific database
        creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
        creds_cur = creds_conn.cursor()
        creds = get_user_db_credentials(creds_cur, user_id, inferred_db_name)
        creds_cur.close()
        creds_conn.close()
        
        if not creds:
            raise HTTPException(status_code=404, detail=f"Database configuration '{inferred_db_name}' not found for this user.")
        current_db_config = creds
    
    if inferred_table not in all_user_schemas.get(inferred_db_name, {}):
        raise HTTPException(status_code=400, detail=f"LLM inferred table '{inferred_table}' not found in the '{inferred_db_name}' database.")

    # 4. Execute the generated SQL query
    conn = None
    df = pd.DataFrame()
    try:
        # WARNING: DIRECTLY EXECUTING LLM-GENERATED SQL IS A MAJOR SECURITY RISK (SQL INJECTION).
        # A production application must include a robust validation and sanitization
        # layer to ensure the generated SQL is safe and does not contain malicious commands.
        # This implementation uses pandas.read_sql, which is safer than f-strings, but
        # still executes the query as a whole. A full solution would parse and validate
        # the query's structure, table names, and column names against a whitelist.
        conn = get_db_connection(current_db_config)
        df = pd.read_sql(sql_query, conn)
    except psycopg2.Error as e:
        print(f"Database execution error: {e}")
        raise HTTPException(status_code=400, detail=f"Database query failed. Please check the query syntax.")
    except Exception as e:
        print(f"Unexpected error during SQL execution: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during query execution: {e}")
    finally:
        if conn:
            conn.close()

    # 5. Return the query results to the user
    return {
        "inferred_db_name": inferred_db_name,
        "inferred_table": inferred_table,
        "sql_query": sql_query,
        "rows_returned": len(df),
        "data": df.to_dict(orient="records")
    }

