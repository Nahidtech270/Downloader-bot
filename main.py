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
import random
import json
from urllib.parse import urljoin
from datetime import datetime
from aiohttp import web

# ==========================================
# 🛠 ১. সিস্টেম ও ডিপেন্ডেন্সি (Auto-Installer)
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UniversalBot")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing: {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except Exception as e:
            print(f"❌ Failed to install {package}: {e}")

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

# FFmpeg Setup
try:
    import imageio_ffmpeg
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

# ==========================================
# 🛠 ২. Aria2c সেটআপ (অরিজিনাল লজিক)
# ==========================================
ARIA2_BIN_PATH = os.path.join(os.getcwd(), "aria2c")

def install_aria2_static():
    if os.path.exists(ARIA2_BIN_PATH): return ARIA2_BIN_PATH
    aria_sys = shutil.which("aria2c")
    if aria_sys: return aria_sys
    
    print("🚀 Downloading Aria2c Static Engine...")
    try:
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
        r = requests.get(url, stream=True)
        tar_name = "aria2.tar.bz2"
        with open(tar_name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk: f.write(chunk)
        
        with tarfile.open(tar_name, "r:bz2") as tar:
            for member in tar.getmembers():
                if member.name.endswith("aria2c"):
                    member.name = "aria2c" 
                    tar.extract(member, path=os.getcwd())
                    break
        os.chmod(ARIA2_BIN_PATH, 0o755)
        if os.path.exists(tar_name): os.remove(tar_name)
        return ARIA2_BIN_PATH
    except Exception as e:
        print(f"⚠️ Aria2c Download Failed: {e}")
        return None

ARIA2_EXECUTABLE = install_aria2_static()

# ==========================================
# ⚙️ ৩. বট কনফিগারেশন
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464633052:AAEaO33QeUy14LM7yNVSUvbH6uxtYkwvE7k")
API_ID = int(os.environ.get("API_ID", 28870226))
API_HASH = os.environ.get("API_HASH", "a5b1ff3f75941649bf5bc159782f0f00")

DOWNLOAD_FOLDER = "downloads"
if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

app = Client(
    "final_bot_fixed", 
    api_id=API_ID, api_hash=API_HASH, 
    bot_token=BOT_TOKEN, 
    in_memory=True, 
    workers=20
)

# Global Storage
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}
semaphore = asyncio.Semaphore(5)

# ==========================================
# 🌐 Render Web Server
# ==========================================
routes = web.RouteTableDef()
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.Response(text="✅ Bot is Running Successfully!")

# ==========================================
# 🛠 ৪. হেল্পার ফাংশন (Formatting & UI)
# ==========================================
def human_readable_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def clean_filename(name):
    clean = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    return clean[:150]

