#!/usr/bin/env python3
"""
Slackclone with Supabase + Streamlit
Features:
- GitHub auth via streamlit-supabase-auth
- Profile bootstrap with unique usernames
- Friends (search, requests, list)
- Conversations (DMs, group-ready)
- Messages with optimistic UI
"""

import os
import re
import random
import time
import html as py_html
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client
from streamlit_supabase_auth import login_form, logout_button
from streamlit.components.v1 import html

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Slackclone", page_icon="💬", layout="wide")
st.title("💬 Slackclone")

SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("Missing Supabase credentials")
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
    st.info("Please sign in")
    session = login_form(
        url=SUPABASE_URL,
        apiKey=SUPABASE_ANON_KEY,
        providers=["github"],
    )
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
# Username bootstrap
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
        auth_cli.table("profiles").insert(
            {"id": me, "username": handle, "full_name": full_name, "avatar_url": avatar_url}
        ).execute()
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
# Helpers
# ----------------------------
@st.cache_data(ttl=10)
def search_users(query: str):
    if not query:
        return []
    res = (
        auth.table("profiles")
        .select("id, username, full_name, avatar_url")
        .or_(f"username.ilike.%{query}%,full_name.ilike.%{query}%")
        .neq("id", me)
        .limit(20)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=5)
def my_friend_requests():
    incoming = (
        auth.table("friends")
        .select("id, requester_id, addressee_id, status, created_at")
        .eq("addressee_id", me)
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
        or []
    )
    outgoing = (
        auth.table("friends")
        .select("id, requester_id, addressee_id, status, created_at")
        .eq("requester_id", me)
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
        or []
    )
    return incoming, outgoing


@st.cache_data(ttl=10)
def my_friends():
    acc1 = (
        auth.table("friends")
        .select("requester_id, addressee_id")
        .eq("requester_id", me)
        .eq("status", "accepted")
        .execute()
        .data
        or []
    )
    acc2 = (
        auth.table("friends")
        .select("requester_id, addressee_id")
        .eq("addressee_id", me)
        .eq("status", "accepted")
        .execute()
        .data
        or []
    )
    ids = set()
    for r in acc1:
        ids.add(r["addressee_id"])
    for r in acc2:
        ids.add(r["requester_id"])
    profs = []
    if ids:
        profs = (
            auth.table("profiles")
            .select("id, username, full_name, avatar_url")
            .in_("id", list(ids))
            .execute()
            .data
            or []
        )
    return profs


def usernames_for_ids(ids):
    if not ids:
        return {}
    rows = auth.table("profiles").select("id, username").in_("id", list(ids)).execute().data or []
    return {r["id"]: (r["username"] or r["id"][:8]) for r in rows}


def send_friend_request(other_id: str):
    auth.table("friends").insert({"requester_id": me, "addressee_id": other_id, "status": "pending"}).execute()


def update_request_status(req_id: int, new_status: str):
    auth.table("friends").update({"status": new_status}).eq("id", req_id).execute()


def get_or_create_conversation(other_id: str) -> str:
    if other_id == me:
        st.error("You can’t start a conversation with yourself.")
        raise RuntimeError("self-conversation blocked in UI")
    resp = auth.rpc("get_or_create_conversation", {"a": me, "b": other_id}).execute()
    if not resp.data:
        raise RuntimeError("RPC returned no data")
    return resp.data


