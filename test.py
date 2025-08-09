import requests
import json
import time
import re
import os
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env file.")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "openai/gpt-oss-20b:free" # Use the specified free model

def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 500,
    retries: int = 3,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    A generic function to call the OpenRouter API with specified prompts and parameters.
    Handles API requests, retries, and error handling.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for i in range(retries):
        try:
            print(f"Calling OpenRouter API (Attempt {i + 1}/{retries})...")
            response = requests.post(
                OPENROUTER_URL, headers=headers, json=data, timeout=timeout
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"HTTP error on attempt {i + 1}: {e}")
            if i < retries - 1:
                time.sleep(2**i)  # Exponential backoff
            else:
                raise ConnectionError(f"Failed to connect to OpenRouter after {retries} retries.") from e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise  # Re-raise the exception after logging


def llmcall(user_query: str, all_db_schemas: Dict, conversation_history: Optional[List[Dict]] = None) -> str:
    """
    Converts a natural language query into a SQL query using an LLM.
    It builds a detailed prompt including database schemas and conversation history.
    """
    # 1. Build a detailed schema string for the prompt
    db_schema_prompt_lines = []
    for db_name, tables in all_db_schemas.items():
        db_schema_prompt_lines.append(f"Database '{db_name}':")
        for table_name, schema_info in tables.items():
            db_schema_prompt_lines.append(f"  Table '{table_name}':")
            columns = [
                f"    - {col.get('column_name')} ({col.get('data_type')})"
                for col in schema_info
                if col.get("column_name") and col.get("data_type")
            ]
            db_schema_prompt_lines.extend(columns)
        db_schema_prompt_lines.append("")
    full_db_schema_string = "\n".join(db_schema_prompt_lines)

    # 2. Format conversation history for context
    history_string = "No previous conversation."
    if conversation_history:
        history_lines = ["Here is the recent conversation history for context:"]
        for turn in conversation_history:
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role == "user":
                history_lines.append(f"- User: {content}")
            elif role == "assistant" and isinstance(content, dict) and "sql_query" in content:
                history_lines.append(f"- Assistant (executed SQL): {content['sql_query']}")
        history_string = "\n".join(history_lines)

    # 3. Define the system and user prompts
    system_prompt = (
        "You are a world-class SQL expert. Your task is to convert natural language "
        "queries into SQL, considering the provided database schema and conversation history. "
        "Your output must be a single, valid JSON object."
    )

    user_prompt = f"""
**Database Schema:**
{full_db_schema_string}
---
**Conversation History:**
{history_string}
---
**Core Instructions:**
1.  Analyze the user's request and the conversation history.
2.  Correct any spelling errors in table or column names based on the schema.
3.  When filtering by a person's name, use the `ILIKE` operator for case-insensitive matching. If the name has a potential misspelling, you can use `ILIKE` with wildcard characters (`%`) to match similar names.
4.  Generate a single, syntactically correct SQL query.
5.  Your final output must be a single JSON object with three keys: "db" (the database name), "table" (the primary table), and "query" (the SQL query).
6.  If the request is impossible to fulfill, return an empty JSON object: {{}}.

**Examples:**
- User: "show me all mobiles"
  Output: {{\"db\": \"mobiles\", \"table\": \"mobile_phones\", \"query\": \"SELECT * FROM mobile_phones\"}}
- History: "SELECT * FROM teacher WHERE salary > 20000"
  User: "what is the total salary of these teachers"
  Output: {{\"db\": \"teachers\", \"table\": \"teacher\", \"query\": \"SELECT SUM(salary) FROM teacher WHERE salary > 20000\"}}
- User: "list details of a student named john"
  Output: {{\"db\": \"teachers\", \"table\": \"students\", \"query\": \"SELECT * FROM students WHERE name ILIKE '%john%'\"}}


**Current User Request:** {user_query}

**JSON Output:**
"""

    # 4. Call the generic LLM function
    try:
        raw_response = call_llm(system_prompt, user_prompt, temperature=0.0)
        text_output = raw_response["choices"][0]["message"]["content"]

        # 5. Extract and validate the JSON output
        json_match = re.search(r'\{.*\}', text_output, re.DOTALL)
        if not json_match:
            raise ValueError(f"LLM did not return a valid JSON object. Raw output: {text_output}")

        json_string = json_match.group(0)
        parsed_output = json.loads(json_string)

        # Basic validation for required keys
        if parsed_output and any(k not in parsed_output for k in ["db", "table", "query"]):
            raise ValueError(f"LLM output is missing required keys ('db', 'table', 'query'). Output: {json_string}")

        print(f"Successfully generated LLM Output: {json_string}")
        return json_string

    except (ConnectionError, ValueError, json.JSONDecodeError) as e:
        print(f"Error in LLM processing pipeline: {e}")
        # In case of a critical error, return an empty JSON string to be handled by the main app
        return "{}"
    except Exception as e:
        print(f"An unexpected error occurred in llmcall: {e}")
        return "{}"
