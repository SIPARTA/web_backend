import os
import time
from supabase import create_client

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_key or not supabase_url:
    from dotenv import load_dotenv
    load_dotenv("../web_frontend/.env.local")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

try:
    response = supabase.auth.admin.list_users()
    users = getattr(response, "users", response)
    
    # Sort by created_at descending
    sorted_users = sorted(users, key=lambda x: getattr(x, 'created_at', ''), reverse=True)
    
    print("--- LATEST USERS ---")
    for u in sorted_users[:5]:
        print(f"Email: {getattr(u, 'email', '')} | Confirmed At: {getattr(u, 'email_confirmed_at', '')} | Created: {getattr(u, 'created_at', '')} | Invited: {getattr(u, 'invited_at', '')} | Last SignIn: {getattr(u, 'last_sign_in_at', '')}")
except Exception as e:
    print(f"Error querying users: {e}")
