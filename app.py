#!/usr/bin/env python3
"""
Slackclone with Supabase + Streamlit
- GitHub auth (streamlit-supabase-auth)
- Profile bootstrap with unique usernames
- Friends (search, requests, accept/decline)
- DMs + Group chats
- Optimistic messaging (⏳/✅/⚠️)
- 3-column layout: Left (friends & convos), Center (messages), Right (profile)
- Scrollable message panel (HTML iframe)
- Avatars via Supabase Storage (bucket 'avatars')
"""

import os
import re
import uuid
import random
import time
import mimetypes
import html as py_html
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client
from postgrest import APIError
from streamlit_supabase_auth import login_form, logout_button
from streamlit.components.v1 import html

# =========================
# Config
# =========================
st.set_page_config(page_title="Slackclone", page_icon="💬", layout="wide")
st.title("💬 Slackclone")

# Scrub access tokens in URL hash if present
html("""
<script>
  if (window.location.hash && window.location.hash.includes("access_token")) {
    history.replaceState(null, document.title, window.location.pathname + window.location.search);
  }
</script>
""", height=0)

SUPABASE_URL = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("Missing Supabase credentials")
    st.stop()

@st.cache_resource
def base_client():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = base_client()

# =========================
# Auth
# =========================
session = st.session_state.get("session")
if not session:
    st.info("Please sign in to use the app.")
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

# =========================
# Profile / unique username
# =========================
def _slugify(s: str, fallback: str) -> str:
    if not s: return fallback
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
    if _username_available(auth_cli, base): return base
    for i in range(2, 20):
        cand = f"{base}{i}"
        if _username_available(auth_cli, cand): return cand
    for _ in range(50):
        cand = f"{base}{_rand_suffix(3)}"
        if _username_available(auth_cli, cand): return cand
    while True:
        cand = f"{base}{_rand_suffix(6)}"
        if _username_available(auth_cli, cand): return cand

def ensure_profile_with_username(auth_cli, me: str, user_meta: dict) -> dict:
    prof = auth_cli.table("profiles").select("id, username, full_name, avatar_url").eq("id", me).limit(1).execute().data
    prof = prof[0] if prof else None

    gh_handle = (user_meta or {}).get("preferred_username") or (user_meta or {}).get("user_name")
    email = (user_meta or {}).get("email")
    fallback = f"user_{me[:8]}"
    base = _slugify(gh_handle or (email.split("@")[0] if email else "") or "", fallback=fallback)
    if len(base) < 3: base = f"user_{me[:6]}"

    if not prof:
        handle = _next_available_username(auth_cli, base)
        auth_cli.table("profiles").insert({
            "id": me,
            "username": handle,
            "full_name": (user_meta or {}).get("full_name"),
            "avatar_url": (user_meta or {}).get("avatar_url")
        }).execute()
        return {"id": me, "username": handle, "full_name": (user_meta or {}).get("full_name"), "avatar_url": (user_meta or {}).get("avatar_url")}

    if not (prof.get("username") or "").strip():
        handle = _next_available_username(auth_cli, base)
        auth_cli.table("profiles").update({"username": handle}).eq("id", me).execute()
        prof["username"] = handle
    return prof

profile = ensure_profile_with_username(auth, me, user.get("user_metadata", {}) or {})
st.caption(f"Signed in as **@{profile['username']}**")

# =========================
# Avatars (Storage helpers)
# =========================
def _file_ext(mimetype: str) -> str:
    return mimetypes.guess_extension(mimetype or "") or ".bin"

def upload_avatar_to_storage(auth_cli, user_id: str, file_bytes: bytes, mimetype: str) -> str:
    """
    Upload avatar to 'avatars' bucket and return a public URL.
    Uses a unique path, so no need for upsert headers (avoids header-type errors).
    """
    ext = _file_ext(mimetype or "application/octet-stream")
    path = f"{user_id}/avatar-{int(time.time())}{ext}"

    # IMPORTANT: don't pass boolean upsert; some clients turn it into a bad header.
    auth_cli.storage.from_("avatars").upload(
        path=path,
        file=file_bytes,
        file_options={
            "contentType": mimetype or "application/octet-stream",
            # "cacheControl": "3600",  # optional, must be a string if you add it
            # no upsert flag needed since path is unique
        },
    )

    # Public bucket: direct URL; for private, use create_signed_url instead.
    return auth_cli.storage.from_("avatars").get_public_url(path)

