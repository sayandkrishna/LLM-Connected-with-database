# 🤖 Smart Database Query API

Transform natural language into powerful database queries. This production-ready API uses intent detection, semantic caching, and LLM-powered SQL generation to bridge the gap between human language and your data.

This API is designed for developers, data analysts, and business users who need to interact with databases without writing complex SQL.

-----

## 🌟 Core Features

  * **Natural Language Processing**:

      * **Intent Detection**: Employs pattern-based recognition for common query types like listing, counting, and filtering.
      * **LLM Integration**: Seamlessly falls back to a language model for complex or ambiguous queries.
      * **Query Understanding**: Performs semantic analysis of user intent and conversation history for contextual understanding.

  * **Performance Optimization**:

      * **Semantic Caching**: Utilizes a Redis-based cache with sentence transformers to store and retrieve results for similar queries, drastically reducing response times.
      * **Intelligent Fallbacks**: Prioritizes fast pattern matching before making more expensive LLM calls.

  * **Database Management**:

      * **Multi-Database Support**: Connect to and manage multiple PostgreSQL databases simultaneously.
      * **Schema Exploration**: Automatically discovers tables, columns, and data types.
      * **Credential Management**: Securely stores and manages database connection credentials.

  * **Security & Authentication**:

      * **JWT Authentication**: Secures endpoints with token-based user authentication.
      * **User Isolation**: Ensures that each user's queries, database configurations, and cache are kept separate.
      * **Password Security**: Uses SHA-256 hashing to protect stored user credentials.

-----

## 🏗️ Technical Architecture

The application is built with a clean, modular design that separates concerns for maintainability and scalability.

```
/
├── api.py             # FastAPI application, route definitions, and endpoint logic
├── auth.py            # JWT authentication, user creation, and password management
├── cache.py           # Redis caching, embedding generation, and semantic similarity logic
├── config.py          # Environment configuration using Pydantic settings
├── database.py        # Database connection management and schema discovery
├── main.py            # Main application entry point
├── models.py          # Pydantic data models for request/response validation
├── services.py        # Core business logic for query orchestration and intent detection
└── requirements.txt   # Python dependencies
```

### Component Responsibilities

  * **`config.py`**: Manages all environment variables and configuration settings.
  * **`models.py`**: Defines Pydantic models for robust data validation of API requests and responses.
  * **`database.py`**: Handles all interactions with the database, from connection pooling to schema discovery.
  * **`cache.py`**: Manages the Redis connection, sentence transformer model, and all caching logic.
  * **`auth.py`**: Implements JWT token creation/validation and user authentication workflows.
  * **`services.py`**: Contains the core business logic, including the query processing pipeline and intent detection algorithms.
  * **`api.py`**: Defines all REST endpoints, handles request/response cycles, and manages errors.

-----

## ⚙️ How It Works: The Query Pipeline

1.  **Input Validation**: An incoming request is first validated against Pydantic models.
2.  **Semantic Cache Check**: The system generates embeddings for the user query and searches Redis for semantically similar cached queries. If a match with a high similarity score is found, the cached response is returned instantly.
3.  **Intent Detection**: If no cache hit occurs, regex patterns are applied to identify the query's intent (e.g., listing tables, counting records) and confidence score.
4.  **Query Execution**: If the intent is recognized with high confidence, a pre-defined SQL template is used to generate and execute a query. If not, the query is passed to an LLM for SQL generation.
5.  **Response Caching**: The final result is stored in the semantic cache with its corresponding embedding for future use.

-----

## 🛠️ Installation & Setup

### Prerequisites

  * Python 3.8+
  * PostgreSQL
  * Redis (for caching)

### Environment Configuration

Create a `.env` file in the project root and add the following variables:

```env
# Database Configuration (for the application's own data)
DB_HOST=localhost
DB_DATABASE=your_db_name
DB_USER=your_username
DB_PASSWORD=your_password
DB_PORT=5432

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
CACHE_EXPIRATION_SECONDS=3600

# JWT Configuration
JWT_SECRET_KEY=a-very-strong-and-secret-key

# Semantic Search Configuration
SEMANTIC_SIMILARITY_THRESHOLD=0.88
INTENT_CONFIDENCE_THRESHOLD=0.8
```

### Installation Steps

1.  **Clone the repository**:

    ```bash
    git clone <repository-url>
    cd smart-database-query-api
    ```

2.  **Create and activate a virtual environment**:

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the application**:

    ```bash
    uvicorn main:app --reload
    ```

    The API will be available at `http://localhost:8000`.

-----

## 🚀 API Endpoints

### Authentication

  * `POST /signup`: Register a new user.
  * `POST /login`: Authenticate and receive a JWT token.

### Database Management

  * `POST /save-db-config`: Save or update database connection details for the authenticated user.
  * `GET /list-dbs`: List all saved database configurations for the user.
  * `GET /list-tables/{db_name}`: List all tables in a specified database.

### Query Processing

  * `POST /ask`: The main endpoint for submitting natural language queries.
  * `POST /debug-intent`: Test the intent detection on a query without executing it.
  * `POST /debug-embedding`: Get the semantic similarity score between two queries.

### Cache Management

  * `GET /cache-stats`: View cache statistics, including hit rates.
  * `DELETE /clear-cache`: Clear the cache for the authenticated user.

### System Monitoring

  * `GET /health`: A comprehensive health check endpoint that reports the status of the database, Redis cache, and embedding model.

-----

## USAGE

### 1\. Register a User

```bash
curl -X POST "http://localhost:8000/signup" \
-H "Content-Type: application/json" \
-d '{
  "username": "testuser",
  "password": "password123"
}'
```

### 2\. Log In

```bash
curl -X POST "http://localhost:8000/login" \
-H "Content-Type: application/json" \
-d '{
  "username": "testuser",
  "password": "password123"
}'
```

### 3\. Save Database Credentials

```bash
curl -X POST "http://localhost:8000/save-db-config" \
-H "token: YOUR_JWT_TOKEN" \
-H "Content-Type: application/json" \
-d '{
  "db_name": "production_db",
  "db_host": "your_db_host",
  "db_database": "your_db_name",
  "db_user": "your_db_user",
  "db_password": "your_db_password",
  "db_port": 5432
}'
```

### 4\. Ask a Question

```bash
curl -X POST "http://localhost:8000/ask" \
-H "token: YOUR_JWT_TOKEN" \
-H "Content-Type: application/json" \
-d '{
  "user_query": "how many users do we have?"
}'
```

-----

## 🤝 Contributing

Contributions are welcome\! Please feel free to submit a pull request or open an issue.

-----

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
