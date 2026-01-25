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
import stat
import tarfile
import random
from datetime import datetime

# ==========================================
# 🛠 ১. অটোমেটিক ডিপেন্ডেন্সি সেটআপ
# ==========================================
print("⚙️ System Initializing...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent"]
for pkg in required_packages:
    install_and_import(pkg)

# Aria2c Setup
ARIA2_BIN_PATH = os.path.join(os.getcwd(), "aria2c")

def install_aria2_static():
    if os.path.exists(ARIA2_BIN_PATH): return ARIA2_BIN_PATH
    aria_sys = shutil.which("aria2c")
    if aria_sys: return aria_sys
    
    print("🚀 Downloading Aria2c Engine...")
    try:
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
        import requests
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
    except: return None

ARIA2_EXECUTABLE = install_aria2_static()

import requests
import aiohttp
from bs4 import BeautifulSoup
import yt_dlp
import imageio_ffmpeg
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ==========================================
# ⚙️ কনফিগারেশন
# ==========================================
BOT_TOKEN = "7849157640:AAFyGM8F-Yk7tqH2A_vOfVGqMx6bXPq-pTI"
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt"

# র‍্যান্ডম হেডার জেনারেটর (ব্লক এড়াতে)
def get_headers(referer=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer: headers['Referer'] = referer
    return headers

try:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

app = Client("pro_uploader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, workers=10, max_concurrent_transmissions=5)

MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProBot")

if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 হেল্পার ফাংশন
# ==========================================
def human_readable_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def clean_filename(name):
    clean = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    return clean[:200] 

async def update_progress(message, percentage, current, total, speed, status_text):
    filled = int(percentage // 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    speed_txt = human_readable_size(speed) + "/s"
    text = (f"{status_text}\n[{bar}] **{percentage:.1f}%**\n"
            f"📦 `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"🚀 `{speed_txt}`")
    try:
        await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_task")]]))
    except: pass

# ==========================================
# 🔍 PRO SCANNER (Advanced Deep Link)
# ==========================================
def extract_stream_link(url):
    try:
        print(f"🕵️‍♂️ Deep Scanning: {url}")
        session = requests.Session()
        session.headers.update(get_headers())
        
        r = session.get(url, timeout=15, allow_redirects=True)
        html = r.text
        
        # Regex for m3u8, mp4, master playlists
        patterns = [
            r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'src:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'(https?://[^"\s]+\.m3u8[^"\s]*)', 
            r'file:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
            r'(https?://[^"\s]+\.mp4[^"\s]*)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                stream_url = match.group(1).replace('\\/', '/')
                print(f"✅ Found: {stream_url}")
                return stream_url, r.url 
        
        return url, url 
    except: return url, url

def get_target_url(url):
    if any(x in url for x in ["youtube.com", "youtu.be", "facebook.com"]): return url, url
    return extract_stream_link(url)

# ==========================================
# 📨 মেইন হ্যান্ডলার (Document + Video Option)
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    # Rename Logic
    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Starting Engine...**")
        del USER_STATE[chat_id]
        
        task_info = TASK_STORE[task_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['referer'], task_info['mode'], task_id, custom_name))
        return

    if not text.startswith("http"):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Pro Analysis Started...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        target_url, referer = await asyncio.to_thread(get_target_url, text)
        
        # Metadata Fetch
        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'user_agent': get_headers()['User-Agent'],
            'http_headers': get_headers(referer),
        }

        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
            title = info.get('title', f'File_{task_id}')
        except:
            title = f"Unknown_Video_{task_id}"

        # 🔥 Advanced Buttons
        buttons = [
            [
                InlineKeyboardButton("🎬 Video (Playable)", callback_data=f"q_{task_id}_vid"),
                InlineKeyboardButton("📁 Document (Raw)", callback_data=f"q_{task_id}_doc")
            ],
            [
                InlineKeyboardButton("🎵 Audio Only", callback_data=f"q_{task_id}_aud"),
                InlineKeyboardButton("❌ Cancel", callback_data="close")
            ]
        ]

        TASK_STORE[task_id] = {"url": target_url, "referer": referer, "title": title}
        await status_msg.edit(
            f"📂 **Found:** `{title[:60]}`\n"
            f"🔗 **Source:** `{target_url[:40]}...`\n\n"
            f"👇 **Select Format:**\n"
            f"• **Video:** Streamable in Telegram.\n"
            f"• **Document:** Best for keeping original quality (No Errors).",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)[:100]}`")

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    if data == "close": await query.message.delete(); return
    if data == "cancel_task": await query.answer("🛑 Stopping...", show_alert=True); return

    if data.startswith("q_"):
        parts = data.split("_")
        task_id, mode = parts[1], parts[2]
        
        if task_id not in TASK_STORE: await query.answer("⚠️ Task Expired!", show_alert=True); return
        
        TASK_STORE[task_id]['mode'] = mode
        default_name = TASK_STORE[task_id]['title']
        
        USER_STATE[query.message.chat.id] = {'state': 'waiting_name', 'task_id': task_id, 'msg': query.message}
        await query.message.edit(
            f"📝 **File Name:**\n`{default_name}`\n\n👇 **Rename?**\n1. Send new name\n2. Click Default",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Use Default Name", callback_data=f"startdef_{task_id}")],
                [InlineKeyboardButton("❌ Close", callback_data="close")]
            ])
        )

    if data.startswith("startdef_"):
        task_id = data.split("_")[1]
        if task_id not in TASK_STORE: return
        if query.message.chat.id in USER_STATE: del USER_STATE[query.message.chat.id]
        
        info = TASK_STORE[task_id]
        await query.message.edit(f"♻️ **Queued...**")
        asyncio.create_task(run_download_upload(client, query.message, info['url'], info['referer'], info['mode'], task_id, None))

# ==========================================
# 🚀 ULTRA STABLE ENGINE (Anti-Corruption)
# ==========================================
def yt_dlp_hook(d, message, client, task_id):
    if d['status'] == 'downloading':
        now = time.time()
        if (now - LAST_UPDATE_TIME.get(task_id, 0)) < 4: return
        LAST_UPDATE_TIME[task_id] = now
        
        if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED")

        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        current = d.get('downloaded_bytes', 0)
        speed = d.get('speed') or 0
        percentage = current * 100 / total if total > 0 else 0
        
        client.loop.create_task(update_progress(message, percentage, current, total, speed, "⬇️ Downloading..."))

async def upload_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id): app.stop_transmission(); return
    now = time.time()
    if (now - start_time) % 4 < 0.5 or current == total:
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
        percentage = current * 100 / total
        await update_progress(message, percentage, current, total, speed, "⬆️ Uploading...")

async def run_download_upload(client, message, url, referer, mode, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        file_name = clean_filename(custom_name if custom_name else TASK_STORE[task_id].get('title', 'video'))
        final_path = ""
        thumb_path = None
        duration = 0

        dl_headers = get_headers(referer)

        try:
            # 📥 DOWNLOAD PHASE
            await message.edit(f"🚀 **Downloading ({mode.upper()})...**")
            
            # 🔥 Advanced Configuration for Stability
            ydl_opts = {
                'outtmpl': f"{temp_dir}/{file_name}.%(ext)s",
                'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
                'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                'http_headers': dl_headers,
                'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                # Stability Settings
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
            }

            # 🛠 HLS Stability Fix
            if "m3u8" in url:
                # m3u8 এর জন্য Aria2 ব্যবহার না করাই ভালো, কারণ এটা করাপ্ট করে ফেলে
                ydl_opts['hls_prefer_native'] = True  
                ydl_opts['hls_use_mpegts'] = True      # স্ট্রিম স্ট্যাবল করে
            else:
                # অন্য সব লিংকের জন্য Aria2 সুপারফাস্ট
                ydl_opts['external_downloader'] = ARIA2_EXECUTABLE
                ydl_opts['external_downloader_args'] = ['-x', '16', '-k', '1M', '-s', '16']

            if mode == "aud":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
            elif mode == "doc":
                # Document এর জন্য কোন কনভার্সন হবে না, সরাসরি বেস্ট কোয়ালিটি
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['keepvideo'] = True
            else:
                # Video Mode: Ensure MP4
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

            # Execution
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
            
            # File Detection
            for file in os.listdir(temp_dir):
                if file.endswith((".mp4", ".mkv", ".mp3", ".webm", ".ts")):
                    final_path = os.path.join(temp_dir, file)
                    break
            
            # Thumbnail & Duration
            thumb_path = f"{temp_dir}/{file_name}.jpg"
            if not os.path.exists(thumb_path): thumb_path = None
            duration = int(info.get('duration', 0))

            # 📤 UPLOAD PHASE
            if not os.path.exists(final_path): raise Exception("Download Failed (No File)")
            file_size = os.path.getsize(final_path)

            if file_size > 2 * 1024 * 1024 * 1024:
                await message.edit("❌ **File too large (>2GB).**")
                return

            await message.edit(f"⬆️ **Uploading as {mode.upper()}...**")
            start_time = time.time()
            caption = f"📁 **{file_name}**\n💾 Size: {human_readable_size(file_size)}\n🤖 Bot Upload"

            if mode == "aud":
                await client.send_audio(message.chat.id, final_path, caption=caption, duration=duration, progress=upload_hook, progress_args=(message, start_time, task_id))
            elif mode == "doc":
                # 🔥 Document Mode: Upload as File (No Compression/Conversion issues)
                await client.send_document(message.chat.id, final_path, caption=caption, thumb=thumb_path, force_document=True, progress=upload_hook, progress_args=(message, start_time, task_id))
            else:
                # Video Mode
                await client.send_video(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, supports_streaming=True, progress=upload_hook, progress_args=(message, start_time, task_id))

            await message.delete()

        except Exception as e:
            logger.error(f"Error: {e}")
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled.**")
            else: await message.edit(f"❌ **Failed:** `{str(e)[:100]}`")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None)

@app.on_message(filters.command("start"))
async def start(c, m): 
    await m.reply("👋 **Pro URL Uploader Ready!**\n\n✨ **Features:**\n🎬 Video Mode (Streamable)\n📁 Document Mode (Raw File/No Corruption)\n🛡️ Anti-HLS Crash System\n\n**Send a link to start!**")

print("🔥 Bot Started (Advanced Video+Doc Mode)...")
app.run()
