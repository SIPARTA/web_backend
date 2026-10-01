import os
from supabase import create_client

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_key or not supabase_url:
    from dotenv import load_dotenv
    load_dotenv("../web_frontend/.env.local")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

users = supabase.auth.admin.list_users()
users_list = getattr(users, "users", users)

for u in users_list:
    email = getattr(u, 'email', '')
    if email in ['hrepunzel@gmail.com', 'ascreedonly@gmail.com']:
        print(f"Updating password for {email}...")
        try:
            supabase.auth.admin.update_user_by_id(getattr(u, 'id', ''), {"password": "Password123!"})
            print(f"Success: Password for {email} is now 'Password123!'")
        except Exception as e:
            print(f"Error updating {email}: {e}")
