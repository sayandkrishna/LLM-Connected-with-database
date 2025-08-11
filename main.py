from fastapi import FastAPI, HTTPException, status, Header, Depends
from pydantic import BaseModel
import pandas as pd
import psycopg2
from psycopg2 import sql
import json
import time
from typing import List, Dict, Optional
import hashlib
import os
import redis
from test import llmcall
import jwt
import datetime
import pytz
import re
# --- New Imports and Setup for .env file ---
from dotenv import load_dotenv
# Load environment variables from a .env file.
# This should be at the very top of your application.
load_dotenv()

# Create the FastAPI app instance
app = FastAPI()

# --- New Redis Cache Configuration ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
CACHE_EXPIRATION_SECONDS = int(os.getenv("CACHE_EXPIRATION_SECONDS", 3600))  # 1 hour default

# Setup Redis connection
try:
    cache_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    cache_client.ping()  # Check the connection
    print("✅ Successfully connected to Redis.")
except redis.exceptions.ConnectionError as e:
    print(f"⚠️ Could not connect to Redis: {e}. Caching will be disabled.")
    cache_client = None  # Disable caching if connection fails

# Default Database configuration (used for authentication and schema caching)
# Now loaded from environment variables
DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_DATABASE", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "port": int(os.getenv("DB_PORT", 5432))
}

# --- New JWT Configuration ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-that-you-should-change")
ALGORITHM = "HS256"
# Token expiration time in minutes
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# In-memory storage for simple token-based authentication
# user_tokens: dict[str, str] = {} # This is now deprecated and replaced by JWT

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
        # Connect to the main application DB to get the list of user's saved connections
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        
        # This query is already secure as it filters by user_id
        cur.execute("SELECT db_name FROM db_credentials WHERE user_id = %s", (user_id,))
        db_name_aliases = [row[0] for row in cur.fetchall()]
        
        for db_name_alias in db_name_aliases:
            # Here, we MUST pass the user_id to get the credentials securely
            # This prevents a user from accessing another user's DB even if they guess the alias
            db_config = get_user_db_credentials(cur, user_id, db_name_alias)
            if db_config:
                db_schemas = {}
                # This part is safe as it uses the securely retrieved db_config
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
# --- JWT Helper Functions ---

