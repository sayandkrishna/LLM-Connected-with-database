import requests
import json

def llmcall(user_query: str) -> str:
    url = "http://127.0.0.1:11434/api/generate"

    # Explicitly give LLM the table schema
    prompt = f"""
You are an expert in SQL (SQLite).
You have one table named 'employees' with these columns:

EmpID, FirstName, LastName, StartDate, ExitDate, Title, Supervisor, ADEmail, 
BusinessUnit, EmployeeStatus, EmployeeType, PayZone, EmployeeClassificationType,
TerminationType, TerminationDescription, DepartmentType, Division, DOB, State,
JobFunctionDescription, GenderCode, LocationCode, RaceDesc, MaritalDesc, 
PerformanceScore, CurrentEmployeeRating

Rules:
1. Convert the user's natural language request into a valid SQL query.
2. Only use the columns provided above.
3. Only return the SQL query (no markdown, no explanations, no backticks).
4. Ensure the query works in SQLite.

User request: {user_query}

SQLite Query:
"""

    data = {
        "model": "llama3:latest",
        "prompt": prompt,
        "stream": True
    }

    print("Sending request to Ollama...")
    response = requests.post(url, json=data, stream=True)

    full_reply = ""
    for line in response.iter_lines():
        if line:
            part = json.loads(line.decode('utf-8'))
            full_reply += part.get("response", "")

    return full_reply.strip()
