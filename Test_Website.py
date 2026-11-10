import streamlit as st
import pandas as pd
import hashlib
from io import BytesIO
from supabase import create_client

# ----------------------------------
# 1. Connect to Supabase
# ----------------------------------

@st.cache_resource
def get_database():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

supabase = get_database()


# ----------------------------------
# 2. Calculate CSV metric
# ----------------------------------

def calculate_sum(df):
    numeric_df = df.apply(
        pd.to_numeric,
        errors="coerce"
    )
    return float(numeric_df.sum().sum())


# ----------------------------------
# 3. Username session state
# ----------------------------------

if "username" not in st.session_state:
    st.session_state.username = ""

def clear_username():
    st.session_state.username = ""


# ----------------------------------
# 4. Streamlit website
# ----------------------------------

st.title("CSV Sum Leaderboard")

st.write(
    "Enter your username and upload a CSV "
    "file to compete on the leaderboard!"
)

username = st.text_input(
    "Enter your username",
    max_chars=30,
    key="username"
)

st.button(
    "Clear Username",
    on_click=clear_username
)

uploaded_file = st.file_uploader(
    "Choose a CSV file",
    type=["csv"]
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()

    try:
        df = pd.read_csv(BytesIO(file_bytes))

        st.subheader("Uploaded CSV Preview")

        st.write(f"Total rows: {len(df)}")
        st.write(f"Total columns: {len(df.columns)}")

        st.dataframe(
            df,
            height=400
        )

        total = calculate_sum(df)

        st.subheader("Your Score")
        st.metric("Sum of all numbers", total)

        if st.button("Submit to Leaderboard"):

            if not username.strip():
                st.error("Please enter a username.")

            else:
                file_hash = hashlib.sha256(
                    file_bytes
                ).hexdigest()

                try:
                    # Check for duplicate file
                    existing = (
                        supabase.table("leaderboard")
                        .select("id")
                        .eq("file_hash", file_hash)
                        .limit(1)
                        .execute()
                    )

                    if existing.data:
                        st.info(
                            "This CSV was already submitted."
                        )
                    else:
                        # Insert new submission
                        supabase.table("leaderboard").insert({
                            "username": username.strip(),
                            "filename": uploaded_file.name,
                            "file_hash": file_hash,
                            "total": total
                        }).execute()

                        st.success(
                            "Score added to leaderboard!"
                        )

                except Exception as e:
                    st.error(f"Supabase submission error: {e}")

    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        UnicodeError
    ) as e:
        st.error(f"Could not read CSV: {e}")


# ----------------------------------
# 5. Display leaderboard
# ----------------------------------

st.header("Leaderboard")

if st.button("Refresh Leaderboard"):
    st.rerun()

try:
    response = (
        supabase.table("leaderboard")
        .select("username,filename,total")
        .order("total", desc=True)
        .limit(1000)
        .execute()
    )

    leaderboard = pd.DataFrame(response.data)

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

except Exception as e:
    st.error(f"Supabase leaderboard error: {e}")
