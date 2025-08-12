from fastapi import FastAPI, HTTPException, status, Header, Depends
from pydantic import BaseModel
import pandas as pd
import psycopg2
from psycopg2 import sql
import json
import time
from typing import List, Dict, Optional, Tuple, Any
import hashlib
import os
import redis
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import re
from test import llmcall
import jwt
import datetime
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create the FastAPI app instance
app = FastAPI()

# --- Enhanced Cache Configuration ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
CACHE_EXPIRATION_SECONDS = int(os.getenv("CACHE_EXPIRATION_SECONDS", 3600))  # 1 hour default
SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_SIMILARITY_THRESHOLD", 0.8))
INTENT_CONFIDENCE_THRESHOLD = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", 0.7))

# Setup Redis connection
try:
    cache_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    cache_client.ping()
    print("✅ Successfully connected to Redis.")
except redis.exceptions.ConnectionError as e:
    print(f"⚠️ Could not connect to Redis: {e}. Caching will be disabled.")
    cache_client = None

# --- Embedding Model Setup ---
print("🔄 Loading sentence transformer model...")
try:
    embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    print("✅ Embedding model loaded successfully.")
except Exception as e:
    print(f"⚠️ Failed to load embedding model: {e}")
    embedding_model = None

# Database configuration
DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_DATABASE", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "port": int(os.getenv("DB_PORT", 5432))
}

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-that-you-should-change")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# --- Enhanced Cache Classes ---
class SemanticCacheEntry(BaseModel):
    query: str
    embedding: List[float]
    response: Dict[str, Any]
    timestamp: float
    user_id: str
    hit_count: int = 1

class IntentPattern(BaseModel):
    pattern: str
    table_hint: str
    sql_template: str
    confidence_score: float

# --- Intent Detection Patterns ---
INTENT_PATTERNS = [
    IntentPattern(
        pattern=r"show\s+(?:all\s+)?(?:records?|rows?|data)\s+from\s+(\w+)",
        table_hint=r"\1",
        sql_template="SELECT * FROM {table} LIMIT 100;",
        confidence_score=0.9
    ),
    IntentPattern(
        pattern=r"count\s+(?:records?|rows?)\s+in\s+(\w+)",
        table_hint=r"\1",
        sql_template="SELECT COUNT(*) as count FROM {table};",
        confidence_score=0.9
    ),
    IntentPattern(
        pattern=r"list\s+(?:all\s+)?(?:tables?|schemas?)",
        table_hint="",
        sql_template="LIST_TABLES",
        confidence_score=0.95
    ),
    IntentPattern(
        pattern=r"(?:find|search|get)\s+(\w+)\s+where\s+(\w+)\s*=\s*['\"]?([^'\"]+)['\"]?",
        table_hint=r"\1",
        sql_template="SELECT * FROM {table} WHERE {column} = '{value}' LIMIT 50;",
        confidence_score=0.8
    ),
    IntentPattern(
        pattern=r"(?:top|first)\s+(\d+)\s+(?:records?|rows?)\s+from\s+(\w+)",
        table_hint=r"\2",
        sql_template="SELECT * FROM {table} LIMIT {limit};",
        confidence_score=0.85
    )
]

# --- Helper Functions (keeping existing ones) ---
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
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection(db_config: Dict) -> psycopg2.extensions.connection:
    return psycopg2.connect(**db_config)

def get_all_table_names(db_config: Dict) -> list[str]:
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
    all_schemas = {}
    conn = None
    try:
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

# --- New Semantic Cache Functions ---

