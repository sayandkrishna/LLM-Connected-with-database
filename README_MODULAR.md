# Smart Database Query API

A smart database query API with semantic caching, intent detection, and LLM fallback, built with a clean, modular architecture in Python.

## ✨ Features

*   **Natural Language Queries:** Ask questions to your database in plain English.
*   **Semantic Caching:** Blazing-fast responses for similar queries using sentence transformers.
*   **Intent Detection:** Quickly handles common queries (e.g., counting, listing) without hitting the LLM.
*   **LLM Fallback:** For complex queries, the API leverages a Large Language Model to generate SQL.
*   **Modular Architecture:** Clean, maintainable, and scalable code organization.
*   **JWT Authentication:** Secure your endpoints with JSON Web Tokens.
*   **Database Management:** Endpoints to manage database configurations and explore schemas.

## 🚀 Getting Started

### Prerequisites

*   Python 3.8+
*   PostgreSQL
*   Redis (optional, for caching)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/sayandkrishna/LLM-Connected-with-database.git
    cd your-repo
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file in the project root and add the following configuration.

    ```env
    # Database Configuration
    DB_HOST=localhost
    DB_DATABASE=mydb
    DB_USER=postgres
    DB_PASSWORD=root
    DB_PORT=5432

    # Redis Configuration (optional)
    REDIS_HOST=localhost
    REDIS_PORT=6379
    REDIS_DB=0
    CACHE_EXPIRATION_SECONDS=3600

    # JWT Configuration
    JWT_SECRET_KEY=your-super-secret-key-change-this

    # Semantic Search Configuration
    SEMANTIC_SIMILARITY_THRESHOLD=0.8
    INTENT_CONFIDENCE_THRESHOLD=0.7
    ```

4.  **Run the application:**
    ```bash
    uvicorn main:app --reload
    ```
    The API will be available at `http://localhost:8000`.

## 🛠️ Technology Stack

*   **Backend:** FastAPI, Uvicorn
*   **Database:** PostgreSQL (with `psycopg2-binary`)
*   **Caching:** Redis
*   **Authentication:** PyJWT
*   **Data Handling:** Pandas
*   **Environment Management:** python-dotenv
*   **And more:** `pytz`, `requests`, `streamlit`

## 🏗️ Architecture

The application is organized into a modular structure for clarity and maintainability:

```
/
├── api.py             # FastAPI endpoints and routes
├── auth.py            # JWT authentication and user management
├── cache.py           # Redis caching and semantic similarity
├── config.py          # Configuration and environment variables
├── database.py        # Database operations
├── main.py            # Application entry point
├── models.py          # Pydantic data models
├── services.py        # Business logic and query orchestration
└── requirements.txt   # Project dependencies
```

## 📡 API Endpoints

### Authentication

*   `POST /signup`: Create a new user account.
*   `POST /login`: Authenticate and receive a JWT token.

### Database Management

*   `POST /save-db-config`: Save database configuration for a user.
*   `GET /list-dbs`: List a user's saved databases.
*   `GET /list-tables/{db_name}`: List tables in a specific database.

### Querying

*   `POST /ask`: The main endpoint for asking natural language questions.
*   `POST /debug-intent`: Test the intent detection for a query.
*   `POST /debug-embedding`: Compare the semantic similarity of two queries.

### Cache

*   `GET /cache-stats`: View statistics about the semantic cache.
*   `DELETE /clear-cache`: Clear the cache for the authenticated user.

### System

*   `GET /health`: System health check.

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes and commit them (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature-name`).
5.  Open a pull request.

Please make sure to update tests as appropriate.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.