def avatar_img(url: str | None, size: int = 28) -> str:
    if not url:
        # simple placeholder circle
        return f"<div style='width:{size}px;height:{size}px;border-radius:50%;background:#ddd;display:inline-block;border:1px solid #eee;vertical-align:middle;'></div>"
    return (
        f"<img src='{py_html.escape(url)}' width='{size}' height='{size}' "
        f"style='border-radius:50%;object-fit:cover;vertical-align:middle;border:1px solid #eee'/>"
    )

# =========================
# Optimistic messaging
# =========================
if "optimistic" not in st.session_state:
    # { conversation_id: [ {id,temp|db, sender_id, content, created_at, status} ] }
    st.session_state["optimistic"] = {}

def _optimistic_list(cid: str):
    return st.session_state["optimistic"].setdefault(cid, [])

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def add_optimistic_message(cid: str, sender_id: str, content: str):
    msg = {
        "id": f"tmp-{uuid.uuid4()}",
        "sender_id": sender_id,
        "content": (content or "").strip(),
        "created_at": _now_iso(),
        "status": "sending",  # sending | sent | failed
    }
    _optimistic_list(cid).append(msg)
    return msg

def mark_optimistic(cid: str, temp_id: str, new_status: str):
    for m in _optimistic_list(cid):
        if m["id"] == temp_id:
            m["status"] = new_status
            return

def drop_delivered_optimistic(cid: str, server_msgs: list):
    """Hide optimistic copies once an equivalent server message arrives (same sender+content within 10s)."""
    lst = _optimistic_list(cid)
    keep = []
    for om in lst:
        if om["status"] == "failed":
            keep.append(om); continue
        om_ts = datetime.fromisoformat(om["created_at"].replace("Z", "+00:00"))
        matched = False
        for sm in server_msgs:
            if sm["sender_id"] != om["sender_id"]: continue
            if (sm["content"] or "").strip() != (om["content"] or "").strip(): continue
            sm_ts = datetime.fromisoformat(sm["created_at"].replace("Z", "+00:00"))
            if abs((sm_ts - om_ts).total_seconds()) <= 10:
                matched = True; break
        if not matched:
            keep.append(om)
    st.session_state["optimistic"][cid] = keep

def combined_messages(cid: str, server_msgs: list):
    drop_delivered_optimistic(cid, server_msgs)
    merged = list(server_msgs) + list(_optimistic_list(cid))
    def _ts(m): return datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
    return sorted(merged, key=_ts)

# =========================
# Data helpers
# =========================
@st.cache_data(ttl=10)
def search_users(query: str):
    if not query: return []
    res = auth.table("profiles").select("id, username, full_name, avatar_url")\
        .or_(f"username.ilike.%{query}%,full_name.ilike.%{query}%").neq("id", me).limit(20).execute()
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
    ids = {r["addressee_id"] for r in acc1} | {r["requester_id"] for r in acc2}
    ids.discard(me)
    if not ids: return []
    return auth.table("profiles").select("id, username, full_name, avatar_url").in_("id", list(ids)).execute().data or []

def usernames_for_ids(ids):
    ids = list(ids or [])
    if not ids: return {}
    rows = auth.table("profiles").select("id, username").in_("id", ids).execute().data or []
    return {r["id"]: (r["username"] or r["id"][:8]) for r in rows}

def profiles_for_ids(ids):
    ids = list(ids or [])
    if not ids: return {}
    rows = auth.table("profiles").select("id, username, avatar_url").in_("id", ids).execute().data or []
    return {r["id"]: r for r in rows}

def send_friend_request(other_id: str):
    try:
        # prefer idempotent RPC if you created it
        auth.rpc("upsert_friend_request", {"a": me, "b": other_id}).execute()
    except APIError:
        # fallback: simple insert
        auth.table("friends").insert({"requester_id": me, "addressee_id": other_id, "status": "pending"}).execute()