def get_query_embedding(query: str) -> Optional[np.ndarray]:
    """Generate embedding for a query using the sentence transformer model."""
    if not embedding_model:
        return None
    try:
        embedding = embedding_model.encode([query.lower().strip()])[0]
        return embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def store_semantic_cache(user_id: str, query: str, embedding: np.ndarray, response: Dict[str, Any]):
    """Store query-response pair with embedding in Redis."""
    if not cache_client:
        return
    
    try:
        cache_entry = SemanticCacheEntry(
            query=query,
            embedding=embedding.tolist(),
            response=response,
            timestamp=time.time(),
            user_id=user_id
        )
        
        # Store with a unique key
        cache_key = f"semantic_cache:{user_id}:{hashlib.sha256(query.encode()).hexdigest()[:16]}"
        cache_client.setex(
            cache_key, 
            CACHE_EXPIRATION_SECONDS, 
            cache_entry.json()
        )
        
        # Also add to a user's cache index for retrieval
        index_key = f"semantic_index:{user_id}"
        cache_client.sadd(index_key, cache_key)
        cache_client.expire(index_key, CACHE_EXPIRATION_SECONDS)
        
        print(f"✅ Stored semantic cache entry: {cache_key}")
    except Exception as e:
        print(f"Error storing semantic cache: {e}")

def find_similar_cached_query(user_id: str, query: str, query_embedding: np.ndarray) -> Optional[Dict[str, Any]]:
    """Find semantically similar cached queries using vector similarity."""
    if not cache_client:
        return None
        
    try:
        index_key = f"semantic_index:{user_id}"
        cached_keys = cache_client.smembers(index_key)
        
        if not cached_keys:
            return None
        
        best_match = None
        best_similarity = 0
        
        for cache_key in cached_keys:
            try:
                cached_data = cache_client.get(cache_key)
                if not cached_data:
                    continue
                    
                cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                cached_embedding = np.array(cache_entry.embedding).reshape(1, -1)
                current_embedding = query_embedding.reshape(1, -1)
                
                similarity = cosine_similarity(current_embedding, cached_embedding)[0][0]
                
                if similarity > best_similarity and similarity > SEMANTIC_SIMILARITY_THRESHOLD:
                    best_similarity = similarity
                    best_match = {
                        "response": cache_entry.response,
                        "similarity": similarity,
                        "original_query": cache_entry.query,
                        "cache_key": cache_key
                    }
                    
            except Exception as e:
                print(f"Error processing cached entry {cache_key}: {e}")
                continue
        
        if best_match:
            print(f"🎯 Found similar query (similarity: {best_match['similarity']:.3f})")
            print(f"   Original: {best_match['original_query']}")
            print(f"   Current:  {query}")
            
            # Update hit count
            try:
                cached_data = cache_client.get(best_match['cache_key'])
                cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                cache_entry.hit_count += 1
                cache_client.setex(
                    best_match['cache_key'], 
                    CACHE_EXPIRATION_SECONDS, 
                    cache_entry.json()
                )
            except:
                pass
                
        return best_match
        
    except Exception as e:
        print(f"Error finding similar cached query: {e}")
        return None

def detect_intent_with_patterns(query: str, all_schemas: Dict) -> Optional[Dict[str, Any]]:
    """Use pattern matching for quick intent detection."""
    query_lower = query.lower().strip()
    
    # Get all available tables for context
    all_tables = []
    for db_name, tables in all_schemas.items():
        all_tables.extend([(db_name, table_name, columns) for table_name, columns in tables.items()])
    
    for pattern in INTENT_PATTERNS:
        match = re.search(pattern.pattern, query_lower, re.IGNORECASE)
        if match:
            print(f"🔍 Pattern matched: {pattern.pattern}")
            
            # Special case for list tables
            if pattern.sql_template == "LIST_TABLES":
                # Try to infer which database they want
                db_name = None
                for db in all_schemas.keys():
                    if db.lower() in query_lower:
                        db_name = db
                        break
                if not db_name and all_schemas:
                    db_name = list(all_schemas.keys())[0]  # Default to first DB
                
                return {
                    "action": "list_tables",
                    "db": db_name,
                    "confidence": pattern.confidence_score,
                    "source": "intent_detection"
                }
            
            # For SQL queries, try to match table names
            table_hint = pattern.table_hint
            if table_hint and match.groups():
                # Replace regex groups in table hint
                for i, group in enumerate(match.groups(), 1):
                    table_hint = table_hint.replace(f"\\{i}", group)
            
            # Find matching table
            matched_table = None
            matched_db = None
            for db_name, table_name, columns in all_tables:
                if table_hint.lower() in table_name.lower() or table_name.lower() in table_hint.lower():
                    matched_table = table_name
                    matched_db = db_name
                    break
            
            if matched_table and matched_db:
                # Build SQL from template
                sql_query = pattern.sql_template.format(
                    table=matched_table,
                    column=match.group(2) if len(match.groups()) >= 2 else "id",
                    value=match.group(3) if len(match.groups()) >= 3 else "",
                    limit=match.group(1) if pattern.pattern.startswith(r"(?:top|first)") else "100"
                )
                
                return {
                    "db": matched_db,
                    "table": matched_table,
                    "query": sql_query,
                    "confidence": pattern.confidence_score,
                    "source": "intent_detection"
                }
    
    return None

