#!/usr/bin/env python3
"""
Longhorn Preflight - Automated Setup Script
Guides you through the complete setup process with validation
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path

# Colors for output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_step(step_num, title):
    print(f"\n{Colors.BLUE}{Colors.BOLD}=== Step {step_num}: {title} ==={Colors.END}")

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def ask_yes_no(question, default="y"):
    choices = "[Y/n]" if default.lower() == "y" else "[y/N]"
    while True:
        answer = input(f"{question} {choices}: ").strip().lower()
        if not answer:
            return default.lower() == "y"
        if answer in ['y', 'yes']:
            return True
        elif answer in ['n', 'no']:
            return False
        print("Please answer 'y' or 'n'")

def check_venv():
    """Check if we're in a virtual environment"""
    return hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)

def check_ai_cli_environment():
    """Check if running in a recommended AI CLI environment"""
    # Check for Claude Code
    if os.getenv('CLAUDE_CODE_SESSION') or os.getenv('ANTHROPIC_CLI'):
        return "Claude Code"
    
    # Check for OpenAI CLI
    if os.getenv('OPENAI_CLI') or os.getenv('OPENAI_API_KEY'):
        return "OpenAI CLI"
    
    # Check for Gemini CLI
    if os.getenv('GEMINI_CLI') or os.getenv('GOOGLE_AI_STUDIO'):
        return "Gemini CLI"
    
    # Check if we're in a known AI CLI context by terminal
    term_program = os.getenv('TERM_PROGRAM', '').lower()
    if 'claude' in term_program or 'anthropic' in term_program:
        return "Claude Code"
    elif 'openai' in term_program:
        return "OpenAI CLI"
    elif 'gemini' in term_program or 'google' in term_program:
        return "Gemini CLI"
    
    # For now, assume any sophisticated terminal might be an AI CLI
    # This is permissive to avoid false negatives
    if os.getenv('TERM_PROGRAM') or os.getenv('SSH_CLIENT'):
        return "Unknown AI CLI"
    
    return None

def check_windows_environment():
    """Check if running on Windows (not WSL)"""
    if platform.system() == 'Windows':
        # Check if it's WSL by looking for WSL-specific indicators
        if os.path.exists('/proc/version'):
            with open('/proc/version', 'r') as f:
                if 'microsoft' in f.read().lower() or 'wsl' in f.read().lower():
                    return False  # This is WSL, not native Windows
        return True  # Native Windows
    return False

def check_dependencies():
    """Check if required packages are installed"""
    try:
        import streamlit
        import supabase
        import dotenv
        import streamlit_supabase_auth
        return True
    except ImportError:
        return False

