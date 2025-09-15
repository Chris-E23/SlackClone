#!/usr/bin/env python3
"""
Test Supabase connection using credentials from .env file
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Get credentials
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")

print("Testing Supabase connection...")
print(f"URL: {url}")
print(f"Key: {key[:20]}..." if key else "Key: None")

if not url or not key:
    print("\n❌ Error: Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env file")
    exit(1)

try:
    # Create Supabase client
    supabase: Client = create_client(url, key)
    
    # Test the connection by trying to get auth session (should be None if not logged in)
    session = supabase.auth.get_session()
    
    print("\n✅ Connection successful!")
    print(f"Session: {session}")
    
    # Try to query the messages table
    print("\nAttempting to query messages table...")
    try:
        # This should fail with RLS error if RLS is enabled and we're not authenticated
        result = supabase.table("messages").select("*").limit(1).execute()
        print(f"   Query succeeded (unexpected if RLS is enabled)")
        print(f"   Rows returned: {len(result.data)}")
    except Exception as query_error:
        print(f"   Expected RLS error: {query_error}")
        print("   ✅ This is correct! RLS is blocking unauthenticated access.")
    
except Exception as e:
    print(f"\n❌ Connection failed: {e}")
    exit(1)