# --- JWT Functions (keeping existing) ---
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.now(pytz.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_current_user_id(token: str = Header(None)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token missing")
    payload = verify_token(token)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return user_id

# --- Pydantic Models (keeping existing) ---
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
    conversation_history: Optional[List[Dict[str, Any]]] = None

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    try:
        setup_database_tables()
        print("Application startup completed successfully")
    except Exception as e:
        print(f"Startup error: {e}")
        raise

# --- Authentication Endpoints (keeping existing) ---
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
    cur = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (request.username,))
        result = cur.fetchone()

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
        
        raise HTTPException(status_code=401, detail="Invalid username or password")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# --- Database Management Endpoints (keeping existing) ---
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
    conn = None
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        cur = conn.cursor()
        databases = []
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

# --- Enhanced Ask Endpoint with Semantic Caching ---
@app.post("/ask", tags=["LLM Interaction"])
async def ask_llm(request: QueryRequest, user_id: str = Depends(get_current_user_id)):
    """
    Enhanced query handler with semantic caching and intent detection.
    Flow: Semantic Cache → Intent Detection → OSS LLM Fallback
    """
    user_query = request.user_query.strip()
    print(f"🔍 Processing query: {user_query}")
    
    # Step 1: Get user's database schemas
    all_user_schemas = get_all_user_db_schemas(user_id)
    if not all_user_schemas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No database connections found. Please add a database configuration first."
        )
    
    # Step 2: Generate embedding for semantic similarity
    query_embedding = get_query_embedding(user_query)
    
    # Step 3: Check semantic cache first
    if query_embedding is not None:
        similar_match = find_similar_cached_query(user_id, user_query, query_embedding)
        if similar_match:
            response = similar_match["response"].copy()
            response["source"] = "semantic_cache"
            response["similarity_score"] = similar_match["similarity"]
            response["original_cached_query"] = similar_match["original_query"]
            print(f"✅ Returning semantic cache hit")
            return response
    
    # Step 4: Try intent detection with patterns
    intent_result = detect_intent_with_patterns(user_query, all_user_schemas)
    if intent_result and intent_result.get("confidence", 0) > INTENT_CONFIDENCE_THRESHOLD:
        print(f"🎯 Intent detection successful (confidence: {intent_result['confidence']})")
        
        # Handle list tables action
        if intent_result.get("action") == "list_tables":
            db_name = intent_result.get("db")
            if not db_name:
                raise HTTPException(status_code=400, detail="Could not determine database for table listing.")
            
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
                    "source": "intent_detection",
                    "confidence": intent_result["confidence"]
                }
                
                # Cache this result
                if query_embedding is not None:
                    store_semantic_cache(user_id, user_query, query_embedding, final_response)
                
                return final_response
            finally:
                if creds_conn:
                    creds_conn.close()
        
        # Handle SQL query execution
        elif "query" in intent_result:
            inferred_db_name = intent_result.get("db")
            inferred_table = intent_result.get("table")
            sql_query = intent_result.get("query")
            
            # Get database credentials
            creds_conn = None
            try:
                creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
                current_db_config = get_user_db_credentials(creds_conn.cursor(), user_id, inferred_db_name)
            finally:
                if creds_conn:
                    creds_conn.close()
            
            if not current_db_config:
                raise HTTPException(status_code=404, detail=f"Database configuration '{inferred_db_name}' not found.")
            
            # Execute the query
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
                    "source": "intent_detection",
                    "confidence": intent_result["confidence"]
                }
                
                # Cache this result
                if query_embedding is not None:
                    store_semantic_cache(user_id, user_query, query_embedding, final_response)
                
                return final_response
            except Exception as e:
                print(f"Error executing intent-detected query: {e}")
                # Fall through to OSS LLM on execution error
            finally:
                if conn:
                    conn.close()
    
    # Step 5: Fallback to OSS LLM
    print(f"🔄 Escalating to OSS LLM (no cache hit or intent detection failed)")
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
    
    # Process LLM response (same as before)
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
                "source": "llm_fallback"
            }
            
            # Cache this LLM result
            if query_embedding is not None:
                store_semantic_cache(user_id, user_query, query_embedding, final_response)
            
            return final_response
        finally:
            if creds_conn:
                creds_conn.close()

    # Handle SQL query from LLM
    elif "query" in llm_output:
        inferred_db_name = llm_output.get("db")
        inferred_table = llm_output.get("table")
        sql_query = llm_output.get("query")

        if not all([inferred_db_name, inferred_table, sql_query]):
            raise HTTPException(status_code=400, detail="LLM response for query is missing 'db', 'table', or 'query' key.")

        print(f"LLM inferred DB: {inferred_db_name}, Table: {inferred_table}, Generated SQL: {sql_query}")

        # Securely retrieve credentials
        creds_conn = None
        try:
            creds_conn = get_db_connection(DEFAULT_DB_CONFIG)
            current_db_config = get_user_db_credentials(creds_conn.cursor(), user_id, inferred_db_name)
        finally:
            if creds_conn:
                creds_conn.close()

        if not current_db_config:
            raise HTTPException(status_code=404, detail=f"Database configuration '{inferred_db_name}' not found or you do not have access.")

        # Execute the query
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
                "source": "llm_fallback"
            }
            
            # Cache this LLM result
            if query_embedding is not None:
                store_semantic_cache(user_id, user_query, query_embedding, final_response)
            
            return final_response
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"An error occurred during query execution: {e}")
        finally:
            if conn:
                conn.close()
    
    # LLM response is unclear
    else:
        raise HTTPException(status_code=400, detail=f"LLM returned an unrecognized response format: {llm_output}")

