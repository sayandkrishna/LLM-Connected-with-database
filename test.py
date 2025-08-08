import requests
import json
import time
from typing import Optional, List, Dict
from collections import defaultdict # Added import for defaultdict


import requests
import json
import time
from typing import Optional, List, Dict
from collections import defaultdict # Added import for defaultdict

def llmcall(user_query: str, all_db_schemas: Dict[str, Dict[str, List[Dict]]]) -> str:
    """
    Convert natural language query to SQL using Ollama LLM,
    dynamically including ALL of a user's database schema information for inference.

    Args:
        user_query (str): Natural language query from user.
        all_db_schemas (Dict[str, Dict[str, List[Dict]]]): A dictionary where keys are database names
                                                and values are their respective schemas (table_name -> schema).

    Returns:
        str: JSON string containing the inferred database name, table name, and the generated SQL query.
             Example: '{"db": "db1", "table": "table1", "query": "SELECT * FROM table1 WHERE age > 30"}'
             Returns an empty string if inference or SQL generation fails.
    """
    url = "http://127.0.0.1:11434/api/generate" # Ensure Ollama server is running

    # Dynamically build the full database schema string for the prompt
    db_schema_prompt_lines = []
    for db_name, tables in all_db_schemas.items():
        db_schema_prompt_lines.append(f"Database: {db_name}")
        for table_name, schema_info in tables.items():
            db_schema_prompt_lines.append(f"  Table: {table_name}")
            for col in schema_info:
                col_name = col.get("column_name")
                data_type = col.get("data_type")
                if col_name and data_type:
                    db_schema_prompt_lines.append(f"    - {col_name} ({data_type})")
        db_schema_prompt_lines.append("")

    full_db_schema_string = "\n".join(db_schema_prompt_lines).strip()

    # Enhanced prompt for multi-database inference and SQL generation
    prompt = f"""
    
You are an expert PostgreSQL SQL query generator. Your task is to convert natural language requests into valid SQL queries by inferring the correct database and table.

You have access to the following database schema for a user:

{full_db_schema_string}

Instructions:
1.  **Crucial Inference:**
    * Based on the 'User Request', infer the most appropriate **database** and **table** from the provided schema.
    * Use column and table names as the primary indicators for inference.
2.  **Generate SQL:** Construct a valid PostgreSQL SQL query for the inferred database and table. When comparing string values, use the case-insensitive ILIKE operator and include wildcards (%) to handle potential misspellings or casing variations. For example, a user query for "electronics" should generate a clause like `WHERE category ILIKE '%electronics%'`.
3.  **Strict Output Format:** Your response MUST be a JSON string with three keys:
    * `"db"`: The name of the inferred database (e.g., "db1").
    * `"table"`: The name of the inferred table (e.g., "table1", "table2").
    * `"query"`: The generated PostgreSQL SQL query (e.g., "SELECT * FROM table1 WHERE column_a > 30").
    Do NOT include any explanations, markdown formatting, or conversational text outside this JSON.
4.  **Column and Table Accuracy:** Use the exact table and column names as provided in the schema.
5.  **Handling Ambiguity/Failure:** If you cannot confidently infer the database or generate a valid SQL query, return an empty string.

Examples:
- User Request: "Find all records where name is 'John Doe'"
  Output: {{"db": "db1", "table": "table1", "query": "SELECT * FROM table1 WHERE name ILIKE '%john doe%'"}}

- User Request: "list items with a price greater than 100"
  Output: {{"db": "db2", "table": "table2", "query": "SELECT * FROM table2 WHERE price > 100"}}

- User Request: "find all records greater than age 39"
  Output: {{"db": "db1", "table": "table1", "query": "SELECT * FROM table1 WHERE age > 39"}}

- User Request: "list all products where category is eletronics"
  Output: {{"db": "mydb", "table": "products", "query": "SELECT * FROM products WHERE category ILIKE '%eletronics%'"}}
  
- User Request: "list all albums by artist 'Iron Maiden'"
  Output: {{"db": "chinook", "table": "Albums", "query": "SELECT T2.\"Title\" FROM \"Artists\" AS T1 JOIN \"Albums\" AS T2 ON T1.\"ArtistId\" = T2.\"ArtistId\" WHERE T1.\"Name\" ILIKE '%Iron Maiden%'"}}
  
User Request: {user_query}

Output:"""

    data = {
        "model": "llama3:latest",
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 200
        }
    }

    full_reply = ""
    retries = 3
    for i in range(retries):
        try:
            print(f"Converting query: '{user_query}' to SQL (Attempt {i+1}/{retries})...")
            response = requests.post(url, json=data, stream=True, timeout=60)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        part = json.loads(line.decode('utf-8'))
                        full_reply += part.get("response", "")
                    except json.JSONDecodeError:
                        continue

            try:
                parsed_output = json.loads(full_reply.strip())
                if not isinstance(parsed_output, dict) or "db" not in parsed_output or "table" not in parsed_output or "query" not in parsed_output:
                    raise ValueError("LLM output is not a valid JSON with 'db', 'table', and 'query' keys.")
            except json.JSONDecodeError:
                print(f"LLM did not return valid JSON: {full_reply.strip()}")
                return ""

            print(f"Generated LLM Output: {full_reply.strip()}")
            return full_reply.strip()

        except requests.exceptions.ConnectionError as e:
            print(f"Connection error to Ollama: {e}. Retrying...")
            time.sleep(2 ** i)
        except requests.exceptions.Timeout:
            print(f"Request to Ollama timed out. Retrying...")
            time.sleep(2 ** i)
        except requests.exceptions.RequestException as e:
            print(f"HTTP error from Ollama: {e}")
            raise ConnectionError(f"Failed to connect to Ollama server or received HTTP error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred in LLM call: {e}")
            raise Exception(f"LLM processing error: {e}")

    raise ConnectionError(f"Failed to connect to Ollama server after {retries} attempts.")

def llm_for_summary(prompt: str) -> str:
    """
    Calls Ollama LLM to generate a natural language summary.

    Args:
        prompt (str): The prompt containing the data to be summarized.

    Returns:
        str: The natural language summary.
    """
    url = "http://127.0.0.1:11434/api/generate"
    data = {
        "model": "llama3:latest",
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
            "max_tokens": 500
        }
    }

    full_reply = ""
    retries = 3
    for i in range(retries):
        try:
            print(f"Generating summary (Attempt {i+1}/{retries})...")
            response = requests.post(url, json=data, stream=True, timeout=60)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        part = json.loads(line.decode('utf-8'))
                        full_reply += part.get("response", "")
                    except json.JSONDecodeError:
                        continue
            
            return full_reply.strip()

        except requests.exceptions.ConnectionError as e:
            print(f"Connection error to Ollama for summary: {e}. Retrying...")
            time.sleep(2 ** i)
        except requests.exceptions.Timeout:
            print(f"Request to Ollama for summary timed out. Retrying...")
            time.sleep(2 ** i)
        except requests.exceptions.RequestException as e:
            print(f"HTTP error from Ollama for summary: {e}")
            raise ConnectionError(f"Failed to connect to Ollama server or received HTTP error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred in summary LLM call: {e}")
            raise Exception(f"LLM processing error: {e}")
    
    raise ConnectionError(f"Failed to connect to Ollama server after {retries} attempts.")
