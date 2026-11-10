# pip install streamlit pandas

import streamlit as st
import pandas as pd
import sqlite3
from io import BytesIO
import hashlib

# ----------------------------------
# 1. Database setup
# ----------------------------------

def get_connection():
    return sqlite3.connect("leaderboard.db")


def initialize_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'Anonymous',
            filename TEXT,
            file_hash TEXT UNIQUE,
            total REAL
        )
    """)

    # Check whether username column exists
    columns = conn.execute(
        "PRAGMA table_info(leaderboard)"
    ).fetchall()

    column_names = [column[1] for column in columns]

    # Add username column to older databases
    if "username" not in column_names:
        conn.execute("""
            ALTER TABLE leaderboard
            ADD COLUMN username TEXT NOT NULL
            DEFAULT 'Anonymous'
        """)

    conn.commit()
    conn.close()


initialize_database()


# ----------------------------------
# 2. Calculate CSV metric
# ----------------------------------

def calculate_sum(df):
    numeric_df = df.apply(
        pd.to_numeric, errors="coerce"
    )

    return float(numeric_df.sum().sum())


# ----------------------------------
# 3. Streamlit website
# ----------------------------------

st.title("CSV Sum Leaderboard")

st.write(
    "Enter your username and upload a CSV "
    "file to compete on the leaderboard!"
)

# Initialize username in session state
if "username" not in st.session_state:
    st.session_state.username = ""

# Function to clear the username
def clear_username():
    st.session_state.username = ""

# Username input
username = st.text_input(
    "Enter your username",
    max_chars=30,
    key="username"
)

# Clear button
st.button(
    "Clear Username",
    on_click=clear_username
)

# CSV upload
uploaded_file = st.file_uploader(
    "Choose a CSV file",
    type=["csv"]
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()

    try:
        df = pd.read_csv(BytesIO(file_bytes))

        st.subheader("Uploaded CSV")
        st.dataframe(df)

        total = calculate_sum(df)

        st.subheader("Your Score")
        st.metric("Sum of all numbers", total)

        # Submit button
        if st.button("Submit to Leaderboard"):

            # Validate username
            if not username.strip():
                st.error(
                    "Please enter a username first."
                )

            else:
                file_hash = hashlib.sha256(
                    file_bytes
                ).hexdigest()

                conn = get_connection()

                cursor = conn.execute("""
                    INSERT OR IGNORE INTO leaderboard
                    (username, filename, file_hash, total)
                    VALUES (?, ?, ?, ?)
                """, (
                    username.strip(),
                    uploaded_file.name,
                    file_hash,
                    total
                ))

                conn.commit()
                conn.close()

                if cursor.rowcount > 0:
                    st.success(
                        "Score added to leaderboard!"
                    )
                else:
                    st.info(
                        "This CSV was already submitted."
                    )

    except (pd.errors.ParserError,
            pd.errors.EmptyDataError,
            UnicodeError) as e:
        st.error(f"Could not read CSV: {e}")


# ----------------------------------
# 4. Display leaderboard
# ----------------------------------

st.header("Leaderboard")

conn = get_connection()

leaderboard = pd.read_sql_query("""
    SELECT username, filename, total
    FROM leaderboard
    ORDER BY total DESC, id ASC
""", conn)

conn.close()

if not leaderboard.empty:
    leaderboard.index += 1
    leaderboard.index.name = "Rank"

    leaderboard.columns = [
        "Username",
        "File Name",
        "Total Sum"
    ]

    st.dataframe(leaderboard)

else:
    st.write("No CSV files submitted yet.")