def update_request_status(req_id: int, new_status: str):
    auth.table("friends").update({"status": new_status}).eq("id", req_id).execute()

def get_or_create_conversation(other_id: str) -> str:
    if other_id == me:
        st.error("You can’t start a conversation with yourself.")
        raise RuntimeError("self-conversation blocked in UI")
    resp = auth.rpc("get_or_create_conversation", {"a": me, "b": other_id}).execute()
    if not resp.data: raise RuntimeError("RPC returned no data")
    return resp.data

def create_group(others: list[str], title: str) -> str:
    resp = auth.rpc("create_group_conversation", {"creator": me, "members": others, "conv_title": title}).execute()
    if not resp.data: raise RuntimeError("RPC returned no data")
    return resp.data

@st.cache_data(ttl=5)
def my_conversations():
    cps = auth.table("conversation_participants").select("conversation_id").eq("user_id", me).execute().data or []
    conv_ids = [c["conversation_id"] for c in cps]
    if not conv_ids: return []
    convs = auth.table("conversations").select("id, title, is_group, created_at, creator_id")\
        .in_("id", conv_ids).order("created_at", desc=True).execute().data or []
    members = auth.table("conversation_participants").select("conversation_id, user_id")\
        .in_("conversation_id", conv_ids).execute().data or []
    byconv = {}
    for m in members:
        byconv.setdefault(m["conversation_id"], []).append(m["user_id"])
    for c in convs:
        c["members"] = byconv.get(c["id"], [])
    return convs

def convo_label(convo, usernames_map):
    if convo.get("is_group"):
        name = (convo.get("title") or "").strip()
        if name:
            return f"👥 {name}"
        others = [u for u in convo.get("members", []) if u != me]
        handles = [f"@{usernames_map.get(u, u[:8])}" for u in others][:3]
        tail = "" if len(others) <= 3 else f" +{len(others)-3}"
        return "👥 " + ", ".join(handles) + tail
    # DM: show other
    others = [u for u in convo.get("members", []) if u != me]
    if not others: return "💬 DM"
    other = others[0]
    return f"💬 @{usernames_for_ids([other]).get(other, other[:8])}"

def convo_label_with_avatar(convo, usernames_map, profile_map) -> str:
    if convo.get("is_group"):
        others = [u for u in convo.get("members", [])]
        urls = [profile_map.get(u, {}).get("avatar_url") for u in others][:2]
        imgs = "".join(f"<span style='margin-right:-6px;'>{avatar_img(u, 18)}</span>" for u in urls if u)
        base = (convo.get("title") or "").strip()
        if not base:
            handles = [f"@{usernames_map.get(u, u[:8])}" for u in others if u != me][:3]
            tail = "" if len(others) <= 3 else f" +{len(others)-3}"
            base = ", ".join(handles) + tail if handles else "Group"
        return f"{imgs} <span>👥 {py_html.escape(base)}</span>"
    # DM
    others = [u for u in convo.get("members", []) if u != me]
    other = others[0] if others else None
    if not other:
        return f"{avatar_img(None, 18)} <span>💬 DM</span>"
    return f"{avatar_img(profile_map.get(other, {}).get('avatar_url'), 18)} <span>💬 @{py_html.escape(usernames_map.get(other, other[:8]))}</span>"

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

# =========================
# Layout: Left / Center / Right
# =========================
col_left, col_main, col_right = st.columns([1, 2, 1])

