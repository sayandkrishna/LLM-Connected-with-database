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
    raise EnvironmentError("OPENROUTER_API_KEY not found in .env file. Please add it.")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "openai/gpt-oss-20b:free"  # Free model

def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 500,
    retries: int = 3,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Call the OpenRouter API with prompts and parameters."""
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
                time.sleep(2**i)
            else:
                raise ConnectionError(f"Failed to connect to OpenRouter after {retries} retries.") from e
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise


def llmcall(user_query: str, all_db_schemas: Dict, conversation_history: Optional[List[Dict]] = None) -> str:
    """Convert a natural language query into SQL or admin command, with memory for last db/table."""

    # Step 1: Build schema string
    db_schema_prompt_lines = []
    for db_name, tables in all_db_schemas.items():
        db_schema_prompt_lines.append(f"Database '{db_name}':")
        for table_name, schema_info in tables.items():
            db_schema_prompt_lines.append(f"  Table '{table_name}':")
            for col in schema_info:
                if col.get("column_name") and col.get("data_type"):
                    db_schema_prompt_lines.append(f"    - {col['column_name']} ({col['data_type']})")
        db_schema_prompt_lines.append("")
    full_db_schema_string = "\n".join(db_schema_prompt_lines)

    # Step 2: Track last used db/table from history
    last_db = last_table = None
    history_string = "No previous conversation."
    if conversation_history:
        history_lines = ["Here is the recent conversation history for context:"]
        for turn in conversation_history:
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role == "user":
                history_lines.append(f"- User: {content}")
            elif role == "assistant" and isinstance(content, dict):
                if "db" in content:
                    last_db = content.get("db")
                if "table" in content:
                    last_table = content.get("table")
                history_lines.append(f"- Assistant Output: {json.dumps(content)}")
        history_string = "\n".join(history_lines)

    # Step 3: If user omits db/table, tell LLM to reuse last ones
    memory_instructions = ""
    if last_db or last_table:
        memory_instructions = (
            f"If the user request does not mention a database or table, reuse the last used ones: "
            f"db='{last_db}' table='{last_table}'.\n"
            f"If there is no last table (None), only reuse the db."
        )

    # Step 4: Prompts
    system_prompt = (
        "You are a world-class database expert. Convert natural language requests into either SQL queries or admin commands. "
        "Your output must be a single valid JSON object only."
    )

    user_prompt = f"""
**Database Schema:**
{full_db_schema_string}
---
**Conversation History:**
{history_string}
---
**Memory Instructions:**
{memory_instructions}
---
**Core Instructions:**
1. For Data Queries: Return {{"db": "...", "table": "...", "query": "..."}}.
2. For List Tables: Return {{"db": "...", "action": "list_tables"}}.
3. If unclear, return {{}}.

**Current User Request:** {user_query}
**JSON Output:**
"""

    try:
        raw_response = call_llm(system_prompt, user_prompt, temperature=0.0)
        text_output = raw_response["choices"][0]["message"]["content"].strip()

        # Extract JSON
        json_match = re.search(r'\{.*\}', text_output, re.DOTALL)
        if not json_match:
            raise ValueError(f"LLM did not return valid JSON. Raw output: {text_output}")

        parsed_output = json.loads(json_match.group(0))

        # Validate keys
        if parsed_output:
            if parsed_output.get("action") == "list_tables":
                if "db" not in parsed_output:
                    raise ValueError("Missing 'db' key for list_tables action.")
            else:
                for k in ["db", "table", "query"]:
                    if k not in parsed_output:
                        raise ValueError(f"Missing key '{k}' in output: {parsed_output}")

        print(f"LLM Output: {parsed_output}")
        return json.dumps(parsed_output)

    except (ConnectionError, ValueError, json.JSONDecodeError) as e:
        print(f"Error: {e}")
        return "{}"
    except Exception as e:
        print(f"Unexpected error in llmcall: {e}")
        return "{}"