def create_access_token(data: dict):
    """Creates a JWT access token with an expiration time."""
    to_encode = data.copy()
    
    # Set the expiration time
    expire = datetime.datetime.now(pytz.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    
    # Encode the payload with the secret key and algorithm
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    """Verifies a JWT token and returns the payload if valid."""
    try:
        # Decode and verify the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_current_user_id(token: str = Header(None)):
    """Dependency to get the current user's ID from the JWT token."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token missing")

    payload = verify_token(token)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
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

# In main.py
from typing import List, Dict, Optional, Any

class QueryRequest(BaseModel):
    user_query: str
    conversation_history: Optional[List[Dict[str, Any]]] = None # Add this line

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
    # Initialize both conn and cur to None
    conn = None
    cur = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (request.username,))
        result = cur.fetchone()

        # This logic correctly checks the user and password
        if result and result[1] == hash_password(request.password):
            user_id = str(result[0])
            access_token = create_access_token(data={"user_id": user_id})
            return {
                "message": "Login successful",
                "user_id": user_id,
                "username": request.username,
                "access_token": access_token,
                "token_type": "bearer"
            }
        
        # If the if-condition is false, this 401 error is raised as intended
        raise HTTPException(status_code=401, detail="Invalid username or password")

    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly so FastAPI can handle them
        raise http_exc
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        # Securely close resources
        if cur:
            cur.close()
        if conn:
            conn.close()
@app.post("/save-db-config", tags=["Database Management"])
async def save_db_config(request: DbConfigRequest, user_id: str = Depends(get_current_user_id)):
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

@app.get("/list-dbs", tags=["Database Management"])
async def list_user_databases(user_id: str = Depends(get_current_user_id)):
    """Lists all connected database aliases and their configurations (excluding passwords) for the current user."""
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()

        databases = []
        
        # THIS IS THE KEY: The WHERE clause filters for the currently logged-in user.
        # This prevents User A from seeing databases saved by User B.
        cur.execute("SELECT db_name, db_host, db_database, db_user, db_port FROM db_credentials WHERE user_id = %s", (user_id,))
        
        for row in cur.fetchall():
            databases.append({
                "db_name": row[0],
                "config": {
                    "host": row[1],
                    "database": row[2],
                    "user": row[3],
                    "port": row[4]
                }
            })

        return {"databases": databases}
    except Exception as e:
        print(f"Error listing databases for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if conn:
            cur.close()
            conn.close()

@app.get("/list-tables/{db_name}", tags=["Database Management"])
async def list_db_tables(db_name: str, user_id: str = Depends(get_current_user_id)):
    creds_conn = None
    try:
        creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
        creds_cur = creds_conn.cursor()
        db_config = get_user_db_credentials(creds_cur, user_id, db_name)
        
        if not db_config:
            raise HTTPException(status_code=404, detail=f"Database configuration '{db_name}' not found or you do not have access.")
            
        table_names = get_all_table_names(db_config)
        return {"tables": table_names}
    except Exception as e:
        print(f"Error listing tables for db {db_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if creds_conn:
            creds_cur.close()
            creds_conn.close()
def is_list_tables_request(user_query: str) -> bool:
    """
    Detects if the user is asking for a list of tables.
    """
    query = user_query.lower().strip()
    # A set of trigger phrases to detect the user's intent
    triggers = [
        "list all tables",
        "show all tables",
        "list the tables",
        "show me the tables",
        "what tables are in",
        "which tables are available"
    ]
    return any(trigger in query for trigger in triggers)

@app.post("/ask", tags=["LLM Interaction"])
async def ask_llm(request: QueryRequest, user_id: str = Depends(get_current_user_id)):
    """
    Handles a user's query by routing all requests through the LLM for maximum
    flexibility and error correction, with an optimized caching layer.
    """
    # NOTE: The "is_list_tables_request" shortcut has been removed.
    # All queries will now go through the LLM.

    # 1. Create a cache key based on the user's query.
    user_query = request.user_query.lower().strip()
    content_hash = hashlib.sha256(user_query.encode('utf-8')).hexdigest()
    cache_key = f"query_cache:{user_id}:{content_hash}"
    
    # 2. Check the Redis cache first.
    if cache_client:
        cached_data = cache_client.get(cache_key)
        if cached_data:
            print(f"✅ Returning cached response for key: {cache_key}")
            cached_response = json.loads(cached_data)
            # Ensure cached responses for list_tables are handled
            if cached_response.get("action") == "list_tables":
                return cached_response
            cached_response["source"] = "cache"
            return cached_response

    print(f"🔍 No cache hit for key: {cache_key}. Processing new request via LLM.")
    
    # 3. Securely get schemas for the user's databases.
    all_user_schemas = get_all_user_db_schemas(user_id)
    if not all_user_schemas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No database connections found. Please add a database configuration first."
        )

    # 4. Call the LLM with the user query, schemas, and conversation history.
    try:
        llm_response_str = llmcall(
            request.user_query,
            all_user_schemas,
            request.conversation_history
        )
        llm_output = json.loads(llm_response_str)
    except Exception as e:
        print(f"Error calling LLM or parsing its response: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during LLM processing: {e}"
        )

    # 5. NEW: Intelligently process the LLM's response.
    # Case A: The LLM wants to list tables.
    if llm_output.get("action") == "list_tables":
        db_name = llm_output.get("db")
        if not db_name:
            raise HTTPException(status_code=400, detail="LLM chose to list tables but did not specify a database.")
        
        print(f"LLM decided to list tables for database: '{db_name}'")
        creds_conn = None
        try:
            creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
            creds_cur = creds_conn.cursor()
            db_config = get_user_db_credentials(creds_cur, user_id, db_name)
            
            if not db_config:
                raise HTTPException(status_code=404, detail=f"Database '{db_name}' not found or you lack access.")
            
            table_names = get_all_table_names(db_config)
            final_response = {
                "inferred_db_name": db_name,
                "action": "list_tables",
                "data": table_names,
                "source": "live_action"
            }
            # Cache this action's result
            if cache_client:
                cache_client.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(final_response))
            return final_response
        finally:
            if creds_conn:
                creds_conn.close()

    # Case B: The LLM generated a SQL query.
    elif "query" in llm_output:
        inferred_db_name = llm_output.get("db")
        inferred_table = llm_output.get("table")
        sql_query = ll_output.get("query")

        if not all([inferred_db_name, inferred_table, sql_query]):
            raise HTTPException(status_code=400, detail="LLM response for query is missing 'db', 'table', or 'query' key.")

        print(f"LLM inferred DB: {inferred_db_name}, Table: {inferred_table}, Generated SQL: {sql_query}")

        # Securely retrieve credentials for the specific user and inferred database.
        creds_conn = None
        try:
            creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
            current_db_config = get_user_db_credentials(creds_conn.cursor(), user_id, inferred_db_name)
        finally:
            if creds_conn:
                creds_conn.close()

        if not current_db_config:
            raise HTTPException(status_code=404, detail=f"Database configuration '{inferred_db_name}' not found or you do not have access.")

        # Execute the query.
        conn = None
        try:
            conn = get_db_connection(current_db_config)
            df = pd.read_sql(sql_query, conn)
            final_response = {
                "inferred_db_name": inferred_db_name,
                "inferred_table": inferred_table,
                "sql_query": sql_query,
                "rows_returned": len(df),
                "data": df.to_dict(orient="records"),
                "source": "live"
            }
            # Cache the query result
            if cache_client:
                cache_client.setex(cache_key, CACHE_EXPIRATION_SECONDS, json.dumps(final_response))
            return final_response
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"An error occurred during query execution: {e}")
        finally:
            if conn:
                conn.close()
    
    # Case C: The LLM response is unclear.
    else:
        raise HTTPException(status_code=400, detail=f"LLM returned an unrecognized response format: {llm_output}")
