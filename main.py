import os
import sys
import time
import asyncio
import logging
import shutil
import uuid
import re
import subprocess
import importlib.util
import tarfile
import json
from urllib.parse import urljoin
from datetime import datetime
from aiohttp import web

# ==========================================
# 🛠 ১. ডিপেন্ডেন্সি চেক ও ইন্সটলেশন
# ==========================================
def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required_packages = [
    "pyrogram", "tgcrypto", "yt_dlp", "requests", 
    "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent", "cloudscraper"
]

for pkg in required_packages:
    install_and_import(pkg)

import cloudscraper
import requests
import yt_dlp
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait

# FFmpeg Location Setup
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_PATH = "ffmpeg"

# ==========================================
# ⚙️ ২. কনফিগারেশন (Environment Variables)
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464633052:AAEaO33QeUy14LM7yNVSUvbH6uxtYkwvE7k")
API_ID = int(os.environ.get("API_ID", "28870226"))
API_HASH = os.environ.get("API_HASH", "a5b1ff3f75941649bf5bc159782f0f00")

DOWNLOAD_FOLDER = "downloads"
if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

app = Client(
    "universal_bot", 
    api_id=API_ID, api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=50,
    max_concurrent_transmissions=10
)

# Task Management
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(10) # একসাথে ১০টি ডাউনলোড হবে

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Bot")

# ==========================================
# 🛠 ৩. হেল্পার ফাংশনস
# ==========================================
def format_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

async def progress_bar(current, total, message, start_time, status_text):
    try:
        now = time.time()
        diff = now - start_time
        if round(diff % 4.0) == 0 or current == total:
            percentage = current * 100 / total
            speed = current / diff if diff > 0 else 0
            
            filled = int(percentage // 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            
            progress_str = (
                f"**{status_text}**\n"
                f"📂 [{bar}] `{percentage:.1f}%`\n"
                f"🚀 Speed: `{format_size(speed)}/s`\n"
                f"📦 Size: `{format_size(current)} / {format_size(total)}`"
            )
            await message.edit(progress_str, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_task")]]))
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        pass

# ==========================================
# 🕵️‍♂️ ৪. অ্যাডভান্সড লিঙ্ক স্ক্র্যাপার
# ==========================================
def get_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Video_File'),
                'url': url,
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration')
            }
        except Exception as e:
            logger.error(f"Scrape Error: {e}")
            return None

# ==========================================
# 🤖 ৫. বট হ্যান্ডলার (Messages & Callbacks)
# ==========================================
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("👋 **Universal Video Downloader!**\n\nযেকোনো ভিডিও লিঙ্ক পাঠান, আমি সেটি ডাউনলোড করে ফাইল হিসেবে পাঠিয়ে দেব।")

@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def handle_link(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        return await message.reply("❌ এটি একটি সঠিক লিঙ্ক নয়!")

    status = await message.reply("🔍 **লিঙ্ক চেক করছি...**")
    
    # লিঙ্ক থেকে তথ্য সংগ্রহ
    info = await asyncio.to_thread(get_video_info, url)
    if not info:
        return await status.edit("❌ ভিডিওর তথ্য পাওয়া যায়নি বা লিঙ্কটি সাপোর্টেড নয়।")

    task_id = str(uuid.uuid4())[:8]
    TASK_STORE[task_id] = info
    
    buttons = [
        [InlineKeyboardButton("🎬 Download Video", callback_data=f"dl_{task_id}_vid")],
        [InlineKeyboardButton("📁 Download as Doc", callback_data=f"dl_{task_id}_doc")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close")]
    ]
    
    await status.edit(
        f"📂 **Title:** `{info['title']}`\n"
        f"⏱ **Duration:** {info['duration']}s\n\nকিভাবে ডাউনলোড করতে চান?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    if data == "close":
        await query.message.delete()
    elif data.startswith("dl_"):
        _, task_id, mode = data.split("_")
        if task_id not in TASK_STORE:
            return await query.answer("পুরানো টাস্ক, আবার চেষ্টা করুন।", show_alert=True)
        
        info = TASK_STORE[task_id]
        await query.message.edit(f"⏳ **কিউতে যোগ করা হয়েছে...** `{info['title']}`")
        asyncio.create_task(process_download(client, query.message, info, mode, task_id))

# ==========================================
# 🚀 ৬. মেইন ডাউনলোড ও আপলোড ইঞ্জিন
# ==========================================
async def process_download(client, message, info, mode, task_id):
    async with DOWNLOAD_SEMAPHORE:
        path = os.path.join(DOWNLOAD_FOLDER, f"{task_id}")
        if not os.path.exists(path): os.makedirs(path)
        
        final_file = ""
        start_time = time.time()
        
        try:
            # ডাউনলোড শুরু
            await message.edit("📥 **ডাউনলোড শুরু হচ্ছে...**")
            
            def ydl_hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    current = d.get('downloaded_bytes')
                    if total:
                        asyncio.run_coroutine_threadsafe(
                            progress_bar(current, total, message, start_time, "📥 Downloading"), 
                            asyncio.get_event_loop()
                        )

            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': f'{path}/%(title)s.%(ext)s',
                'ffmpeg_location': FFMPEG_PATH,
                'progress_hooks': [ydl_hook],
                'noplaylist': True,
                'merge_output_format': 'mp4'
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([info['url']])

            # ফাইল খোঁজা
            files = os.listdir(path)
            if not files:
                raise Exception("ফাইল ডাউনলোড হয়নি।")
            
            final_file = os.path.join(path, files[0])
            file_size = os.path.getsize(final_file)
            
            # ২ জিবির বেশি হলে চেক (টেলিগ্রাম লিমিট)
            if file_size > 2000 * 1024 * 1024:
                return await message.edit("❌ ফাইলটি ২ জিবির চেয়ে বড়, যা টেলিগ্রামে পাঠানো সম্ভব নয়।")

            # আপলোড শুরু
            await message.edit("📤 **টেলিগ্রামে আপলোড করা হচ্ছে...**")
            
            async def upload_progress(current, total):
                await progress_bar(current, total, message, start_time, "📤 Uploading")

            if mode == "vid":
                await client.send_video(
                    chat_id=message.chat.id,
                    video=final_file,
                    caption=f"✅ **Downloaded:** `{info['title']}`",
                    progress=upload_progress
                )
            else:
                await client.send_document(
                    chat_id=message.chat.id,
                    document=final_file,
                    caption=f"✅ **Downloaded:** `{info['title']}`",
                    progress=upload_progress
                )

            await message.delete()

        except Exception as e:
            logger.error(f"Process Error: {e}")
            await message.edit(f"❌ এরর: `{str(e)[:100]}`")
        finally:
            shutil.rmtree(path, ignore_errors=True)
            if task_id in TASK_STORE: del TASK_STORE[task_id]

# ==========================================
# 🌐 ৭. ওয়েব সার্ভার (Render Keep-Alive)
# ==========================================
async def web_server():
    routes = web.RouteTableDef()
    @routes.get("/", allow_head=True)
    async def root_handler(request):
        return web.Response(text="Bot is Running!")
    
    server = web.Application()
    server.add_routes(routes)
    return server

# ==========================================
# 🔥 ৮. মেইন রানার
# ==========================================
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    
    # ওয়েব সার্ভার পোর্ট সেটআপ
    port = int(os.environ.get("PORT", 8080))
    
    async def main():
        # Start Web Server
        app_web = await web_server()
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"✅ Server started on port {port}")
        
        # Start Bot
        await app.start()
        print("✅ Bot is online!")
        await idle()
        await app.stop()

    loop.run_until_complete(main())
