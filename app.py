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
    # Do not include extra spaces around commas.
    cond = f"username.ilike.%{query}%,full_name.ilike.%{query}%"
    res = auth.table("profiles")\
        .select("id, username, full_name, avatar_url")\
        .or_(cond)\
        .neq("id", me)\
        .limit(20)\
        .execute()
    return res.data or []

@st.cache_data(ttl=5)
def my_friend_requests():
    incoming = auth.table("friends")\
        .select("id, requester_id, addressee_id, status, created_at")\
        .eq("addressee_id", me).eq("status", "pending").order("created_at").execute().data or []
    outgoing = auth.table("friends")\
        .select("id, requester_id, addressee_id, status, created_at")\
        .eq("requester_id", me).eq("status", "pending").order("created_at").execute().data or []
    return incoming, outgoing

@st.cache_data(ttl=10)
def my_friends():
    acc1 = auth.table("friends").select("requester_id, addressee_id").eq("requester_id", me).eq("status", "accepted").execute().data or []
    acc2 = auth.table("friends").select("requester_id, addressee_id").eq("addressee_id", me).eq("status", "accepted").execute().data or []
    ids = set()
    for r in acc1: ids.add(r["addressee_id"])
    for r in acc2: ids.add(r["requester_id"])
    ids.discard(me)  # safety
    profs = []
    if ids:
        profs = auth.table("profiles").select("id, username, full_name, avatar_url").in_("id", list(ids)).execute().data or []
    return profs

def usernames_for_ids(ids):
    ids = list(ids or [])
    if not ids:
        return {}
    rows = auth.table("profiles").select("id, username").in_("id", ids).execute().data or []
    return {r["id"]: (r["username"] or r["id"][:8]) for r in rows}

def send_friend_request(other_id: str):
    if other_id == me:
        st.warning("You can’t add yourself.")
        return
    try:
        auth.table("friends").insert({
            "requester_id": me,
            "addressee_id": other_id,
            "status": "pending",
        }).execute()
    except APIError as e:
        # Likely unique constraint (duplicate request) or RLS
        st.error("Could not send request (already sent, already friends, or not allowed).")

def update_request_status(req_id: int, new_status: str):
    try:
        auth.table("friends").update({"status": new_status}).eq("id", req_id).execute()
    except APIError:
        st.error("Could not update request. Check permissions / RLS.")

def get_or_create_conversation(other_id: str) -> str:
    if other_id == me:
        st.error("You can’t start a conversation with yourself.")
        raise RuntimeError("self-conversation blocked in UI")
    try:
        resp = auth.rpc("get_or_create_conversation", {"a": me, "b": other_id}).execute()
        if not resp.data:
            raise RuntimeError("RPC returned no data")
        return resp.data
    except APIError as e:
        # Most common: function not SECURITY DEFINER or RLS blocking inserts
        st.error(
            "Couldn’t open/create the conversation. "
            "Confirm the SQL function is SECURITY DEFINER, lives in the public schema, "
            "and RLS isn’t forced on conversation_participants."
        )
        # Uncomment for local debugging:
        # st.exception(e)
        raise

@st.cache_data(ttl=2)
def load_messages(conversation_id: str, limit: int = 200):
    res = auth.table("direct_messages")\
        .select("id, sender_id, content, created_at")\
        .eq("conversation_id", conversation_id)\
        .order("created_at")\
        .limit(limit)\
        .execute()
    return res.data or []

def send_message(conversation_id: str, text: str):
    text = (text or "").strip()
    if not text:
        return
    try:
        auth.table("direct_messages").insert({
            "conversation_id": conversation_id,
            "sender_id": me,
            "content": text
        }).execute()
    except APIError:
        st.error("Failed to send message (RLS or grants).")

# ----------------------------
# UI
# ----------------------------
tabs = st.tabs(["Find Users", "Friend Requests", "Friends & Chats"])

# --- Find Users
with tabs[0]:
    st.subheader("Find Users")
    q = st.text_input("Search by username or full name", "", placeholder="e.g. chris, jane doe")
    results = search_users(q) if q else []
    if results:
        for r in results:
            if r["id"] == me:
                continue
            col1, col2 = st.columns([3,1])
            with col1:
                name = r.get("full_name") or r.get("username") or r["id"][:8]
                handle = r.get("username") or r["id"][:8]
                st.write(f"**{name}**  \n`@{handle}`")
            with col2:
                if st.button("Add Friend", key=f"add_{r['id']}"):
                    send_friend_request(r["id"])
                    st.success("Friend request sent (if allowed).")
                    st.cache_data.clear()

