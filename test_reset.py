import os
from supabase import create_client

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_ANON_KEY")

if not supabase_key or not supabase_url:
    from dotenv import load_dotenv
    load_dotenv("../web_frontend/.env.local")
    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")

supabase = create_client(supabase_url, supabase_key)

try:
    res = supabase.auth.reset_password_email("ascreedonly@gmail.com", options={"redirect_to": "http://localhost:3000/update-password"})
    print("Success:", res)
except Exception as e:
    print("Error:", e)
