from core.config import settings
from services.supabase_service import _get_client
client = _get_client()

try:
    res = client.table("transactions_logs").select("*").limit(1).execute()
    print("transactions_logs:", res)
except Exception as e:
    print("Error transactions_logs:", e)

try:
    res = client.table("transaction_logs").select("*").limit(1).execute()
    print("transaction_logs:", res)
except Exception as e:
    print("Error transaction_logs:", e)

