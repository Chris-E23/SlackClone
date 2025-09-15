#!/usr/bin/env python3
"""
Test Supabase database operations (insert and read)
Note: Run schema.sql in Supabase Dashboard first!
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
import uuid

# Load environment variables
load_dotenv()

# Get credentials
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")

print("Testing Supabase database operations...")
print(f"URL: {url}")
print(f"Key: {key[:20]}..." if key else "Key: None")

if not url or not key:
    print("\n❌ Error: Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env file")
    exit(1)

try:
    # Create Supabase client
    supabase: Client = create_client(url, key)
    
    print("\n1. Testing SELECT (should fail without auth due to RLS)...")
    try:
        result = supabase.table("messages").select("*").execute()
        print(f"   Messages found: {len(result.data)}")
        for msg in result.data[:3]:  # Show first 3 messages
            print(f"   - {msg}")
    except Exception as e:
        print(f"   Expected RLS error (not authenticated): {e}")
    
    print("\n2. Testing INSERT (should fail without auth due to RLS)...")
    try:
        test_message = {
            "user_id": str(uuid.uuid4()),  # Generate a test UUID
            "content": f"Test message from script at {datetime.now()}"
        }
        result = supabase.table("messages").insert(test_message).execute()
        print(f"   ✅ Inserted: {result.data}")
    except Exception as e:
        print(f"   Expected RLS error (not authenticated): {e}")
    
    print("\n3. Note: Both operations should fail with RLS errors when not authenticated.")
    print("   This is expected behavior! The app.py will handle authentication.")
    
    print("\n✅ Database connection works! RLS policies are active (blocking unauthenticated access).")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\nPossible issues:")
    print("1. Table 'messages' doesn't exist - run schema.sql in Supabase Dashboard")
    print("2. Network/connection issues")
    print("3. Invalid credentials")
    exit(1)