# ---------- Left: Friends & Conversations ----------
with col_left:
    st.subheader("👥 Friends & Conversations")

    # Find users
    with st.expander("Find users"):
        q = st.text_input("Search", "", placeholder="username or name")
        results = search_users(q) if q else []
        for r in results:
            if r["id"] == me: continue
            name = r.get("full_name") or r.get("username") or r["id"][:8]
            handle = r.get("username") or r["id"][:8]
            cols = st.columns([2,1])
            cols[0].markdown(
                f"{avatar_img(r.get('avatar_url'), 24)} **{py_html.escape(name)}**  \n`@{py_html.escape(handle)}`",
                unsafe_allow_html=True
            )
            if cols[1].button("Add", key=f"add_{r['id']}"):
                send_friend_request(r["id"])
                st.success("Request sent")
                st.cache_data.clear()

    # Friend requests
    with st.expander("Requests"):
        incoming, outgoing = my_friend_requests()
        st.markdown("**Incoming**")
        if not incoming:
            st.caption("None")
        for req in incoming:
            rid = req["id"]; from_id = req["requester_id"]
            prof = profiles_for_ids([from_id]).get(from_id, {})
            uname = prof.get("username") or from_id[:8]
            cols = st.columns([2,1,1])
            cols[0].markdown(f"{avatar_img(prof.get('avatar_url'), 20)} @{py_html.escape(uname)}", unsafe_allow_html=True)
            if cols[1].button("Accept", key=f"acc_{rid}"):
                update_request_status(rid, "accepted"); st.cache_data.clear()
            if cols[2].button("Decline", key=f"dec_{rid}"):
                update_request_status(rid, "declined"); st.cache_data.clear()
        st.markdown("---")
        st.markdown("**Outgoing**")
        if not outgoing:
            st.caption("None")
        for req in outgoing:
            to_id = req["addressee_id"]
            prof = profiles_for_ids([to_id]).get(to_id, {})
            uname = prof.get("username") or to_id[:8]
            st.caption(f"{avatar_img(prof.get('avatar_url'), 16)} Sent to @{py_html.escape(uname)} (pending)", unsafe_allow_html=True)

    # Quick DM from friends
    with st.expander("Friends"):
        friends = my_friends()
        if not friends:
            st.caption("No friends yet")
        else:
            for f in friends:
                fid = f["id"]
                label = f.get("full_name") or f.get("username") or fid[:8]
                cols = st.columns([2,1])
                cols[0].markdown(
                    f"{avatar_img(f.get('avatar_url'), 24)} **{py_html.escape(label)}**  \n`@{py_html.escape(f.get('username') or fid[:8])}`",
                    unsafe_allow_html=True
                )
                if cols[1].button("DM", key=f"dm_{fid}"):
                    try:
                        convo_id = get_or_create_conversation(fid)
                        st.session_state["current_convo"] = convo_id
                        st.cache_data.clear()
                    except Exception:
                        st.error("Could not open DM")

    # New group
    with st.expander("New group"):
        friends = my_friends()
        if not friends:
            st.caption("Add friends first to create a group.")
        else:
            friend_id_to_label = {f["id"]: (f.get("full_name") or f.get("username") or f["id"][:8]) for f in friends}
            chosen = st.multiselect(
                "Pick at least 2:",
                options=list(friend_id_to_label.keys()),
                format_func=lambda i: f'{friend_id_to_label[i]} (@{next((f["username"] for f in friends if f["id"]==i), i[:8])})'
            )
            group_title = st.text_input("Group name (optional)", "")
            if st.button("Create", type="primary", disabled=len(chosen) < 2):
                try:
                    convo_id = create_group(chosen, group_title)
                    st.success("Group created")
                    st.session_state["current_convo"] = convo_id
                    st.cache_data.clear()
                except Exception:
                    st.error("Failed to create group")

    st.markdown("---")

    # Conversation list (DMs + Groups)
    convs = my_conversations()
    st.markdown("**Your conversations**")
    if not convs:
        st.caption("No conversations yet.")
    else:
        all_member_ids = {u for c in convs for u in c.get("members", [])}
        uname_map = usernames_for_ids(all_member_ids)
        prof_map = profiles_for_ids(list(all_member_ids))
        conv_options = {}
        for c in convs:
            conv_options[c["id"]] = f"{convo_label_with_avatar(c, uname_map, prof_map)} · {c['id'][:6]}"

        conv_ids = list(conv_options.keys())
        current = st.session_state.get("current_convo")
        default_index = conv_ids.index(current) if current in conv_ids else 0

        # selectbox can't render HTML; we show a plain label in the select and pretty HTML below it
        def _plain_label(cid: str) -> str:
            # strip tags for the selectbox display
            import re as _re
            return _re.sub(r"<[^>]+>", "", conv_options.get(cid, cid[:8]))

        selected_convo_id = st.selectbox(
            "Open",
            conv_ids,
            index=default_index if conv_ids else 0,
            format_func=_plain_label,
            key="select_convo",
        )
        st.session_state["current_convo"] = selected_convo_id

        st.markdown(conv_options.get(selected_convo_id, selected_convo_id[:8]), unsafe_allow_html=True)

        if st.button("Refresh"):
            st.cache_data.clear()

