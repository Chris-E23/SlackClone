# pages/10_Friends_and_Messages.py
import os
import time
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Friends & Messages", page_icon="💬", layout="wide")
st.title("💬 Friends & Messages")

# ---- Reuse your env/secrets
SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("Missing Supabase credentials")
    st.stop()

@st.cache_resource
def base_client():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = base_client()

# ---- Require auth (session provided by your main page using streamlit_supabase_auth)
session = st.session_state.get("session")
if not session or not session.get("user"):
    st.info("Please sign in to use friends and messaging.")
    st.stop()

user = session["user"]
me = user["id"]

@st.cache_resource(show_spinner=False)
def authed_client(access_token: str, refresh_token: str):
    cli = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    cli.auth.set_session(access_token, refresh_token or "")
    return cli

auth = authed_client(session.get("access_token"), session.get("refresh_token"))

# ---------- Helpers

def ensure_profile_row():
    # On first login you might want to insert your own profile row
    prof = auth.table("profiles").select("id").eq("id", me).limit(1).execute().data
    if not prof:
        username_guess = (user.get("user_metadata", {}) or {}).get("user_name") or user.get("email", "").split("@")[0]
        full_name = (user.get("user_metadata", {}) or {}).get("full_name")
        auth.table("profiles").insert({
            "id": me,
            "username": username_guess,
            "full_name": full_name,
            "avatar_url": (user.get("user_metadata", {}) or {}).get("avatar_url"),
        }).execute()

ensure_profile_row()

@st.cache_data(ttl=10)
def search_users(query: str):
    if not query:
        return []
    # simple ilike match on username or full_name
    res = auth.table("profiles")\
        .select("id, username, full_name, avatar_url")\
        .or_(f"username.ilike.%{query}%,full_name.ilike.%{query}%")\
        .neq("id", me)\
        .limit(20)\
        .execute()
    return res.data or []

@st.cache_data(ttl=5)
def my_friend_requests():
    # incoming pending requests for me
    incoming = auth.table("friends")\
        .select("id, requester_id, addressee_id, status, created_at")\
        .eq("addressee_id", me).eq("status", "pending").order("created_at").execute().data or []
    # outgoing pending
    outgoing = auth.table("friends")\
        .select("id, requester_id, addressee_id, status, created_at")\
        .eq("requester_id", me).eq("status", "pending").order("created_at").execute().data or []
    return incoming, outgoing

@st.cache_data(ttl=10)
def my_friends():
    # accepted friendships: either direction, give me other user ids
    acc1 = auth.table("friends").select("requester_id, addressee_id").eq("requester_id", me).eq("status", "accepted").execute().data or []
    acc2 = auth.table("friends").select("requester_id, addressee_id").eq("addressee_id", me).eq("status", "accepted").execute().data or []
    ids = set()
    for r in acc1: ids.add(r["addressee_id"])
    for r in acc2: ids.add(r["requester_id"])
    profs = []
    if ids:
        profs = auth.table("profiles").select("id, username, full_name, avatar_url").in_("id", list(ids)).execute().data or []
    return profs

def get_or_create_conversation(other_id: str) -> str:
    resp = auth.rpc("get_or_create_conversation", {"a": me, "b": other_id}).execute()
    if not resp.data:
        raise RuntimeError("Could not create conversation")
    return resp.data

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
    auth.table("direct_messages").insert({
        "conversation_id": conversation_id,
        "sender_id": me,
        "content": text
    }).execute()

def send_friend_request(other_id: str):
    auth.table("friends").insert({
        "requester_id": me,
        "addressee_id": other_id,
        "status": "pending",
    }).execute()

def update_request_status(req_id: int, new_status: str):
    auth.table("friends").update({"status": new_status}).eq("id", req_id).execute()

# ---------- UI

tabs = st.tabs(["Find Users", "Friend Requests", "Friends & Chats"])

with tabs[0]:
    st.subheader("Find Users")
    q = st.text_input("Search by username or full name", "", placeholder="e.g. chris, jane doe")
    results = search_users(q) if q else []
    if results:
        for r in results:
            col1, col2 = st.columns([3,1])
            with col1:
                name = r.get("full_name") or r.get("username") or r["id"][:8]
                st.write(f"**{name}**  \n`{r['id']}`")
            with col2:
                if st.button("Add Friend", key=f"add_{r['id']}"):
                    send_friend_request(r["id"])
                    st.success("Friend request sent.")
                    st.cache_data.clear()

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
        c1, c2, c3 = st.columns([3,1,1])
        c1.write(f"**{name}**  \n`{from_id}`")
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
        st.write(f"Sent to **{name}**  (`{to_id}`) — *pending*")

with tabs[2]:
    st.subheader("Friends & Chats")

    friends = my_friends()
    if not friends:
        st.caption("No friends yet — add some from the Find Users tab.")
        st.stop()

    # Choose a friend
    friend_label_map = {
        f["id"]: (f.get("full_name") or f.get("username") or f["id"][:8])
        for f in friends
    }
    friend_ids = list(friend_label_map.keys())
    default_idx = 0
    if "chat_with" in st.session_state and st.session_state["chat_with"] in friend_ids:
        default_idx = friend_ids.index(st.session_state["chat_with"])

    selected_id = st.selectbox(
        "Choose a friend to chat with",
        friend_ids,
        index=default_idx,
        format_func=lambda i: friend_label_map[i]
    )
    st.session_state["chat_with"] = selected_id

    # Ensure there is a conversation
    convo_id = get_or_create_conversation(selected_id)

    # Messages list (simple polling; refresh button)
    cols = st.columns([4,1])
    with cols[0]:
        st.markdown(f"**Conversation:** `{convo_id}`")
    with cols[1]:
        if st.button("Refresh"):
            st.cache_data.clear()

    msgs = load_messages(convo_id)

    st.divider()
    st.markdown("**Messages**")
    if not msgs:
        st.caption("No messages yet. Say hi!")

    for m in msgs:
        mine = (m["sender_id"] == me)
        who = "You" if mine else friend_label_map.get(m["sender_id"], m["sender_id"][:8])
        ts = datetime.fromisoformat(m["created_at"].replace("Z","+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        st.markdown(f"{'🟦' if mine else '🟨'} **{who}** · {ts}\n\n{m['content']}")
        st.write("---")

    # Composer
    with st.form("composer", clear_on_submit=True):
        text = st.text_area("Message", placeholder="Type a message…", height=80, max_chars=2000)
        sent = st.form_submit_button("Send", type="primary")
        if sent and text.strip():
            send_message(convo_id, text)
            # light debounce
            time.sleep(0.1)
            st.cache_data.clear()
            st.experimental_rerun()
