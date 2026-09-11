import os,httpx
async def send_telegram(text:str):
    token=os.getenv("TELEGRAM_BOT_TOKEN",""); chat=os.getenv("TELEGRAM_CHAT_ID","")
    if not token or not chat: return False
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"https://api.telegram.org/bot{token}/sendMessage",data={"chat_id":chat,"text":text}); r.raise_for_status(); return True