async def update_progress(message, percentage, current, total, speed, status_text):
    now = time.time()
    msg_id = f"{message.chat.id}_{message.id}"
    if (now - LAST_UPDATE_TIME.get(msg_id, 0)) < 4: return
    LAST_UPDATE_TIME[msg_id] = now

    filled = int(percentage // 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    speed_txt = human_readable_size(speed) + "/s"
    text = (f"**{status_text}**\n"
            f"[{bar}] **{percentage:.1f}%**\n"
            f"📦 `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"🚀 Speed: `{speed_txt}`")
    try:
        await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{message.id}")]]))
    except FloodWait as e: await asyncio.sleep(e.value)
    except: pass

# ==========================================
# 🕵️‍♂️ ৫. সুপার স্ক্র্যাপার (Hidden Link Extractor)
# ==========================================
def deep_scrape_link(page_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(page_url, headers=headers, timeout=15)
        html = response.text
        
        # Regex for hidden .mp4 or .m3u8
        patterns = [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
            r'source\s*src\s*=\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                link = match.group(1).replace('\\/', '/')
                if not link.startswith('http'): link = urljoin(page_url, link)
                return link
        return page_url
    except:
        return page_url

# ==========================================
# 🤖 ৬. বট হ্যান্ডলার (Logics)
# ==========================================
@app.on_message(filters.command("start"))
async def start(c, m):
    await m.reply("👋 **সব ধরণের ভিডিও ডাউনলোডার বট!**\n\nযেকোনো লিঙ্ক দিন, আমি ফাইলটি নামিয়ে দেব।")

@app.on_message(filters.text & ~filters.command(["start"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    # Rename Logic
    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **নতুন নাম:** `{custom_name}`\n♻️ কিউতে যোগ হচ্ছে...")
        del USER_STATE[chat_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, TASK_STORE[task_id], task_id, custom_name))
        return

    if not text.startswith("http"): return

    status_msg = await message.reply("🕵️‍♂️ **লিঙ্ক এনালাইজ করা হচ্ছে...**")
    task_id = str(uuid.uuid4())[:8]

    # Scrape Info
    try:
        real_link = await asyncio.to_thread(deep_scrape_link, text)
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(text, download=False))
            title = info.get('title', f"Video_{task_id}")
        
        TASK_STORE[task_id] = {"url": real_link, "title": title, "original_url": text}
        
        buttons = [
            [InlineKeyboardButton("🎬 Download Video", callback_data=f"q_{task_id}_vid")],
            [InlineKeyboardButton("📁 Download Document", callback_data=f"q_{task_id}_doc")],
            [InlineKeyboardButton("❌ Close", callback_data="close")]
        ]
        await status_msg.edit(f"📂 **নাম:** `{title[:60]}`\n\nকিভাবে ডাউনলোড করতে চান?", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await status_msg.edit(f"❌ এরর: `{str(e)[:100]}`")

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    if data == "close": await query.message.delete(); return
    
    if data.startswith("q_"):
        _, task_id, mode = data.split("_")
        if task_id not in TASK_STORE: return await query.answer("টাস্ক পাওয়া যায়নি!", show_alert=True)
        
        TASK_STORE[task_id]['mode'] = mode
        USER_STATE[query.message.chat.id] = {'state': 'waiting_name', 'task_id': task_id, 'msg': query.message}
        
        await query.message.edit(
            f"📝 **ফাইলের নাম পরিবর্তন করতে চান?**\nবর্তমান নাম: `{TASK_STORE[task_id]['title']}`\n\nনতুন নাম লিখে পাঠান অথবা নিচের বাটনে ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ডিফল্ট নামে ডাউনলোড করুন", callback_data=f"startdef_{task_id}")]])
        )

    if data.startswith("startdef_"):
        task_id = data.split("_")[1]
        if query.message.chat.id in USER_STATE: del USER_STATE[query.message.chat.id]
        await query.message.edit("♻️ **ইঞ্জিন চালু হচ্ছে...**")
        asyncio.create_task(run_download_upload(client, query.message, TASK_STORE[task_id], task_id, None))

# ==========================================
# 🚀 ৭. মেইন ডাউনলোড ও আপলোড ইঞ্জিন
# ==========================================
async def run_download_upload(client, message, task_info, task_id, custom_name):
    async with semaphore:
        temp_dir = os.path.join(DOWNLOAD_FOLDER, task_id)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        final_name = custom_name if custom_name else clean_filename(task_info['title'])
        mode = task_info.get('mode', 'vid')
        start_time = time.time()

        def ydl_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                current = d.get('downloaded_bytes', 0)
                speed = d.get('speed', 0)
                if total > 0:
                    pct = (current / total) * 100
                    asyncio.run_coroutine_threadsafe(update_progress(message, pct, current, total, speed, "⬇️ Downloading"), asyncio.get_event_loop())

        ydl_opts = {
            'outtmpl': f"{temp_dir}/{final_name}.%(ext)s",
            'ffmpeg_location': FFMPEG_LOCATION,
            'progress_hooks': [ydl_hook],
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4' if mode == 'vid' else None,
        }
        
        if ARIA2_EXECUTABLE:
            ydl_opts['external_downloader'] = ARIA2_EXECUTABLE
            ydl_opts['external_downloader_args'] = ['-x', '16', '-s', '16', '-k', '1M']

        try:
            await message.edit("📥 **ডাউনলোড শুরু হয়েছে...**")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await asyncio.to_thread(ydl.download, [task_info['url']])
            
            # Find the file
            downloaded_files = os.listdir(temp_dir)
            if not downloaded_files: raise Exception("ফাইল খুঁজে পাওয়া যায়নি!")
            file_path = os.path.join(temp_dir, downloaded_files[0])
            file_size = os.path.getsize(file_path)

            if file_size > 2097152000: # 2GB Limit
                return await message.edit("❌ ফাইলটি ২ জিবির বেশি, আপলোড করা সম্ভব নয়।")

            await message.edit("📤 **আপলোড করা হচ্ছে...**")
            
            async def upload_progress(current, total):
                await update_progress(message, (current/total)*100, current, total, current/(time.time()-start_time), "⬆️ Uploading")

            caption = f"📁 **Name:** `{final_name}`\n💾 **Size:** `{human_readable_size(file_size)}`"
            
            if mode == 'doc':
                await client.send_document(message.chat.id, file_path, caption=caption, progress=upload_progress)
            else:
                await client.send_video(message.chat.id, file_path, caption=caption, supports_streaming=True, progress=upload_progress)
            
            await message.delete()

        except Exception as e:
            await message.edit(f"❌ এরর: `{str(e)[:150]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None)

# ==========================================
# 🔥 ৮. ফাইনাল এক্সিকিউশন
# ==========================================
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    
    async def main():
        # Web Server Setup
        web_app = web.Application()
        web_app.add_routes(routes)
        runner = web.AppRunner(web_app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        print(f"✅ Web Server Live on {PORT}")
        
        # Bot Setup
        await app.start()
        print("✅ Telegram Bot is Live!")
        await idle()
        await app.stop()

    asyncio.get_event_loop().run_until_complete(main())