# --- Friend Requests
with tabs[1]:
    st.subheader("Friend Requests")
    incoming, outgoing = my_friend_requests()

    st.markdown("**Incoming**")
    if not incoming:
        st.caption("No incoming requests.")
    for req in incoming:
        rid = req["id"]; from_id = req["requester_id"]
        prof = auth.table("profiles").select("username, full_name").eq("id", from_id).limit(1).execute().data
        name = (prof[0]["full_name"] or prof[0]["username"]) if prof else from_id[:8]
        uname = (prof[0]["username"] if prof else from_id[:8])
        c1, c2, c3 = st.columns([3,1,1])
        c1.write(f"**{name}**  \n`@{uname}`")
        if c2.button("Accept", key=f"acc_{rid}"):
            update_request_status(rid, "accepted")
            st.success("Accepted.")
            st.cache_data.clear()
        if c3.button("Decline", key=f"dec_{rid}"):
            update_request_status(rid, "declined")
            st.info("Declined.")
            st.cache_data.clear()

    st.markdown("---")
    st.markdown("**Outgoing**")
    if not outgoing:
        st.caption("No outgoing requests.")
    for req in outgoing:
        to_id = req["addressee_id"]
        prof = auth.table("profiles").select("username, full_name").eq("id", to_id).limit(1).execute().data
        name = (prof[0]["full_name"] or prof[0]["username"]) if prof else to_id[:8]
        uname = (prof[0]["username"] if prof else to_id[:8])
        st.write(f"Sent to **{name}**  (`@{uname}`) — *pending*")

# --- Friends & Chats
with tabs[2]:
    st.subheader("Friends & Chats")
    friends = my_friends()
    if not friends:
        st.caption("No friends yet — add some from the Find Users tab.")
        st.stop()

    # Picker
    friend_label_map = {f["id"]: (f.get("full_name") or f.get("username") or f["id"][:8]) for f in friends}
    friend_ids = [fid for fid in friend_label_map.keys() if fid != me]
    if not friend_ids:
        st.caption("No friends available to chat.")
        st.stop()

    # Persist selected friend across reruns
    default_idx = 0
    if "chat_with" in st.session_state and st.session_state["chat_with"] in friend_ids:
        default_idx = friend_ids.index(st.session_state["chat_with"])

    selected_id = st.selectbox(
        "Choose a friend to chat with",
        friend_ids,
        index=min(default_idx, len(friend_ids)-1),
        format_func=lambda i: f"{friend_label_map[i]} (@{next((f['username'] for f in friends if f['id']==i), i[:8])})"
    )
    st.session_state["chat_with"] = selected_id

    # Conversation
    try:
        convo_id = get_or_create_conversation(selected_id)
    except Exception:
        st.stop()

    cols = st.columns([4,1])
    with cols[0]:
        st.caption(f"Conversation: `{convo_id}`")
    with cols[1]:
        if st.button("Refresh"):
            st.cache_data.clear()

    msgs = load_messages(convo_id)
    id_map = usernames_for_ids({m["sender_id"] for m in msgs} | {me, selected_id})

    st.divider()
    st.markdown("**Messages**")
    if not msgs:
        st.caption("No messages yet. Say hi!")

    for m in msgs:
        mine = (m["sender_id"] == me)
        who = "You" if mine else f"@{id_map.get(m['sender_id'], m['sender_id'][:8])}"
        ts = datetime.fromisoformat(m["created_at"].replace("Z","+00:00"))\
             .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        bubble = "🟦" if mine else "🟨"
        st.markdown(f"{bubble} **{who}** · {ts}\n\n{m['content']}")
        st.write("---")

    # Composer
    with st.form("composer", clear_on_submit=True):
        text = st.text_area("Message", placeholder="Type a message…", height=80, max_chars=2000)
        sent = st.form_submit_button("Send", type="primary")
        if sent and text.strip():
            send_message(convo_id, text)
            time.sleep(0.1)
            st.cache_data.clear()
            st.experimental_rerun()