# --- Cache Management Endpoints ---
@app.get("/cache-stats", tags=["Cache Management"])
async def get_cache_stats(user_id: str = Depends(get_current_user_id)):
    """Get semantic cache statistics for the current user."""
    if not cache_client:
        return {"error": "Cache not available"}
    
    try:
        index_key = f"semantic_index:{user_id}"
        cached_keys = cache_client.smembers(index_key)
        
        stats = {
            "total_cached_queries": len(cached_keys),
            "cache_entries": []
        }
        
        for cache_key in cached_keys:
            try:
                cached_data = cache_client.get(cache_key)
                if cached_data:
                    cache_entry = SemanticCacheEntry.parse_raw(cached_data)
                    stats["cache_entries"].append({
                        "query": cache_entry.query,
                        "hit_count": cache_entry.hit_count,
                        "timestamp": cache_entry.timestamp,
                        "response_type": cache_entry.response.get("action", "query")
                    })
            except Exception as e:
                print(f"Error reading cache entry {cache_key}: {e}")
                continue
        
        # Sort by hit count descending
        stats["cache_entries"].sort(key=lambda x: x["hit_count"], reverse=True)
        
        return stats
    except Exception as e:
        print(f"Error getting cache stats: {e}")
        return {"error": "Failed to retrieve cache statistics"}

