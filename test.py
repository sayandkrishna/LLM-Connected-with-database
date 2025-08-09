import requests
import json
import time
import re
from typing import Optional, List, Dict
from collections import defaultdict

def llmcall(user_query: str, all_db_schemas: Dict, conversation_history: List = None) -> str:
    """
    Converts natural language to SQL using Ollama LLM, with contextual awareness,
    error correction, and support for complex queries.
    """
    url = "http://127.0.0.1:11434/api/generate"

    # 1. Dynamically build the database schema string for the prompt
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

    # 2. Format the conversation history for the prompt
    history_string = ""
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

    # 3. The final, context-aware "Super-Prompt"
    prompt = f"""
You are a world-class SQL expert with contextual awareness. Your primary goal is to answer the user's current request, but you MUST use the provided conversation history to understand context for ambiguous or follow-up questions.

**Database Schema:**
{full_db_schema_string}
---
**Conversation History:**
{history_string if history_string else "No previous conversation."}
---

**Core Instructions:**

1.  **Analyze Intent**: First, analyze the 'Current User Request'.
2.  **Spelling Correction is Key**: Pay very close attention to the user's spelling. The user may misspell column names, table names, or SQL keywords. Your first job is to figure out what they *meant* to type based on the database schema.
3.  **Check History for Context**: If the request is a follow-up (e.g., "what about for a higher price?", "only the top 5", "what is the total sum of their salaries"), you MUST refer to the conversation history to understand the missing information (like the table or previous filters).
4.  **Generate SQL**: Based on the request and context, generate a precise SQL query. This can include `WHERE`, `GROUP BY`, `ORDER BY`, `LIMIT`, `SUM`, `AVG`, `COUNT`, and `JOIN`.
5.  **Strict JSON Output**: Your entire response MUST be a single JSON object with the keys "db", "table", and "query". Do not include any other text, not even comments or explanations.
6.  **Failure**: If the request is impossible or unclear, return an empty JSON object: {{}}.

---
**Examples:**

* **Initial Query with Misspelling**:
    * History: No previous conversation.
    * Current User Request: "shw me all mebiles"
    * Output: {{"db": "mobiles", "table": "mobile_phones", "query": "SELECT * FROM mobile_phones"}}

* **Query with Misspelled Column**:
    * History: No previous conversation.
    * Current User Request: "sem of prise of all mobiles"
    * Output: {{"db": "mobiles", "table": "mobile_phones", "query": "SELECT SUM(price) FROM mobile_phones"}}

* **Follow-up Query**:
    * History:
        - User: list all teacher with selery greter than 20k
        - Assistant (executed SQL): SELECT * FROM teacher WHERE salary > 20000
    * Current User Request: "what is total sum of salary of these teachers"
    * Output: {{"db": "teachers", "table": "teacher", "query": "SELECT SUM(salary) FROM teacher WHERE salary > 20000"}}

* **Aggregation with Grouping**:
    * History: No previous conversation.
    * Current User Request: "how many employees are in each department?"
    * Output: {{"db": "company_db", "table": "employees", "query": "SELECT department, COUNT(*) FROM employees GROUP BY department"}}

---

**Current User Request**: {user_query}

Output:"""

    data = {
        "model": "llama3:latest",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 1,
            "max_tokens": 500
        }
    }

    retries = 3
    for i in range(retries):
        try:
            print(f"Converting query: '{user_query}' to SQL (Attempt {i+1}/{retries})...")
            response = requests.post(url, json=data, timeout=60)
            response.raise_for_status()
            
            raw_response = response.json().get("response", "")

            try:
                json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                if not json_match:
                    print(f"LLM did not return any valid-looking JSON: {raw_response}")
                    return ""
                
                json_string = json_match.group(0)
                parsed_output = json.loads(json_string)

                if parsed_output and any(k not in parsed_output for k in ["db", "table", "query"]):
                    raise ValueError("LLM output is missing one of the required keys: 'db', 'table', 'query'.")
                
                print(f"Generated LLM Output: {json_string}")
                return json_string

            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error parsing LLM JSON response: {e}. Raw response: {raw_response}")
                return ""

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