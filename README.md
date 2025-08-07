# LLM Database Query API

A FastAPI application that converts natural language queries to SQL and executes them on a PostgreSQL database using Ollama LLM.

## 🚀 Features

- **Natural Language to SQL**: Convert human-readable queries to SQL using LLM
- **PostgreSQL Integration**: Execute queries on PostgreSQL database
- **Connection Pooling**: Optimized database connections for better performance
- **Error Handling**: Comprehensive error handling and validation
- **Health Checks**: Built-in health monitoring
- **API Documentation**: Auto-generated Swagger/OpenAPI docs

## 📋 Prerequisites

- Python 3.8+
- PostgreSQL database
- Ollama server running locally

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd API-PROJECTS
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup PostgreSQL**
   - Install PostgreSQL
   - Create a database named `mydb`
   - Update credentials in `.env` file if needed

4. **Setup Ollama**
   ```bash
   # Install Ollama (if not already installed)
   # Download from https://ollama.ai/
   
   # Pull the Llama model
   ollama pull llama3:latest
   ```

5. **Configure environment**
   ```bash
   # The .env file should contain:
   DB_NAME=mydb
   DB_USER=postgres
   DB_PASSWORD=root
   DB_HOST=localhost
   DB_PORT=5432
   ```

## 🚀 Quick Start

### Option 1: Using the startup script
```bash
python start_server.py
```

### Option 2: Manual setup
```bash
# 1. Setup database
python table.py

# 2. Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at: http://localhost:8000

## 📚 API Documentation

### Endpoints

#### POST `/ask`
Convert natural language to SQL and execute on database.

**Request:**
```json
{
  "user_query": "give all users having salary greater than 30000"
}
```

**Response:**
```json
{
  "sql_query": "SELECT * FROM employee WHERE salary > 30000",
  "rows_returned": 15,
  "data": [
    {
      "id": 1,
      "name": "Alice",
      "age": 25,
      "salary": 50000
    }
  ],
  "execution_time_ms": 245.67,
  "success": true,
  "error": null
}
```

#### GET `/health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected"
}
```

#### GET `/`
API information.

**Response:**
```json
{
  "message": "LLM Database Query API",
  "version": "1.0.0",
  "endpoints": {
    "/ask": "POST - Convert natural language to SQL and execute",
    "/health": "GET - Health check",
    "/docs": "GET - API documentation"
  }
}
```

## 🔧 Usage Examples

### Using curl
```bash
# Query employees with salary > 30000
curl -X POST "http://localhost:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"user_query": "give all users having salary greater than 30000"}'

# Query employees by age
curl -X POST "http://localhost:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"user_query": "show employees with age above 30"}'

# Query specific employee
curl -X POST "http://localhost:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"user_query": "find employees named Alice"}'
```

### Using Python requests
```python
import requests

# Query the API
response = requests.post(
    "http://localhost:8000/ask",
    json={"user_query": "give all users having salary greater than 30000"}
)

result = response.json()
print(f"SQL Query: {result['sql_query']}")
print(f"Rows returned: {result['rows_returned']}")
print(f"Execution time: {result['execution_time_ms']}ms")
```

## 🗄️ Database Schema

The application uses a PostgreSQL database with the following table:

### employee table
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| name | VARCHAR(100) | Employee name |
| age | INTEGER | Employee age |
| salary | INTEGER | Employee salary |
| created_at | TIMESTAMP | Record creation time |

## 🔍 Troubleshooting

### Common Issues

1. **Database Connection Error**
   - Verify PostgreSQL is running
   - Check credentials in `.env` file
   - Ensure database `mydb` exists

2. **Ollama Connection Error**
   - Ensure Ollama server is running: `ollama serve`
   - Verify model is downloaded: `ollama list`

3. **Module Import Errors**
   - Install missing dependencies: `pip install -r requirements.txt`
   - Activate virtual environment if using one

### Logs
The application provides detailed logging. Check the console output for:
- Database connection status
- SQL query generation
- Execution times
- Error details

## 🏗️ Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│  FastAPI    │───▶│   Ollama    │───▶│ PostgreSQL  │
│             │    │   Server    │    │    LLM      │    │  Database   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## 📝 License

This project is licensed under the MIT License.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request