# ---------- Center: Messages ----------
with col_main:
    st.subheader("💬 Messages")
    current_convo = st.session_state.get("current_convo")
    if not current_convo:
        st.caption("Pick a conversation from the left.")
        st.stop()

    # Load from DB then merge with optimistic
    server_msgs = load_messages(current_convo)
    msgs = combined_messages(current_convo, server_msgs)
    id_map = usernames_for_ids({m["sender_id"] for m in msgs} | {me})
    sender_profiles = profiles_for_ids(list({m["sender_id"] for m in msgs}))

    # Scrollable messages panel (HTML iframe)
    st.markdown("**Thread**")
    items = []
    for m in msgs:
        mine = (m["sender_id"] == me)
        who = "You" if mine else f"@{id_map.get(m['sender_id'], m['sender_id'][:8])}"
        ts = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))\
             .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        status = m.get("status")
        badge_text = "⏳ sending" if status == "sending" else ("✅ sent" if status == "sent" else ("⚠️ failed" if status == "failed" else ""))
        badge_html = f"<span class='badge'>{badge_text}</span>" if badge_text else ""
        bubble = "🟦" if mine else "🟨"
        avatar_url = sender_profiles.get(m["sender_id"], {}).get("avatar_url") or ""

        items.append(f"""
          <div class="msg {'mine' if mine else 'theirs'}">
            <div class="row">
              <img src="{py_html.escape(avatar_url)}" class="avatar"/>
              <div class="content">
                <div class="meta">{bubble} <strong>{py_html.escape(who)}</strong> · {py_html.escape(ts)} {badge_html}</div>
                <div class="body">{py_html.escape(m['content'] or '')}</div>
              </div>
            </div>
          </div>
        """)

    messages_html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body {{ margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }}
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
  .row {{ display: flex; gap: 10px; align-items: flex-start; }}
  .avatar {{ width: 28px; height: 28px; border-radius: 50%; object-fit: cover; border: 1px solid #eee; }}
  .content {{ flex: 1; }}
  .meta {{ font-size: 12px; color: #555; margin-bottom: 4px; }}
  .body {{ white-space: pre-wrap; word-wrap: break-word; }}
  .mine .meta {{ color: #245; }}
  .theirs .meta {{ color: #542; }}
  .badge {{
    display:inline-block; padding:0 6px; font-size:11px; border-radius:999px; background:#f1f1f1; color:#333; margin-left:6px;
  }}
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

    # Composer (optimistic)
    with st.form("composer", clear_on_submit=True):
        # Placeholder reflects DM vs group
        convs = my_conversations()
        is_group = any(c["id"] == current_convo and c.get("is_group") for c in convs)
        placeholder = "Message group…" if is_group else "Message…"

        text = st.text_area("Message", placeholder=placeholder, height=80, max_chars=2000, key="composer_text")
        sent = st.form_submit_button("Send", type="primary")
        if sent and text.strip():
            temp = add_optimistic_message(current_convo, me, text.strip())  # show instantly
            ok = send_message_to_db(current_convo, text)                    # persist
            mark_optimistic(current_convo, temp["id"], "sent" if ok else "failed")
            st.cache_data.clear()

# ---------- Right: Profile ----------
with col_right:
    st.subheader("🙍 Profile")

    st.markdown(
        f"{avatar_img(profile.get('avatar_url'), 64)} "
        f"<span style='font-size:18px;vertical-align:middle;margin-left:8px;'>@{py_html.escape(profile['username'])}</span>",
        unsafe_allow_html=True,
    )

    st.caption("Update your profile photo:")
    up = st.file_uploader("Upload an image", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
    if up is not None:
        data = up.read()
        if len(data) > 0:
            try:
                url = upload_avatar_to_storage(auth, me, data, up.type or "image/png")
                auth.table("profiles").update({"avatar_url": url}).eq("id", me).execute()
                st.success("Avatar updated!")
                profile["avatar_url"] = url
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Upload failed: {e}")