@app.delete("/clear-cache", tags=["Cache Management"])
async def clear_user_cache(user_id: str = Depends(get_current_user_id)):
    """Clear all cached queries for the current user."""
    if not cache_client:
        return {"error": "Cache not available"}
    
    try:
        index_key = f"semantic_index:{user_id}"
        cached_keys = cache_client.smembers(index_key)
        
        # Delete all cache entries
        if cached_keys:
            cache_client.delete(*cached_keys)
        
        # Delete the index
        cache_client.delete(index_key)
        
        return {
            "message": f"Cleared {len(cached_keys)} cached queries",
            "cleared_count": len(cached_keys)
        }
    except Exception as e:
        print(f"Error clearing cache: {e}")
        return {"error": "Failed to clear cache"}

# --- Debug Endpoints ---
@app.post("/debug-intent", tags=["Debug"])
async def debug_intent_detection(request: QueryRequest, user_id: str = Depends(get_current_user_id)):
    """Debug endpoint to test intent detection without executing queries."""
    all_user_schemas = get_all_user_db_schemas(user_id)
    if not all_user_schemas:
        raise HTTPException(status_code=404, detail="No database connections found.")
    
    intent_result = detect_intent_with_patterns(request.user_query, all_user_schemas)
    
    return {
        "query": request.user_query,
        "intent_detected": intent_result is not None,
        "intent_result": intent_result,
        "available_patterns": [
            {
                "pattern": p.pattern,
                "confidence": p.confidence_score,
                "sql_template": p.sql_template
            }
            for p in INTENT_PATTERNS
        ]
    }

@app.post("/debug-embedding", tags=["Debug"])
async def debug_embedding_similarity(query1: str, query2: str):
    """Debug endpoint to test semantic similarity between two queries."""
    if not embedding_model:
        raise HTTPException(status_code=503, detail="Embedding model not available")
    
    try:
        embedding1 = get_query_embedding(query1)
        embedding2 = get_query_embedding(query2)
        
        if embedding1 is None or embedding2 is None:
            raise HTTPException(status_code=500, detail="Failed to generate embeddings")
        
        similarity = cosine_similarity(
            embedding1.reshape(1, -1), 
            embedding2.reshape(1, -1)
        )[0][0]
        
        return {
            "query1": query1,
            "query2": query2,
            "similarity": float(similarity),
            "would_cache_hit": similarity > SEMANTIC_SIMILARITY_THRESHOLD,
            "threshold": SEMANTIC_SIMILARITY_THRESHOLD
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating similarity: {e}")

# --- Health Check ---
@app.get("/health", tags=["System"])
async def health_check():
    """System health check including cache and embedding model status."""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "components": {
            "database": "unknown",
            "redis_cache": "unknown",
            "embedding_model": "unknown"
        }
    }
    
    # Check database
    try:
        conn = get_db_connection(DEFAULT_DB_CONFIG)
        conn.close()
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["components"]["database"] = f"unhealthy: {e}"
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        if cache_client:
            cache_client.ping()
            health_status["components"]["redis_cache"] = "healthy"
        else:
            health_status["components"]["redis_cache"] = "disabled"
    except Exception as e:
        health_status["components"]["redis_cache"] = f"unhealthy: {e}"
        health_status["status"] = "degraded"
    
    # Check embedding model
    try:
        if embedding_model:
            # Quick test embedding
            test_embedding = get_query_embedding("test query")
            if test_embedding is not None:
                health_status["components"]["embedding_model"] = "healthy"
            else:
                health_status["components"]["embedding_model"] = "unhealthy: failed to generate embedding"
                health_status["status"] = "degraded"
        else:
            health_status["components"]["embedding_model"] = "disabled"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["components"]["embedding_model"] = f"unhealthy: {e}"
        health_status["status"] = "degraded"
    
    return health_status