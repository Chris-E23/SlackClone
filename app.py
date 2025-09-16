# pages/10_Friends_and_Messages.py
import os
import re
import random
import time
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client
from postgrest import APIError
from streamlit_supabase_auth import login_form, logout_button

# ----------------------------
# Config & clients
# ----------------------------
st.set_page_config(page_title="Friends & Messages", page_icon="💬", layout="wide")
st.title("💬 Friends & Messages")

SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("Missing Supabase credentials.")
    st.stop()

@st.cache_resource
def base_client():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = base_client()

# ----------------------------
# Auth: get or create session
# ----------------------------
session = st.session_state.get("session")

if not session:
    st.info("Please sign in to use friends and messaging.")
    session = login_form(
        url=SUPABASE_URL,
        apiKey=SUPABASE_ANON_KEY,
        providers=["github"]
    )
    if session:
        st.session_state["session"] = session

if not session or not session.get("user"):
    st.stop()

# Session fields
user = session["user"]
me = user["id"]
access_token = session.get("access_token")
refresh_token = session.get("refresh_token", "")

# Optional: logout
logout_button(apiKey=SUPABASE_ANON_KEY)

@st.cache_resource(show_spinner=False)
def authed_client(access_token: str, refresh_token: str):
    cli = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    cli.auth.set_session(access_token, refresh_token or "")
    return cli

auth = authed_client(access_token, refresh_token)

# ----------------------------
# Username bootstrap (unique)
# ----------------------------
def _slugify(s: str, fallback: str) -> str:
    if not s:
        return fallback
    s = s.strip().lower()
    s = s.replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or fallback

def _rand_suffix(n=3) -> str:
    alphabet = "bcdfghjklmnpqrstvwxyz0123456789"
    return "".join(random.choice(alphabet) for _ in range(n))

def _username_available(auth_cli, handle: str) -> bool:
    res = auth_cli.table("profiles").select("id").eq("username", handle).limit(1).execute()
    return not bool(res.data)

def _next_available_username(auth_cli, base: str) -> str:
    if _username_available(auth_cli, base):
        return base
    for i in range(2, 20):
        cand = f"{base}{i}"
        if _username_available(auth_cli, cand):
            return cand
    for _ in range(50):
        cand = f"{base}{_rand_suffix(3)}"
        if _username_available(auth_cli, cand):
            return cand
    while True:
        cand = f"{base}{_rand_suffix(6)}"
        if _username_available(auth_cli, cand):
            return cand

def ensure_profile_with_username(auth_cli, me: str, user_meta: dict) -> dict:
    prof = auth_cli.table("profiles").select("id, username, full_name, avatar_url").eq("id", me).limit(1).execute().data
    prof = prof[0] if prof else None

    gh_handle = (user_meta or {}).get("preferred_username") or (user_meta or {}).get("user_name")
    email = (user_meta or {}).get("email")
    fallback = f"user_{me[:8]}"
    base = _slugify(gh_handle or (email.split("@")[0] if email else "") or "", fallback=fallback)
    if len(base) < 3:
        base = f"user_{me[:6]}"

    if not prof:
        handle = _next_available_username(auth_cli, base)
        full_name = (user_meta or {}).get("full_name")
        avatar_url = (user_meta or {}).get("avatar_url")
        auth_cli.table("profiles").insert({
            "id": me,
            "username": handle,
            "full_name": full_name,
            "avatar_url": avatar_url
        }).execute()
        return {"id": me, "username": handle, "full_name": full_name, "avatar_url": avatar_url}

    current = (prof.get("username") or "").strip()
    if not current:
        handle = _next_available_username(auth_cli, base)
        auth_cli.table("profiles").update({"username": handle}).eq("id", me).execute()
        prof["username"] = handle
    return prof

profile = ensure_profile_with_username(auth, me, user.get("user_metadata", {}) or {})
st.info(f"Signed in as **@{profile['username']}**")

# ----------------------------
# Friends & Messaging helpers
# ----------------------------
@st.cache_data(ttl=10)
def search_users(query: str):
    if not query:
        return []
    # NOTE: Supabase .or_ needs a single string with comma-separated conditions.
    # Do not include extra s
