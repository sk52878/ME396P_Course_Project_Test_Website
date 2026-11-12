import hashlib
import logging
import math
from io import BytesIO, StringIO
from zipfile import BadZipFile, ZipFile

import pandas as pd
import streamlit as st
from supabase import create_client


# ----------------------------------
# 1. Configuration and Supabase
# ----------------------------------

logger = logging.getLogger(__name__)

MOT_PATH = "OpenSimData/Kinematics/Walk1.mot"
MAX_ZIP_SIZE = 200 * 1024 * 1024  # 200 MB compressed upload
MAX_MOT_SIZE = 20 * 1024 * 1024  # 20 MB uncompressed MOT


@st.cache_resource
def get_database():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


try:
    supabase = get_database()
except Exception:
    logger.exception("Failed to initialize Supabase")
    st.error("The leaderboard service is unavailable. Please try again later.")
    st.stop()


# ----------------------------------
# 2. Read MOT from ZIP
# ----------------------------------

def read_mot_from_zip(zip_bytes):
    """Return (dataframe, metadata_text, mot_bytes, internal_path)."""
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError("The ZIP exceeds the 200 MB upload limit.")

    with ZipFile(BytesIO(zip_bytes)) as archive:
        # Permit an arbitrary outer folder, but require the exact relative path.
        matches = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and (
                info.filename == MOT_PATH
                or info.filename.endswith("/" + MOT_PATH)
            )
        ]

        if not matches:
            raise FileNotFoundError(
                f"The ZIP must contain '{MOT_PATH}'."
            )
        if len(matches) != 1:
            raise ValueError(
                "The ZIP contains multiple matching Walk1.mot files. "
                "Please include exactly one."
            )

        mot_info = matches[0]
        if mot_info.file_size > MAX_MOT_SIZE:
            raise ValueError("The Walk1.mot file exceeds the 20 MB limit.")

        # Read only the requested entry, with a hard cap on extracted bytes.
        with archive.open(mot_info) as mot_file:
            mot_bytes = mot_file.read(MAX_MOT_SIZE + 1)
        if len(mot_bytes) > MAX_MOT_SIZE:
            raise ValueError("The Walk1.mot file exceeds the 20 MB limit.")

    mot_text = mot_bytes.decode("utf-8-sig")
    lines = mot_text.splitlines()
    endheader_index = next(
        (i for i, line in enumerate(lines)
         if line.strip().lower() == "endheader"),
        None,
    )
    if endheader_index is None:
        raise ValueError("Walk1.mot is missing the 'endheader' marker.")

    # Keep every line of the original MOT metadata, including 'endheader'.
    metadata_text = "\n".join(lines[:endheader_index + 1])
    table_text = "\n".join(lines[endheader_index + 1:])
    if not table_text.strip():
        raise ValueError("Walk1.mot contains no data table after 'endheader'.")

    # The first nonempty line after endheader becomes the DataFrame column names.
    df = pd.read_csv(StringIO(table_text), sep=r"\s+")
    if df.empty or len(df.columns) == 0:
        raise ValueError("Walk1.mot contains no data rows.")

    return df, metadata_text, mot_bytes, mot_info.filename


# ----------------------------------
# 3. Calculate scores from MOT
# ----------------------------------

def calculate_sum(df):
    numeric_df = df.apply(pd.to_numeric, errors="coerce")
    total = float(numeric_df.sum().sum())
    if not math.isfinite(total):
        raise ValueError("The MOT score is not finite. Check the numeric data.")
    return total


# ----------------------------------
# 4. Username session state
# ----------------------------------

if "username" not in st.session_state:
    st.session_state.username = ""


def clear_username():
    st.session_state.username = ""


# ----------------------------------
# 5. Streamlit website and submission
# ----------------------------------

st.title("MOT Sum Leaderboard", anchor=False)
st.write(
    "Enter your username and upload a ZIP containing "
    f"`{MOT_PATH}` to compete on the leaderboard!"
)

username = st.text_input(
    "Enter your username",
    max_chars=30,
    key="username",
)
st.button("Clear Username", on_click=clear_username)

uploaded_file = st.file_uploader(
    "Choose a ZIP file",
    type=["zip"],
)

if uploaded_file is not None:
    try:
        df, metadata_text, mot_bytes, internal_path = read_mot_from_zip(
            uploaded_file.getvalue()
        )

        st.subheader("Uploaded MOT Preview", anchor=False)
        st.caption(f"File found: {internal_path}")
        st.write(f"Rows: {len(df)} | Columns: {len(df.columns)}")
        st.dataframe(df)

        # Metadata is not part of the numeric table, but is retained and visible.
        with st.expander("Original MOT metadata header"):
            st.code(metadata_text, language="text")

        total = calculate_sum(df)
        st.subheader("Your Score", anchor=False)
        st.metric("Sum of all numbers", total)

        if st.button("Submit to Leaderboard"):
            if not username.strip():
                st.error("Please enter a username.")
            else:
                file_hash = hashlib.sha256(mot_bytes).hexdigest()
                try:
                    existing = (
                        supabase.table("leaderboard")
                        .select("id")
                        .eq("file_hash", file_hash)
                        .limit(1)
                        .execute()
                    )

                    if existing.data:
                        st.info("This MOT file was already submitted.")
                    else:
                        supabase.table("leaderboard").insert({
                            "username": username.strip(),
                            "filename": uploaded_file.name,
                            "file_hash": file_hash,
                            "total": total,
                        }).execute()
                        st.success("Score added to leaderboard!")
                except Exception as exc:
                    # Unique constraint also protects against simultaneous submissions.
                    if str(getattr(exc, "code", "")) == "23505":
                        st.info("This MOT file was already submitted.")
                    else:
                        logger.exception("Supabase submission failed")
                        st.error(
                            "Unable to submit your score right now. "
                            "Please try again later."
                        )

    except FileNotFoundError as exc:
        st.error(str(exc))
    except BadZipFile:
        st.error("The uploaded file is not a valid ZIP archive.")
    except UnicodeError:
        st.error("Walk1.mot could not be decoded as UTF-8 text.")
    except pd.errors.EmptyDataError:
        st.error("Walk1.mot has no readable table columns or data.")
    except pd.errors.ParserError:
        st.error("Walk1.mot has an invalid or inconsistent data table.")
    except ValueError as exc:
        st.error(str(exc))
    except (RuntimeError, EOFError, OSError):
        logger.exception("Unable to extract MOT from ZIP")
        st.error("The ZIP could not be read or contains a damaged MOT entry.")


# ----------------------------------
# 6. Display leaderboard
# ----------------------------------

st.header("Leaderboard", anchor=False)
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
        leaderboard.columns = ["Username", "File Name", "Total Sum"]
        leaderboard["Rank"] = leaderboard["Total Sum"].rank(method="min", ascending=False).astype(int)
        leaderboard = leaderboard.sort_values(
            by=["Total Sum", "Username"],
            ascending=[False, True],
            key=lambda col: col.str.casefold() if col.name == "Username" else col,
            kind="stable",
        )
        leaderboard = leaderboard.set_index("Rank")
        st.dataframe(
            leaderboard,
            width="stretch",
            column_config={
                "Username": st.column_config.TextColumn(
                    width=200
                ),
                "File Name": st.column_config.TextColumn(
                    width=200
                ),
                "Total Sum": st.column_config.NumberColumn(
                    width=200
                ),
            }
        )
    else:
        st.write("No MOT files submitted yet.")
except Exception:
    logger.exception("Supabase leaderboard retrieval failed")
    st.error(
        "Unable to load the leaderboard right now. "
        "Please refresh the page and try again."
    )