@st.cache_data(ttl=2)
def load_messages(conversation_id: str, limit: int = 200):
    res = (
        auth.table("direct_messages")
        .select("id, sender_id, content, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return res.data or []


def send_message(conversation_id: str, text: str):
    text = (text or "").strip()
    if not text:
        return
    auth.table("direct_messages").insert({"conversation_id": conversation_id, "sender_id": me, "content": text}).execute()


# ----------------------------
# Layout
# ----------------------------
col_left, col_main = st.columns([1, 3])

# --- Friends / Conversations
with col_left:
    st.subheader("👥 Friends & Conversations")

    q = st.text_input("Find user", "", placeholder="username or name")
    results = search_users(q) if q else []
    if results:
        st.caption("Search Results")
        for r in results:
            name = r.get("full_name") or r.get("username") or r["id"][:8]
            if st.button(f"Add @{r.get('username')}", key=f"add_{r['id']}"):
                send_friend_request(r["id"])
                st.success("Request sent")
                st.cache_data.clear()
            else:
                st.write(f"**{name}**  \n@{r.get('username') or r['id'][:8]}")

    st.markdown("---")
    st.subheader("Requests")
    incoming, outgoing = my_friend_requests()
    if incoming:
        for req in incoming:
            from_id = req["requester_id"]
            uname = usernames_for_ids([from_id]).get(from_id, from_id[:8])
            if st.button(f"Accept @{uname}", key=f"acc_{req['id']}"):
                update_request_status(req["id"], "accepted")
                st.cache_data.clear()
            if st.button(f"Decline @{uname}", key=f"dec_{req['id']}"):
                update_request_status(req["id"], "declined")
                st.cache_data.clear()
    else:
        st.caption("No incoming requests")

    if outgoing:
        st.caption("Outgoing:")
        for req in outgoing:
            uname = usernames_for_ids([req["addressee_id"]]).get(req["addressee_id"], req["addressee_id"][:8])
            st.write(f"Sent to @{uname} (pending)")

    st.markdown("---")
    st.subheader("Friends")
    friends = my_friends()
    if friends:
        friend_map = {f["id"]: f.get("username") or f["id"][:8] for f in friends}
        friend_ids = list(friend_map.keys())

        current = st.session_state.get("chat_with")
        default_idx = friend_ids.index(current) if current in friend_ids else 0

        selected_id = st.selectbox(
            "Choose friend",
            friend_ids,
            index=default_idx,
            format_func=lambda i: f"@{friend_map[i]}",
        )
        st.session_state["chat_with"] = selected_id
    else:
        st.caption("No friends yet")
        selected_id = None

# --- Messages
with col_main:
    st.subheader("💬 Messages")

    if selected_id:
        convo_id = get_or_create_conversation(selected_id)
        st.caption(f"Conversation: `{convo_id}`")

        msgs = load_messages(convo_id)
        id_map = usernames_for_ids({m["sender_id"] for m in msgs} | {me})

        # Scrollable HTML block
        items = []
        for m in msgs:
            mine = m["sender_id"] == me
            who = "You" if mine else f"@{id_map.get(m['sender_id'], m['sender_id'][:8])}"
            ts = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            bubble = "🟦" if mine else "🟨"
            items.append(
                f"""
              <div class="msg {'mine' if mine else 'theirs'}">
                <div class="meta">{bubble} <strong>{py_html.escape(who)}</strong> · {py_html.escape(ts)}</div>
                <div class="body">{py_html.escape(m['content'])}</div>
              </div>
            """
            )

        messages_html = f"""
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8" />
        <style>
          body {{ margin:0; font-family: system-ui, sans-serif; }}
          .wrap {{
            height: 100%;
            max-height: 520px;
            overflow-y: auto;
            padding: 12px 16px;
            background: #fafafa;
            border: 1px solid #e6e6e6;
            border-radius: 12px;
          }}
          .msg {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
          .msg:last-child {{ border-bottom: none; }}
          .meta {{ font-size: 12px; color: #555; margin-bottom: 4px; }}
          .body {{ white-space: pre-wrap; word-wrap: break-word; }}
          .mine .meta {{ color: #245; }}
          .theirs .meta {{ color: #542; }}
        </style>
        </head>
        <body>
          <div class="wrap">
            {''.join(items) if items else '<div style="color:#666">No messages yet. Say hi!</div>'}
          </div>
        </body>
        </html>
        """
        html(messages_html, height=540, scrolling=True)

        # Composer
        with st.form("composer", clear_on_submit=True):
            text = st.text_area("Message", placeholder="Type a message…", height=80, max_chars=2000)
            sent = st.form_submit_button("Send", type="primary")
            if sent and text.strip():
                send_message(convo_id, text)
                time.sleep(0.1)
                st.cache_data.clear()
