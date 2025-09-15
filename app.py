#!/usr/bin/env python3
"""
Longhorn Preflight - Using streamlit-supabase-auth (Fixed)
Simplified GitHub authentication with proper OAuth handling
"""

import os
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import time
from streamlit_supabase_auth import login_form, logout_button

# Page config
st.set_page_config(
    page_title="Longhorn Preflight",
    page_icon="🚀",
    layout="centered"
)

# Load environment variables
if os.path.exists(".env"):
    load_dotenv()
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    is_local = True
else:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY")
    is_local = False

# Check for missing configuration
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("🚨 **Configuration Error: Missing Supabase Credentials**")
    
    if is_local:
        st.markdown("""
        **Local Development Setup Needed:**
        
        1. Create a `.env` file in your project root
        2. Add your Supabase credentials:
        ```
        SUPABASE_URL=https://your-project-ref.supabase.co
        SUPABASE_ANON_KEY=your_anon_key_here
        ```
        3. Get these values from [Supabase Dashboard](https://supabase.com/dashboard) → Settings → API
        
        📖 **Need help?** Check the README.md for detailed setup instructions.
        """)
    else:
        st.markdown("""
        **Streamlit Cloud Setup Needed:**
        
        1. Go to your [Streamlit Cloud dashboard](https://share.streamlit.io/)
        2. Find this app and click on it
        3. Click the **⚙️ Settings** button (usually in the top right)
        4. Go to **Secrets** tab
        5. Add your secrets in TOML format (**quotes are required**):
        ```toml
        SUPABASE_URL = "https://your-project-ref.supabase.co"
        SUPABASE_ANON_KEY = "your_anon_key_here"
        ```
        6. Click **Save** and the app will restart automatically
        
        ⚠️ **Important:** Make sure to include the quotes around both values or you'll get "Invalid format: please enter valid TOML" error.
        
        💡 **Get credentials from:** [Supabase Dashboard](https://supabase.com/dashboard) → Settings → API
        """)
    
    st.stop()  # Stop execution here

# Initialize Supabase client
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = init_supabase()

# Header
st.title("🚀 Longhorn Preflight")
st.markdown("Simple message board with GitHub authentication via Supabase")
st.divider()

# Set environment variable for streamlit-supabase-auth
os.environ["SUPABASE_KEY"] = SUPABASE_ANON_KEY

# Authentication using streamlit-supabase-auth
session = login_form(
    url=SUPABASE_URL,
    apiKey=SUPABASE_ANON_KEY,
    providers=["github"]  # Only GitHub provider
)

# Check authentication state
if session:
    # User is authenticated
    user = session["user"]
    
    # User info section
    col1, col2 = st.columns([3, 1])
    with col1:
        email = user.get("email", "Unknown")
        st.success(f"✅ Signed in as: **{email}**")
        st.caption(f"User ID: {user.get('id', 'Unknown')[:8]}...")
    with col2:
        logout_button(apiKey=SUPABASE_ANON_KEY)
    
    # Debug info
    with st.expander("🔍 Debug Info"):
        st.write("**Session Keys:**", list(session.keys()))
        st.write("**Has Access Token:**", "access_token" in session)
        if "access_token" in session:
            token = session["access_token"]
            st.write("**Token Length:**", len(token))
            st.write("**Token Preview:**", f"{token[:20]}..." if len(token) > 20 else token)
    
    st.divider()
    
    # Message posting section
    st.subheader("✍️ Post a Message")
    
    with st.form("message_form"):
        message_content = st.text_area(
            "Your message:",
            max_chars=1000,
            placeholder="What's on your mind? (max 1000 characters)"
        )
        
        submitted = st.form_submit_button("📤 Post Message", type="primary")
        
        if submitted and message_content.strip():
            try:
                # Get user ID and access token
                user_id = user.get("id")
                access_token = session.get("access_token")
                
                if not access_token:
                    st.error("No access token found. Please sign out and sign in again.")
                else:
                    # Create authenticated Supabase client
                    auth_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
                    auth_supabase.auth.set_session(access_token, session.get("refresh_token", ""))
                    
                    # Insert message using authenticated client
                    result = auth_supabase.table("messages").insert({
                        "user_id": user_id,
                        "content": message_content.strip()
                    }).execute()
                    
                    st.success("Message posted successfully!")
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"Error posting message: {e}")
                st.info("Make sure the database schema has been created in Supabase")
        elif submitted:
            st.warning("Please enter a message")
    
    st.divider()
    
    # Messages display section
    st.subheader("📨 Recent Messages")
    
    try:
        # Create authenticated client for reading messages
        access_token = session.get("access_token")
        if access_token:
            auth_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            auth_supabase.auth.set_session(access_token, session.get("refresh_token", ""))
            # Fetch recent messages with authenticated client
            result = auth_supabase.table("messages")\
                .select("*")\
                .order("created_at", desc=True)\
                .limit(50)\
                .execute()
        else:
            # Fallback to unauthenticated client (might work if RLS allows public read)
            result = supabase.table("messages")\
                .select("*")\
                .order("created_at", desc=True)\
                .limit(50)\
                .execute()
        
        messages = result.data
        
        if messages:
            for msg in messages:
                # Create message container
                with st.container():
                    # Parse timestamp
                    created_at = datetime.fromisoformat(msg["created_at"].replace("Z", "+00:00"))
                    formatted_time = created_at.strftime("%Y-%m-%d %H:%M UTC")
                    
                    # Display message
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**Message:** {msg['content']}")
                        st.caption(f"User: {msg['user_id'][:8]}... | {formatted_time}")
                    st.divider()
        else:
            st.info("No messages yet. Be the first to post!")
            
    except Exception as e:
        st.error(f"Error loading messages: {e}")
        st.info("Make sure the schema.sql has been run in Supabase Dashboard")

else:
    # User is not authenticated
    st.subheader("👤 Authentication")
    st.info("Please sign in with GitHub to post and view messages")
    
    # Note about authentication options
    st.markdown("---")
    st.markdown("**Authentication Options:**")
    st.success("✅ **GitHub OAuth** - Click 'Sign up with github' button above (recommended)")
    st.warning("⚠️ **Email/Password** - Not implemented in this MVP. You would need to:")
    with st.expander("How to implement email/password auth"):
        st.markdown("""
        1. **Enable email auth in Supabase:**
           - Go to Authentication → Settings in Supabase Dashboard
           - Enable email confirmations
           - Configure email templates
        
        2. **Add signup/verification logic:**
           - Handle email verification flows
           - Add password reset functionality
           - Implement user profile management
        
        3. **Update RLS policies:**
           - Ensure policies work for both OAuth and email users
        
        **For this demo, use GitHub authentication instead.**
        """)
    
    # The login form is automatically displayed above

# Footer
st.divider()
st.caption("🚀 Longhorn Preflight - Streamlit + Supabase MVP with streamlit-supabase-auth")