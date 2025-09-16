# pages/10_Friends_and_Messages.py
import os
import re
import uuid
import random
import time
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client
from postgrest import APIError
from streamlit_supabase_auth import login_form, logout_button
from streamlit_autorefresh import st_autorefresh  # 👈 auto-refresh

# ----------------------------
# Config & base client
# ----------------------------
st.set_page_config(page_title="Friends & Messages", page_icon="💬", layout="wide")
st.title("💬 Friends & Messages")

# Auto-refresh every 5 seconds (adjust interval as needed)
st_autorefresh(interval=5000, key="chat_autorefresh")

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
# Auth
# ----------------------------
session = st.session_state.get("session")
if not session:
    st.info("Please sign in to use friends and messaging.")
    session = login_form(url=SUPABASE_URL, apiKey=SUPABASE_ANON_KEY, providers=["github"])
    if session:
        st.session_state["session"] = session

if not session or not session.get("user"):
    st.stop()

user = session["user"]
me = user["id"]
access_token = session.get("access_token")
refresh_token = session.get("refresh_token", "")

logout_button(apiKey=SUPABASE_ANON_KEY)

@st.cache_resource(show_spinner=False)
def authed_client(access_token: str, refresh_token: str):
    cli = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    cli.auth.set_session(access_token, refresh_token or "")
    return cli

auth = authed_client(access_token, refresh_token)

# ----------------------------
# Unique username bootstrap
# ----------------------------
def _slugify(s: str, fallback: str) -> str:
    if not s:
        return fallback
    s = s.strip().lower().replace("-", "_")
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
        auth_cli.table("profiles").insert({
            "id": me,
            "username": handle,
            "full_name": (user_meta or {}).get("full_name"),
            "avatar_url": (user_meta or {}).get("avatar_url")
        }).execute()
        return {"id": me, "username": handle, "full_name": (user_meta or {}).get("full_name"), "avatar_url": (user_meta or {}).get("avatar_url")}

    current = (prof.get("username") or "").strip()
    if not current:
        handle = _next_available_username(auth_cli, base)
        auth_cli.table("profiles").update({"username": handle}).eq("id", me).execute()
        prof["username"] = handle
    return prof

profile = ensure_profile_with_username(auth, me, user.get("user_metadata", {}) or {})
st.info(f"Signed in as **@{profile['username']}**")

# ----------------------------
# Optimistic messaging state
# ----------------------------
if "optimistic" not in st.session_state:
    # { conversation_id: [ {id, sender_id, content, created_at, status} ] }
    st.session_state["optimistic"] = {}

def _optimistic_list(cid: str):
    return st.session_state["optimistic"].setdefault(cid, [])

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def add_optimistic_message(cid: str, sender_id: str, content: str):
    temp = {
        "id": f"tmp-{uuid.uuid4()}",
        "sender_id": sender_id,
        "content": content,
        "created_at": _now_iso(),
        "status": "sending",  # sending | sent | failed
    }
    _optimistic_list(cid).append(temp)
    return temp

def mark_optimistic(cid: str, temp_id: str, new_status: str):
    lst = _optimistic_list(cid)
    for m in lst:
        if m["id"] == temp_id:
            m["status"] = new_status
            return

def drop_delivered_optimistic(cid: str, server_msgs: list):
    """
    Hide optimistic copies once an equivalent server message appears.
    Heuristic: same sender + same content within 10s.
    """
    lst = _optimistic_list(cid)
    keep = []
    for om in lst:
        if om["status"] == "failed":
            keep.append(om)
            continue
        om_ts = datetime.fromisoformat(om["created_at"].replace("Z", "+00:00"))
        matched = False
        for sm in server_msgs:
            if sm["sender_id"] != om["sender_id"]:
                continue
            if (sm["content"] or "").strip() != (om["content"] or "").strip():
                continue
            sm_ts = datetime.fromisoformat(sm["created_at"].replace("Z", "+00:00"))
            if abs((sm_ts - om_ts).total_seconds()) <= 10:
                matched = True
                break
        if not matched:
            keep.append(om)
    st.session_state["optimistic"][cid] = keep

def combined_messages(cid: str, server_msgs: list):
    drop_delivered_optimistic(cid, server_msgs)
    merged = list(server_msgs) + list(_optimistic_list(cid))
    def _ts(m):
        return datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
    return sorted(merged, key=_ts)

# ----------------------------
# Helpers: friends & chat
# ----------------------------
@st.cache_data(ttl=10)
def search_users(query: str):
    if not query:
        return []
    cond = f"username.ilike.%{query}%,full_name.ilike.%{query}%"
    res = auth.table("profiles").select("id, username, full_name, avatar_url").or_(cond).neq("id", me).limit(20).execute()
    return res.data or []

@st.cache_data(ttl=5)
def my_friend_requests():
    incoming = auth.table("friends").select("id, requester_id, addressee_id, status, created_at")\
        .eq("addressee_id", me).eq("status", "pending").order("created_at").execute().data or []
    outgoing = auth.table("friends").select("id, requester_id, addressee_id, status, created_at")\
        .eq("requester_id", me).eq("status", "pending").order("created_at").execute().data or []
    return incoming, outgoing

