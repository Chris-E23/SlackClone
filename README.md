# Longhorn Preflight

A minimal Streamlit + Supabase demo application with GitHub authentication.

## Features

- GitHub OAuth authentication via Supabase
- Post and view messages
- Row Level Security (RLS) policies
- Works locally and on Streamlit Community Cloud

## Prerequisites

### Development Environment (Important!)

⚠️ **This project is designed to work with AI coding assistants for the best experience.**

**Recommended AI Coding Tools:**
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/setup)** (Anthropic) - *Recommended*
- **[OpenAI Codex CLI](https://developers.openai.com/codex/cli/)** (OpenAI)
- **[Google Gemini CLI](https://cloud.google.com/gemini/docs/codeassist/gemini-cli)** (Google Cloud)

**Operating System Requirements:**
- ✅ **Linux** (preferred) - Native support for all AI tools
- ✅ **macOS** - Full compatibility
- ⚠️ **Windows** - Use [Windows Subsystem for Linux (WSL)](https://learn.microsoft.com/en-us/windows/wsl/install)
  - Run: `wsl --install` in PowerShell as Administrator
  - Then run all commands inside WSL for best compatibility

**Virtual Environment (Strongly Recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows WSL: same command
# On Windows Command Prompt: venv\Scripts\activate
```

### System Requirements
- Python 3.10+ (3.11 recommended)
- Free accounts on:
  - [GitHub](https://github.com)
  - [Supabase](https://supabase.com)
  - [Streamlit Community Cloud](https://streamlit.io/cloud) (for deployment)

## Quick Start

**Automated Setup (Recommended):**
```bash
git clone <your-repo-url>
cd longhorn-preflight
python setup.py
```

The setup script will:
- ✅ **Check your environment** (AI CLI, OS, Python virtual env)
- ✅ **Guide you through each step** with validation
- ✅ **Test each component** before proceeding
- ⚠️ **Warn about issues** (Windows/WSL, missing AI tools, no venv)
- 🚀 **Launch the app** when everything is ready

**Manual Setup:** Follow the detailed guide below if you prefer step-by-step control.

---

## Setup Guide

### Step 0: Project Setup

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd longhorn-preflight
   ```

2. **Set up virtual environment (recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

### Step 1: Initial Supabase Setup

1. Go to [Supabase Dashboard](https://supabase.com/dashboard)
2. Create a new project (free tier)
3. Go to **Settings → API** and copy:
   - **Project URL** (e.g., `https://kgcsphajdxnhquskfsdb.supabase.co`)
   - **anon public key** (long JWT token)

4. **Create your environment file:**
   ```bash
   cp dot.env.example .env
   ```

5. **Edit `.env`** and add your Supabase credentials:
   ```env
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_ANON_KEY=your_anon_key_here
   APP_URL=http://localhost:8501
   ```

**✅ Test Supabase connection:**
```bash
python test_connection.py
```
You should see "✅ Connection successful!"

### Step 2: Create GitHub OAuth App

**Why now?** You need your Supabase project URL from Step 1 for the callback URL.

1. Go to [GitHub Settings → Developer settings → OAuth Apps](https://github.com/settings/developers)
2. Click **"New OAuth App"**
3. Fill in the application details:
   - **Application name:** `Longhorn Preflight` (or your preferred name)
   - **Homepage URL:** `http://localhost:8501`
   - **Authorization callback URL:** `https://your-project-ref.supabase.co/auth/v1/callback`
     - Use your actual Supabase URL from Step 1: `{SUPABASE_URL}/auth/v1/callback`
4. Click **"Register application"**
5. **Save these credentials** (💡 keep this browser tab open - you'll need to copy these to Supabase next):
   - **Client ID** (e.g., `Ov23lilxyJQpoTlHKGfz`)
   - **Client Secret** (click "Generate a new client secret")

**✅ Test GitHub OAuth setup:**
```bash
python test_oauth.py
```
This verifies your GitHub OAuth app is configured correctly.

### Step 3: Configure GitHub Authentication in Supabase

1. In Supabase Dashboard, go to **Authentication → Providers**
2. Click on **GitHub**
3. **Enable** the GitHub provider
4. Enter your GitHub credentials from Step 2:
   - **Client ID:** (from GitHub OAuth app)
   - **Client Secret:** (from GitHub OAuth app)
5. Click **Save**

6. Go to **Authentication → URL Configuration** and set:
   - **Site URL:** `http://localhost:8501`
   - **Redirect URLs:** Add BOTH URLs for local and production use:
     - `http://localhost:8501/`
     - `https://*.streamlit.app/` (wildcard for Streamlit Cloud)

**✅ Test combined setup:**
```bash
python test_db_operations.py
```
This tests database access (should show RLS errors - that's correct!)

### Step 4: Create Database Schema

1. Go to **Database → SQL Editor** in Supabase Dashboard
2. Copy and run the entire contents of `schema.sql`:
   - Creates `messages` table
   - Enables Row Level Security
   - Creates policies for authenticated users
3. You should see "Success. No rows returned" message

**✅ Test database schema:**
```bash
python test_db_operations.py
```
Should now show RLS blocking unauthenticated access (this is correct behavior)


### 5. Run the Application

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`

**✅ Test full authentication flow:**
1. Click "Sign up with github" button
2. Authenticate with GitHub
3. Return to app (should show your email)
4. Post a test message
5. Verify message appears in the list

**Note:** Email/password fields are shown but not implemented in this MVP (GitHub OAuth only)

## Streamlit Cloud Deployment

### 1. Push to GitHub

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### 2. Deploy on Streamlit Cloud

1. Go to [Streamlit Cloud](https://streamlit.io/cloud)
2. Click "New app"
3. Select your GitHub repository
4. Set branch: `main`, Main file path: `app.py`

### 3. Configure Secrets

In Streamlit Cloud app settings → Secrets, add:

```toml
SUPABASE_URL = "your_project_url_here"
SUPABASE_ANON_KEY = "your_anon_key_here"
```

### 4. Verify Deployment

Your app should now be live! The redirect URLs were already configured in Step 3 to work with both local development and Streamlit Cloud.

**Why both URLs?** 
- Local development needs `http://localhost:8501/`
- Production deployment needs your Streamlit Cloud URL
- The wildcard `https://*.streamlit.app/` covers all Streamlit Cloud deployments

## Testing Checklist

### Local Testing
- [ ] GitHub sign-in redirects and returns successfully
- [ ] User email/ID displays after authentication
- [ ] Can post messages when signed in
- [ ] Messages appear in the list immediately
- [ ] Messages show in Supabase Dashboard table viewer
- [ ] Sign out works correctly

### Production Testing
- [ ] GitHub sign-in works with production URL
- [ ] Messages persist between sessions
- [ ] Multiple users can post and see messages
- [ ] RLS policies prevent unauthenticated access

## Troubleshooting

### GitHub OAuth "404" or "Mini Slack" Error
**Problem:** GitHub OAuth shows "client_id=Mini+Slack" or returns 404
**Solution:** 
1. Verify you've entered the GitHub **Client ID** and **Client Secret** in Supabase
2. Go to Supabase → Authentication → Providers → GitHub
3. Make sure both credentials are saved correctly
4. Clear browser cache or use incognito mode

### Authentication Loops (Signs in but returns to login)
**Problem:** Successfully authenticates with GitHub but app doesn't recognize the session
**Solution:** 
1. Ensure you're using the latest `app.py` with `streamlit-supabase-auth`
2. Check that Streamlit is running on port 8501 (matching redirect URL)
3. Kill any other Streamlit processes: `pkill streamlit`
4. Restart with: `streamlit run app.py`

### "RLS policy violation" Error
**Problem:** `new row violates row-level security policy for table "messages"`
**Solution:**
- Ensure you're signed in with GitHub (not just visiting the page)
- Verify RLS policies exist by re-running `schema.sql`
- Check that the app is using authenticated Supabase client for database operations

### GitHub OAuth App Setup Issues
**Problem:** Need to test GitHub OAuth independently
**Solution:** Run `python test_oauth.py` to verify GitHub app configuration

### Environment Issues
**Problem:** Setup failing or AI features not working
**Solutions:**
1. **Not using AI coding tool:** Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code/setup), [OpenAI CLI](https://developers.openai.com/codex/cli/), or [Gemini CLI](https://cloud.google.com/gemini/docs/codeassist/gemini-cli)
2. **Windows compatibility:** Use WSL instead of native Windows
   - Run `wsl --install` in PowerShell as Administrator
   - Run all commands inside WSL environment
3. **No virtual environment:** Create and activate venv before installing dependencies
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS/WSL
   pip install -r requirements.txt
   ```

### General Setup Issues
1. **Wrong setup order:** Always create GitHub OAuth app FIRST, then configure Supabase
2. **Multiple Streamlit instances:** Only run one Streamlit app at a time on port 8501
3. **Missing dependencies:** Make sure to install: `pip install streamlit-supabase-auth`
4. **URL mismatches:** Ensure callback URLs match between GitHub and Supabase exactly

### Streamlit Cloud Deployment
- Secrets must be in TOML format in Streamlit Cloud settings
- Add your Streamlit Cloud URL to GitHub OAuth app and Supabase redirect URLs
- Don't commit `.env` file to repository

## Project Structure

```
LonghornPreflight/
├── setup.py                 # Automated setup script
├── app.py                   # Main Streamlit application with GitHub OAuth
├── schema.sql              # Database schema and RLS policies
├── requirements.txt        # Python dependencies
├── dot.env.example         # Environment template
├── .env                    # Local environment variables (not in git, create from template)
├── .gitignore              # Git ignore file (excludes .env and other files)
├── test_connection.py      # Basic Supabase connection test
├── test_db_operations.py   # Database operations test
├── test_oauth.py          # GitHub OAuth setup test
└── README.md              # This file
```

**Key Files:**
- **`setup.py`** - 🚀 **Start here!** Automated setup with validation and guidance
- **`app.py`** - Production-ready app with working GitHub OAuth and error handling
- **`schema.sql`** - Complete database setup with RLS policies
- **`dot.env.example`** - Template for environment variables (copy to `.env`)
- **`.gitignore`** - Prevents committing sensitive files like `.env`

## Security Notes

- Never commit `.env` file to version control
- Use only the `anon` key in client applications
- Keep the `service_role` key secret and never use in frontend
- RLS policies protect data at the database level

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Supabase logs in Dashboard → Logs
3. Check Streamlit Cloud logs in app settings

## License

MIT