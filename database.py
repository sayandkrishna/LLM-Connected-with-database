import psycopg2
from psycopg2 import sql
from typing import Dict, List, Optional
from config import settings

def get_db_connection(db_config: Dict) -> psycopg2.extensions.connection:
    """Create a database connection."""
    return psycopg2.connect(**db_config)

def setup_database_tables():
    """Create the necessary database tables if they don't exist."""
    conn = None
    try:
        conn = get_db_connection(settings.database_config)
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

def get_all_table_names(db_config: Dict) -> List[str]:
    """Get all table names from a database."""
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

def get_schema_for_table(db_config: Dict, table_name: str) -> List[Dict]:
    """Get schema information for a specific table."""
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
    """Get database credentials for a specific user and database."""
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
    """Get all database schemas for a specific user."""
    all_schemas = {}
    conn = None
    try:
        conn = get_db_connection(settings.database_config)
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
