import streamlit as st
import requests
import pandas as pd
import json

# --- Configuration ---
# Make sure your FastAPI backend is running at this address
API_URL = "http://127.0.0.1:8000"

# --- Page & Session State Setup ---
st.set_page_config(page_title="DB Chat AI", layout="wide", initial_sidebar_state="expanded")

# Initialize session state variables to persist data across reruns
def init_session_state():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "username" not in st.session_state: 
        st.session_state.username = None   
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "access_token" not in st.session_state:
        st.session_state.access_token = None
    if "databases" not in st.session_state:
        st.session_state.databases = []
    if "messages" not in st.session_state:
        st.session_state.messages = []

init_session_state()

# --- API Helper Functions ---
def login_user(username, password):
    try:
        response = requests.post(f"{API_URL}/login", json={"username": username, "password": password})
        if response.status_code == 200:
            return response.json()
        st.error(f"Login Failed: {response.json().get('detail', 'Unknown error')}")
        return None
    except requests.ConnectionError:
        st.error("Connection Error: Could not connect to the backend. Is it running?")
        return None

def signup_user(username, password):
    try:
        response = requests.post(f"{API_URL}/signup", json={"username": username, "password": password})
        if response.status_code == 200:
            st.success("Signup successful! Please log in.")
            return True
        st.error(f"Signup Failed: {response.json().get('detail', 'Username may already exist.')}")
        return False
    except requests.ConnectionError:
        st.error("Connection Error: Could not connect to the backend.")
        return False

def get_user_databases(token):
    headers = {"token": token}
    try:
        response = requests.get(f"{API_URL}/list-dbs", headers=headers)
        if response.status_code == 200:
            return response.json().get("databases", [])
        return []
    except requests.ConnectionError:
        st.error("Connection Error: Could not fetch databases.")
        return []

def save_db_config(token, config):
    headers = {"token": token}
    try:
        response = requests.post(f"{API_URL}/save-db-config", headers=headers, json=config)
        if response.status_code == 200:
            st.success("Database configuration saved successfully!")
            return True
        st.error(f"Failed to save: {response.json().get('detail')}")
        return False
    except requests.ConnectionError:
        st.error("Connection Error: Could not save configuration.")
        return False

def ask_llm(token, query):
    headers = {"token": token}
    try:
        response = requests.post(f"{API_URL}/ask", headers=headers, json={"user_query": query})
        if response.status_code == 200:
            return response.json()
        st.error(f"Error from AI: {response.json().get('detail')}")
        return None
    except requests.ConnectionError:
        st.error("Connection Error: Could not get response from AI.")
        return None

# --- UI Rendering Functions ---

def display_login_page():
    """Shows the centered Login/Sign Up form."""
    st.title("Welcome to Database Chat AI 🤖")
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            login_tab, signup_tab = st.tabs(["**Login**", "**Sign Up**"])

            with login_tab:
                with st.form("login_form"):
                    username_input = st.text_input("Username", key="login_user") # Renamed variable
                    password = st.text_input("Password", type="password", key="login_pass")
                    submitted = st.form_submit_button("Login", use_container_width=True)
                    if submitted:
                        user_data = login_user(username_input, password)
                        if user_data:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user_data["user_id"]
                            st.session_state.username = user_data["username"] # <-- ADD THIS LINE
                            st.session_state.access_token = user_data["access_token"]
                            st.rerun()
            with signup_tab:
                with st.form("signup_form"):
                    username = st.text_input("Choose a Username", key="signup_user")
                    password = st.text_input("Choose a Password", type="password", key="signup_pass")
                    submitted = st.form_submit_button("Sign Up", use_container_width=True)
                    if submitted:
                        signup_user(username, password)

def display_sidebar():
    """Renders the sidebar with DB list and add new DB form."""
    with st.sidebar:
        st.title("🗂️ Databases")
        st.markdown(f"User: **{st.session_state.user_id}**")
        
        # Fetch and display databases
        if not st.session_state.databases:
             with st.spinner("Loading databases..."):
                st.session_state.databases = get_user_databases(st.session_state.access_token)

        for db in st.session_state.databases:
            with st.container(border=True):
                st.subheader(f"🔹 {db['db_name']}")
                st.write(f"**Host:** {db['config']['host']}")
                st.write(f"**User:** {db['config']['user']}")

        # Form to add a new database
        with st.expander("🔗 Connect New Database"):
            with st.form("new_db_form", clear_on_submit=True):
                db_name = st.text_input("Connection Name (Alias)")
                db_host = st.text_input("Host", value="localhost")
                db_database = st.text_input("Database Name")
                db_user = st.text_input("User")
                db_password = st.text_input("Password", type="password")
                db_port = st.number_input("Port", value=5432)
                
                submitted = st.form_submit_button("Save Connection")
                if submitted:
                    config = {
                        "db_name": db_name, "db_host": db_host, "db_database": db_database,
                        "db_user": db_user, "db_password": db_password, "db_port": db_port
                    }
                    if save_db_config(st.session_state.access_token, config):
                        # Reset databases in state to force a refresh on next run
                        st.session_state.databases = []
                        st.rerun()

        st.button("Logout", on_click=logout, use_container_width=True)

def display_chat_interface():
    """Renders the main chat area."""
    st.title("Chat with your Data 💬")

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            # Check for complex content (dict) vs simple string
            if isinstance(message["content"], dict):
                if "summary" in message["content"]:
                    st.markdown(message["content"]["summary"])
                if "sql" in message["content"]:
                    st.code(message["content"]["sql"], language="sql")
                if "dataframe" in message["content"]:
                    df = pd.DataFrame(message["content"]["dataframe"])
                    st.dataframe(df)
            else:
                st.markdown(message["content"])

    # Accept user input
    if prompt := st.chat_input("Ask a question about your data... e.g., 'show all products from the electronics category'"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get assistant response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = ask_llm(st.session_state.access_token, prompt)
                if response:
                    # Create a rich response object for the chat history
                    assistant_response_content = {
                        "summary": f"I found **{response['rows_returned']}** results from the "
                                   f"`{response['inferred_table']}` table in the "
                                   f"`{response['inferred_db_name']}` database.",
                        "sql": response['sql_query'],
                        "dataframe": response['data']
                    }
                    st.session_state.messages.append({"role": "assistant", "content": assistant_response_content})
                else:
                    error_message = "I couldn't process that request. Please try rephrasing or check the backend logs."
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
            
            # Rerun to display the new message
            st.rerun()

def logout():
    """Clears the session state to log the user out."""
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.access_token = None
    st.session_state.databases = []
    st.session_state.messages = []
    st.rerun()

# --- Main Application Logic ---
if not st.session_state.logged_in:
    display_login_page()
else:
    display_sidebar()
    display_chat_interface()