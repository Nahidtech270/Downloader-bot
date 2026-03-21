import os
import asyncio
import yt_dlp
from pyrogram import Client, filters
from flask import Flask
from threading import Thread

# Flask Web Server
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is Running"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# API Credentials
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("লিঙ্ক দিন, আমি ডাউনলোড করে দিচ্ছি!")

@app.on_message(filters.text & ~filters.command("start"))
async def downloader(client, message):
    url = message.text
    status_msg = await message.reply_text("লিঙ্ক চেক করছি...")

    ydl_opts = {
        'format': 'best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
    }

    try:
        # ডাউনলোড শুরু
        loop = asyncio.get_event_loop()
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info), info.get('title')

        await status_msg.edit_text("ডাউনলোড হচ্ছে... ২জিবি পর্যন্ত ফাইল হলে ধৈর্য ধরুন।")
        file_path, title = await loop.run_in_executor(None, download)
        
        await status_msg.edit_text("আপলোড শুরু হচ্ছে...")
        
        # ভিডিও পাঠানো
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=title,
            supports_streaming=True
        )
        
        if os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"ভুল: {str(e)}")

if __name__ == "__main__":
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    # Flask থ্রেড শুরু
    Thread(target=run_web, daemon=True).start()
    
    # বট রান করা
    print("Bot is starting...")
    app.run()