def run_test(test_name, test_command):
    """Run a test and return True if successful"""
    print(f"🧪 Running {test_name}...")
    try:
        result = subprocess.run(test_command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print_success(f"{test_name} passed")
            return True
        else:
            print_error(f"{test_name} failed:")
            print(result.stdout)
            print(result.stderr)
            return False
    except Exception as e:
        print_error(f"Error running {test_name}: {e}")
        return False

def read_readme_section(section_tag):
    """Extract a section from README.md using tags"""
    # This would read sections marked with tags in README.md
    # For now, return instruction text
    sections = {
        "supabase_setup": """
1. Go to https://supabase.com/dashboard
2. Create a new project (free tier)
3. Go to Settings → API and copy:
   - Project URL (e.g., https://kgcsphajdxnhquskfsdb.supabase.co)
   - anon public key (long JWT token)
4. Edit your .env file with these values
""",
        "github_oauth": """
1. Go to https://github.com/settings/developers
2. Click "New OAuth App"
3. Fill in:
   - Application name: Longhorn Preflight
   - Homepage URL: http://localhost:8501
   - Authorization callback URL: {SUPABASE_URL}/auth/v1/callback
4. Register and save Client ID and Client Secret
""",
        "supabase_auth": """
1. In Supabase Dashboard: Authentication → Providers
2. Click on GitHub and Enable it
3. Enter your GitHub Client ID and Client Secret
4. Go to Authentication → URL Configuration:
   - Site URL: http://localhost:8501
   - Redirect URLs: http://localhost:8501/
"""
    }
    return sections.get(section_tag, "Section not found")

def main():
    print(f"{Colors.BOLD}🚀 Longhorn Preflight Setup{Colors.END}")
    print("This script will guide you through the complete setup process.\n")

    # Check development environment
    print_step(0, "Development Environment Check")
    
    # Check if running in AI CLI
    ai_cli = check_ai_cli_environment()
    if not ai_cli:
        print_warning("You don't appear to be running in a recommended AI coding environment!")
        print_info("This project is designed to work with AI coding assistants:")
        print("• Claude Code CLI (Anthropic): https://docs.anthropic.com/en/docs/claude-code/setup")
        print("• OpenAI Codex CLI: https://developers.openai.com/codex/cli/")
        print("• Google Gemini CLI: https://cloud.google.com/gemini/docs/codeassist/gemini-cli")
        print()
        print_warning("Without an AI assistant, you'll need to manually follow the README.")
        
        if not ask_yes_no("Continue without AI coding assistant? (not recommended)", "n"):
            print("Setup cancelled. Please install a recommended AI coding tool first.")
            return 1
    else:
        print_success(f"AI coding environment detected: {ai_cli}")

    # Check for native Windows (recommend WSL)
    if check_windows_environment():
        print_warning("You're running on native Windows!")
        print_info("AI coding tools work best on Linux-based systems.")
        print_info("For the best experience, install Windows Subsystem for Linux (WSL):")
        print("• WSL Install Guide: https://learn.microsoft.com/en-us/windows/wsl/install")
        print("• Run: wsl --install")
        print("• Then run this setup script inside WSL")
        print()
        
        if not ask_yes_no("Continue on native Windows? (not recommended)", "n"):
            print("Setup cancelled. Please install and use WSL for the best experience.")
            return 1
        print_warning("Continuing on Windows - you may encounter compatibility issues")
    else:
        os_name = platform.system()
        if os_name == "Linux":
            # Check if WSL
            if os.path.exists('/proc/version'):
                try:
                    with open('/proc/version', 'r') as f:
                        version_info = f.read().lower()
                        if 'microsoft' in version_info or 'wsl' in version_info:
                            print_success("WSL environment detected (recommended)")
                        else:
                            print_success("Linux environment detected (recommended)")
                except:
                    print_success("Linux environment detected (recommended)")
            else:
                print_success("Linux environment detected (recommended)")
        elif os_name == "Darwin":
            print_success("macOS environment detected (recommended)")

    # Check virtual environment
    print()
    print_info("Checking Python environment...")
    
    if not check_venv():
        print_warning("You're not in a virtual environment!")
        print_info("It's highly recommended to use a virtual environment.")
        print_info("Run these commands first:")
        print("  python -m venv venv")
        print("  source venv/bin/activate  # On Windows: venv\\Scripts\\activate")
        
        if not ask_yes_no("Continue without virtual environment? (not recommended)", "n"):
            print("Setup cancelled. Please set up a virtual environment first.")
            return 1
    else:
        print_success("Virtual environment detected")

    # Check dependencies
    if not check_dependencies():
        print_info("Installing dependencies...")
        if subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]).returncode != 0:
            print_error("Failed to install dependencies")
            return 1
        print_success("Dependencies installed")
    else:
        print_success("Dependencies already installed")

    # Step 1: Environment file
    print_step(1, "Environment Configuration")
    
    if not os.path.exists(".env"):
        if os.path.exists("dot.env.example"):
            shutil.copy("dot.env.example", ".env")
            print_success("Created .env from dot.env.example")
        else:
            # Create basic .env file
            with open(".env", "w") as f:
                f.write("SUPABASE_URL=your_supabase_project_url_here\n")
                f.write("SUPABASE_ANON_KEY=your_supabase_anon_key_here\n")
                f.write("APP_URL=http://localhost:8501\n")
            print_success("Created .env file")
    else:
        print_success(".env file already exists")

    # Step 2: Supabase setup
    print_step(2, "Supabase Setup")
    print(read_readme_section("supabase_setup"))
    
    if not ask_yes_no("Have you completed the Supabase setup and updated .env?"):
        print_warning("Please complete Supabase setup first, then run this script again.")
        return 1

    # Test Supabase connection
    if not run_test("Supabase connection", "python test_connection.py"):
        print_error("Supabase connection failed. Check your .env file.")
        return 1

    # Step 3: GitHub OAuth
    print_step(3, "GitHub OAuth App Setup")
    print(read_readme_section("github_oauth"))
    
    if not ask_yes_no("Have you created the GitHub OAuth app?"):
        print_warning("Please create GitHub OAuth app first, then run this script again.")
        return 1

    # Test OAuth setup
    if not run_test("GitHub OAuth", "python test_oauth.py"):
        print_warning("GitHub OAuth test failed, but continuing...")

    # Step 4: Supabase Auth Configuration
    print_step(4, "Supabase Auth Configuration")
    print(read_readme_section("supabase_auth"))
    
    if not ask_yes_no("Have you configured GitHub auth in Supabase?"):
        print_warning("Please configure GitHub auth in Supabase first, then run this script again.")
        return 1

    # Test database operations
    if not run_test("Database operations", "python test_db_operations.py"):
        print_warning("Database test failed - this might be normal if schema isn't created yet")

    # Step 5: Database Schema
    print_step(5, "Database Schema")
    print("Now you need to create the database schema:")
    print("1. Go to Supabase Dashboard → Database → SQL Editor")
    print("2. Copy and paste the contents of schema.sql")
    print("3. Click 'Run' - you should see 'Success. No rows returned'")
    
    if not ask_yes_no("Have you run the schema.sql in Supabase?"):
        print_warning("Please run schema.sql in Supabase first, then run this script again.")
        return 1

    # Final test
    if run_test("Database operations (with schema)", "python test_db_operations.py"):
        print_success("Database schema configured correctly")

    # Step 6: Ready to run
    print_step(6, "Ready to Launch!")
    print_success("Setup complete! 🎉")
    print("\nTo start the application:")
    print(f"  {Colors.BOLD}streamlit run app.py{Colors.END}")
    print("\nThen:")
    print("1. Open http://localhost:8501")
    print("2. Click 'Sign up with github'")
    print("3. Authenticate and test posting messages")

    if ask_yes_no("Start the application now?"):
        subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])

    return 0

if __name__ == "__main__":
    sys.exit(main())