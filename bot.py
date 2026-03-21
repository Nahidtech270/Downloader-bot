import os
import asyncio
import yt_dlp
from pyrogram import Client, filters
from flask import Flask
from threading import Thread

# Flask Web Server (Render-কে শান্ত রাখার জন্য)
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is Running"

def run_web():
    # Render ডিফল্টভাবে ১০০০০ পোর্ট ব্যবহার করে
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# টেলিগ্রাম বটের তথ্য
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("লিঙ্ক দিন, আমি ২জিবি পর্যন্ত ভিডিও ডাউনলোড করে দিচ্ছি!")

@app.on_message(filters.text & ~filters.command("start"))
async def downloader(client, message):
    url = message.text
    status_msg = await message.reply_text("লিঙ্ক চেক করছি...")

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'merge_output_format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await status_msg.edit_text("ডাউনলোড শুরু হয়েছে... বড় ফাইল হলে সময় লাগবে।")
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
            await status_msg.edit_text("ডাউনলোড শেষ! এখন আপলোড করছি...")
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=info.get('title'),
                supports_streaming=True
            )
            os.remove(file_path)
            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"ভুল: {str(e)}")

if __name__ == "__main__":
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    # Web server আলাদা থ্রেডে চালানো
    Thread(target=run_web).start()
    
    # বট চালানো
    print("Bot is starting...")
    app.run()
