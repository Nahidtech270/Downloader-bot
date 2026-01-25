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
from datetime import datetime

# ==========================================
# 🛠 ১. অটোমেটিক ডিপেন্ডেন্সি (Cloudscraper Added)
# ==========================================
print("⚙️ System Initializing (Anti-Bot Bypass)...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# 🔥 cloudscraper খুবই গুরুত্বপূর্ণ এই সাইটের জন্য
required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent", "cloudscraper"]
for pkg in required_packages:
    install_and_import(pkg)

import cloudscraper # Cloudflare Bypasser
from fake_useragent import UserAgent

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

try:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

app = Client("bypass_uploader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, workers=10, max_concurrent_transmissions=5)

MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BypassBot")

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
# 🕵️‍♂️ CLOUDSCRAPER & LINK EXTRACTOR (CORE FIX)
# ==========================================
def get_protected_link(url):
    """
    Cloudscraper ব্যবহার করে সাইট বাইপাস করে আসল m3u8 লিংক বের করবে
    এবং কুকি ফাইল আপডেট করবে।
    """
    try:
        if any(x in url for x in ["youtube.com", "youtu.be", "facebook.com"]): return url, url

        print(f"🛡️ Bypassing Protection: {url}")
        
        # 🔥 Cloudflare Bypasser
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        response = scraper.get(url)
        
        # কুকি ফাইলে সেভ করা (yt-dlp এর জন্য)
        with open(COOKIE_FILE, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for cookie in scraper.cookies:
                f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{'TRUE' if cookie.secure else 'FALSE'}\t{cookie.expires}\t{cookie.name}\t{cookie.value}\n")

        html = response.text
        
        # Regex to find hidden streams
        patterns = [
            r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'src:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'(https?://[^"\s]+\.m3u8[^"\s]*)', 
            r'file:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                stream_url = match.group(1).replace('\\/', '/')
                print(f"✅ Found Protected Stream: {stream_url}")
                
                # যদি m3u8 লিংক রিলেটিভ হয় (http না থাকে)
                if not stream_url.startswith("http"):
                    # ডোমেইন অ্যাড করা লাগতে পারে, আপাতত ইগনোর করছি
                    pass 
                
                return stream_url, url 
        
        return url, url 
    except Exception as e:
        print(f"⚠️ Bypass Error: {e}")
        return url, url

# ==========================================
# 📨 মেইন হ্যান্ডলার
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Queueing...**")
        del USER_STATE[chat_id]
        
        task_info = TASK_STORE[task_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['referer'], task_info['mode'], task_info['res'], task_id, custom_name))
        return

    if not text.startswith("http"):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Bypassing Cloudflare...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        # 🔥 নতুন বাইপাস লজিক
        target_url, referer = await asyncio.to_thread(get_protected_link, text)
        is_direct = False
        info = {}
        
        # হেডার জেনারেট (কুকি ফাইল ইউজ হবে)
        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'cookiefile': COOKIE_FILE, # Generated by Cloudscraper
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': referer
        }

        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        except:
            is_direct = True
            info = {'title': f'File_{task_id}', 'formats': []}

        title = info.get('title', f'File_{task_id}')
        formats = info.get('formats', [])
        
        buttons = []
        
        # কোয়ালিটি বাটন
        if not is_direct and formats:
            resolutions = sorted(list(set([f.get('height') for f in formats if f.get('height')])), reverse=True)
            if resolutions:
                row = []
                for res in resolutions[:5]:
                    row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"q_{task_id}_vid_{res}"))
                    if len(row) == 3: buttons.append(row); row = []
                if row: buttons.append(row)
        
        ctrl_buttons = [
            [InlineKeyboardButton("🎬 Best Video (Safe)", callback_data=f"q_{task_id}_vid_best")],
            [InlineKeyboardButton("📁 Document (Raw)", callback_data=f"q_{task_id}_doc_best")],
            [InlineKeyboardButton("🎵 Audio Only", callback_data=f"q_{task_id}_aud_0")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close")]
        ]
        for btn in ctrl_buttons: buttons.append(btn)

        TASK_STORE[task_id] = {"url": target_url, "referer": referer, "title": title}
        await status_msg.edit(
            f"📂 **Found:** `{title[:60]}`\n"
            f"🔗 **Real Link:** `{target_url[:30]}...`\n"
            f"🔓 **Protection:** Bypassed ✅", 
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
        task_id, mode, res = parts[1], parts[2], parts[3]
        
        if task_id not in TASK_STORE: await query.answer("⚠️ Task Expired!", show_alert=True); return
        
        TASK_STORE[task_id].update({'mode': mode, 'res': res})
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
        await query.message.edit(f"♻️ **Initializing...**")
        asyncio.create_task(run_download_upload(client, query.message, info['url'], info['referer'], info['mode'], info['res'], task_id, None))

# ==========================================
# 🚀 ULTRA ENGINE (Cloudflare Support)
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

async def run_download_upload(client, message, url, referer, mode, res, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        file_name = clean_filename(custom_name if custom_name else TASK_STORE[task_id].get('title', 'video'))
        final_path = ""
        thumb_path = None
        duration = 0

        try:
            await message.edit("🚀 **Engine Starting (Bypass Mode)...**")
            out_templ = f"{temp_dir}/{file_name}.%(ext)s"
            
            # 🔥 CRITICAL: কুকি ফাইল ব্যবহার করা হচ্ছে যা Cloudscraper তৈরি করেছে
            ydl_opts = {
                'outtmpl': out_templ,
                'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                'cookiefile': COOKIE_FILE, 
                'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                'http_headers': {'Referer': referer, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
                'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                'socket_timeout': 60,
                'retries': 20,
            }

            # 🛑 ARIA2 DISABLE for this specific site
            # Aria2 কুকি ফাইল রিড করতে পারে না ঠিকমতো এই ধরনের সেশন এর ক্ষেত্রে
            if "m3u8" in url or "instantdl" in url:
                ydl_opts['hls_prefer_native'] = True
                ydl_opts['external_downloader'] = None # Native ব্যবহার হবে
            else:
                ydl_opts['external_downloader'] = ARIA2_EXECUTABLE
                ydl_opts['external_downloader_args'] = ['-x', '16', '-k', '1M']

            if mode == "aud":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
            elif mode == "doc":
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['keepvideo'] = True
            else:
                if res == "best":
                    ydl_opts['format'] = "bestvideo+bestaudio/best"
                else:
                    ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best"
                ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

            # 📥 Start Download
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
            
            for f in os.listdir(temp_dir):
                if f.endswith((".mp4", ".mkv", ".mp3", ".webm", ".ts")):
                    final_path = os.path.join(temp_dir, f)
                    break
            
            # 🛑 SIZE CHECK RELAXED
            if os.path.exists(final_path):
                f_size = os.path.getsize(final_path)
                # যদি ৫০ কেবি এর কম হয় তাহলে এরর
                if f_size < 50 * 1024: 
                     raise Exception("❌ **Protection Block!** Try again later or use Document mode.")

            thumb_path = f"{temp_dir}/{file_name}.jpg"
            if not os.path.exists(thumb_path): thumb_path = None
            duration = int(info.get('duration', 0))
            file_size = os.path.getsize(final_path)

            if file_size > 2 * 1024 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            # 📤 Uploading
            await message.edit(f"⬆️ **Uploading ({mode.upper()})...**")
            start_time = time.time()
            caption = f"📁 **{file_name}**\n💾 Size: {human_readable_size(file_size)}"
            
            if mode == "aud": 
                await client.send_audio(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, progress=upload_hook, progress_args=(message, start_time, task_id))
            elif mode == "doc":
                await client.send_document(message.chat.id, final_path, caption=caption, thumb=thumb_path, force_document=True, progress=upload_hook, progress_args=(message, start_time, task_id))
            else: 
                await client.send_video(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, supports_streaming=True, progress=upload_hook, progress_args=(message, start_time, task_id))
            
            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: logger.error(e); await message.edit(f"❌ **Error:** `{str(e)[:150]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None)

@app.on_message(filters.command("start"))
async def start(c, m): 
    await m.reply("👋 **Bypass Bot Ready!**\n\n✅ **Cloudflare Bypass:** Active\n✅ **Cookie Scraper:** Active\n\nSend link to test!")

print("🔥 Bot Started (Cloudscraper Active)...")
app.run()
