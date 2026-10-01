from core.config import settings
from services.supabase_service import _get_client
client = _get_client()
def get_device_web3_access(device_id):
    if not device_id: return False
    res = client.table("iot_devices").select("user_id").eq("id", device_id).execute()
    if not res.data or not res.data[0].get("user_id"): return False
    user_id = res.data[0]["user_id"]
    u_res = client.table("users").select("wallet_address, metamask_address").eq("id", user_id).execute()
    if not u_res.data: return False
    u = u_res.data[0]
    # Check if they have metamask address
    if u.get("metamask_address"): return True
    w = u.get("wallet_address") or ""
    if w.startswith("0x"): return True
    return False

# We can also test incident fetching
print(client.table("iot_devices").select("*").execute())