@st.cache_data(ttl=10)
def my_friends():
    acc1 = auth.table("friends").select("requester_id, addressee_id").eq("requester_id", me).eq("status", "accepted").execute().data or []
    acc2 = auth.table("friends").select("requester_id, addressee_id").eq("addressee_id", me).eq("status", "accepted").execute().data or []
    ids = set()
    for r in acc1: ids.add(r["addressee_id"])
    for r in acc2: ids.add(r["requester_id"])
    ids.discard(me)
    if not ids:
        return []
    return auth.table("profiles").select("id, username, full_name, avatar_url").in_("id", list(ids)).execute().data or []

@st.cache_data(ttl=10)
def my_added_pending():
    rows = auth.table("friends").select("addressee_id").eq("requester_id", me).eq("status", "pending").execute().data or []
    ids = [r["addressee_id"] for r in rows]
    if not ids:
        return []
    return auth.table("profiles").select("id, username, full_name, avatar_url").in_("id", ids).execute().data or []

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
        # Idempotent; auto-accepts if reverse request exists
        auth.rpc("upsert_friend_request", {"a": me, "b": other_id}).execute()
    except APIError:
        st.error("Could not add friend (check RLS / grants).")

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
    except APIError:
        st.error(
            "Couldn’t open/create the conversation. Ensure the RPC is SECURITY DEFINER, "
            "in schema public, and FORCE RLS is OFF on conversation_participants."
        )
        raise

@st.cache_data(ttl=2)
def load_messages(conversation_id: str, limit: int = 200):
    res = auth.table("direct_messages").select("id, sender_id, content, created_at")\
        .eq("conversation_id", conversation_id).order("created_at").limit(limit).execute()
    return res.data or []

def send_message_to_db(conversation_id: str, text: str) -> bool:
    try:
        auth.table("direct_messages").insert({
            "conversation_id": conversation_id,
            "sender_id": me,
            "content": text.strip()
        }).execute()
        return True
    except APIError:
        return False

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
                    st.success("Friend added (pending until accepted).")
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
    added_pending = my_added_pending()

    if added_pending:
        with st.expander("Added (pending)"):
            for p in added_pending:
                label = p.get("full_name") or p.get("username") or p["id"][:8]
                st.write(f"⏳ {label} (@{p.get('username') or p['id'][:8]}) — awaiting acceptance")

    if not friends:
        st.caption("No accepted friends yet — add some from the Find Users tab.")
        st.stop()

    friend_label_map = {f["id"]: (f.get("full_name") or f.get("username") or f["id"][:8]) for f in friends}
    friend_ids = [fid for fid in friend_label_map.keys() if fid != me]
    if not friend_ids:
        st.caption("No friends available to chat.")
        st.stop()

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

    # Conversation id
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

    # Server messages
    server_msgs = load_messages(convo_id)

    # Composer with optimistic send
    with st.form("composer", clear_on_submit=True):
        text = st.text_area("Message", placeholder="Type a message…", height=80, max_chars=2000, key="composer_text")
        sent = st.form_submit_button("Send", type="primary")
        if sent and text.strip():
            tmp = add_optimistic_message(convo_id, me, text.strip())  # show immediately
            ok = send_message_to_db(convo_id, text)                    # push to DB
            mark_optimistic(convo_id, tmp["id"], "sent" if ok else "failed")
            st.cache_data.clear()                                      # next rerun shows server echo

    # Merge server + optimistic for display
    msgs = combined_messages(convo_id, server_msgs)
    id_map = usernames_for_ids({m["sender_id"] for m in msgs} | {me, selected_id})

    st.divider()
    st.markdown("**Messages**")
    if not msgs:
        st.caption("No messages yet. Say hi!")

    for m in msgs:
        mine = (m["sender_id"] == me)
        who = "You" if mine else f"@{id_map.get(m['sender_id'], m['sender_id'][:8])}"
        ts = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))\
             .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        bubble = "🟦" if mine else "🟨"
        status = m.get("status")  # only for optimistic entries
        badge = " ⏳" if status == "sending" else (" ✅" if status == "sent" else (" ⚠️" if status == "failed" else ""))

        st.markdown(f"{bubble} **{who}** · {ts}{badge}\n\n{m['content']}")

        if status == "failed" and mine:
            cols2 = st.columns([1,1,6])
            with cols2[0]:
                if st.button("Retry", key=f"retry_{m['id']}"):
                    ok = send_message_to_db(convo_id, m["content"])
                    mark_optimistic(convo_id, m["id"], "sent" if ok else "failed")
                    st.cache_data.clear()
            with cols2[1]:
                if st.button("Dismiss", key=f"dismiss_{m['id']}"):
                    lst = _optimistic_list(convo_id)
                    st.session_state["optimistic"][convo_id] = [x for x in lst if x["id"] != m["id"]]
                    st.cache_data.clear()

        st.write("---")
