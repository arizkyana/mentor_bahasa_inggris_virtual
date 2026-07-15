import os
import supabase
from dotenv import load_dotenv

load_dotenv()

supabase_client = supabase.create_client(
    supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY")
)

# TEST: ambil data dari table chat_users
result = supabase_client.table("chat_users").select("*").execute()
print("Koneksi berhasil!")
print(f"Jumlah user terdaftar: {len(result.data)}")
