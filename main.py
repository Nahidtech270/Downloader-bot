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
from datetime import datetime

# ==========================================
# 🛠 ১. অটোমেটিক ডিপেন্ডেন্সি ও টুলস ইনস্টলার (FIXED)
# ==========================================
print("⚙️ System Checking & Installing Dependencies...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing python package: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg", "aiohttp"]
for pkg in required_packages:
    install_and_import(pkg)

# 👇 Aria2c অটোমেটিক সেটআপ (User-Agent ফিক্স করা হয়েছে)
ARIA2_BIN_PATH = os.path.join(os.getcwd(), "aria2c")

def install_aria2_static():
    if os.path.exists(ARIA2_BIN_PATH):
        print("✅ Aria2c already exists.")
        return ARIA2_BIN_PATH
    
    # সিস্টেমে আগে থেকেই আছে কিনা চেক
    aria_sys = shutil.which("aria2c")
    if aria_sys:
        print(f"✅ Found System Aria2c at: {aria_sys}")
        return aria_sys

    print("🚀 Downloading Aria2c Static Binary...")
    try:
        # 🔥 GitHub ব্লক এড়াতে User-Agent যোগ করা হলো
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
        
        import requests
        r = requests.get(url, headers=headers, stream=True)
        r.raise_for_status()

        tar_name = "aria2.tar.bz2"
        with open(tar_name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk: f.write(chunk)
        
        print("📦 Extracting Aria2c...")
        with tarfile.open(tar_name, "r:bz2") as tar:
            for member in tar.getmembers():
                if member.name.endswith("aria2c"):
                    member.name = "aria2c" 
                    tar.extract(member, path=os.getcwd())
                    break
        
        os.chmod(ARIA2_BIN_PATH, os.stat(ARIA2_BIN_PATH).st_mode | stat.S_IEXEC)
        if os.path.exists(tar_name): os.remove(tar_name)
        print(f"✅ Aria2c Successfully Installed at: {ARIA2_BIN_PATH}")
        return ARIA2_BIN_PATH
    except Exception as e:
        print(f"⚠️ Aria2c Install Failed: {e}")
        return None

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
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738
API_HASH = "297f51aaab99720a09e80273628c3c24"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt"

FAKE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://google.com/'
}

try:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_LOCATION = "ffmpeg"

# 🔥 Superfast Client Config
app = Client(
    "ultimate_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN, 
    in_memory=True,
    workers=10, 
    max_concurrent_transmissions=5
)

MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltimateBot")

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 হেল্পার ফাংশন
# ==========================================
def smart_update_ytdlp():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        return True
    except: return False

def human_readable_size(size):
    if not size: return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def time_formatter(seconds):
    if not seconds: return "..."
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h: return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"

def clean_filename(name):
    # ফাইলের নাম খুব বড় হলে সমস্যা হতে পারে, তাই লিমিট করা হলো
    clean = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    return clean[:200] 

# ==========================================
# 💾 ডাইরেক্ট ডাউনলোড হেল্পার
# ==========================================
async def direct_download(url, file_path, message, task_id):
    async with aiohttp.ClientSession(headers=FAKE_HEADERS) as session:
        try:
            async with session.get(url) as response:
                if response.status not in [200, 206]:
                    raise Exception(f"HTTP Error {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()

                with open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(5 * 1024 * 1024): # 5MB Chunk for Speed
                        if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED")
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            now = time.time()
                            if (now - LAST_UPDATE_TIME.get(task_id, 0)) >= 4:
                                LAST_UPDATE_TIME[task_id] = now
                                percentage = downloaded * 100 / total_size if total_size > 0 else 0
                                speed = downloaded / (now - start_time) if (now - start_time) > 0 else 0
                                await update_progress(message, percentage, downloaded, total_size, speed, "⬇️ Direct Downloading...")

        except Exception as e: raise e

# ==========================================
# 📥 প্রোগ্রেস আপডেট ফাংশন
# ==========================================
async def update_progress(message, percentage, current, total, speed, status_text):
    filled = int(percentage // 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    speed_txt = human_readable_size(speed) + "/s"
    text = (f"{status_text}\n[{bar}] **{percentage:.1f}%**\n\n"
            f"📦 `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"🚀 `{speed_txt}`")
    try:
        await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_task")]]))
    except: pass

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
        
        client.loop.create_task(update_progress(message, percentage, current, total, speed, "⬇️ Aria2c Downloading..."))

async def upload_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id): app.stop_transmission(); return
    now = time.time()
    if (now - start_time) % 4 < 0.5 or current == total:
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
        percentage = current * 100 / total
        await update_progress(message, percentage, current, total, speed, "⬆️ Fast Uploading...")

# ==========================================
# 🕵️‍♂️ URL ডিটেক্টর
# ==========================================
def get_target_url(url):
    # কিছু সাইটের জন্য ডাইরেক্ট লিঙ্ক ডিটেকশন
    direct_list = ["youtube", "youtu.be", "facebook", "instagram", "tiktok"]
    if any(x in url for x in direct_list): return url
    
    try:
        # রিডাইরেক্ট চেক
        r = requests.get(url, headers=FAKE_HEADERS, timeout=5, allow_redirects=True)
        return r.url
    except: return url

# ==========================================
# 📨 মেইন লজিক
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    # Rename Check
    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Starting...**")
        del USER_STATE[chat_id]
        
        task_info = TASK_STORE[task_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['mode'], task_info['res'], task_id, custom_name))
        return

    if not text.startswith(("http", "www")):
        await message.reply("❌ Invalid Link")
        return

    status_msg = await message.reply("🕵️‍♂️ **Processing Link...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        target_url = await asyncio.to_thread(get_target_url, text)
        is_direct = False
        info = {}

        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'user_agent': FAKE_HEADERS['User-Agent'],
            'http_headers': FAKE_HEADERS,
        }

        # yt-dlp info extract
        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        except Exception as e:
            # Fallback to Direct Mode
            is_direct = True
            info = {'title': 'Direct_Download', 'formats': []}

        title = info.get('title', 'Video')
        formats = info.get('formats', [])
        
        buttons = []
        if not is_direct and formats:
            resolutions = sorted(list(set([f.get('height') for f in formats if f.get('height')])), reverse=True)
            row = []
            for res in resolutions[:5]:
                row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"q_{task_id}_vid_{res}"))
                if len(row) == 3: buttons.append(row); row = []
            if row: buttons.append(row)
            buttons.append([InlineKeyboardButton("🎵 Audio Only", callback_data=f"q_{task_id}_aud_0")])
        else:
            buttons.append([InlineKeyboardButton("⬇️ Force Download (Direct)", callback_data=f"q_{task_id}_dir_best")])

        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="close")])

        TASK_STORE[task_id] = {"url": target_url, "title": title, "is_direct": is_direct}
        await status_msg.edit(f"📂 **Found:** `{title[:50]}`\n✨ **Select Quality:**", reply_markup=InlineKeyboardMarkup(buttons))

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
        
        if task_id not in TASK_STORE: await query.answer("⚠️ Expired!", show_alert=True); return
        
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
        asyncio.create_task(run_download_upload(client, query.message, info['url'], info['mode'], info['res'], task_id, None))

# ==========================================
# 🚀 সুপারফাস্ট ইঞ্জিন (Aria2 Tuned)
# ==========================================
async def run_download_upload(client, message, url, mode, res, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir) # Clean start
        os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        file_name = clean_filename(custom_name if custom_name else TASK_STORE[task_id].get('title', 'video'))
        final_path = ""
        thumb_path = None
        duration = 0

        try:
            if mode == 'dir':
                await message.edit("⬇️ **Direct Downloading...**")
                final_path = f"{temp_dir}/{file_name}.mp4"
                await direct_download(url, final_path, message, task_id)
            else:
                await message.edit("🚀 **Downloading (Aria2c Engine)...**")
                out_templ = f"{temp_dir}/{file_name}.%(ext)s"
                
                # 🔥 ARIA2 CONFIGURATION (CRITICAL FIX FOR FRAGMENT ERRORS)
                ydl_opts = {
                    'outtmpl': out_templ,
                    'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                    'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
                    'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                    'http_headers': FAKE_HEADERS,
                    'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                    # 👇 এই সেটিংসগুলো ফিক্স করা হয়েছে
                    'external_downloader': ARIA2_EXECUTABLE,
                    'external_downloader_args': [
                        '-x', '16',    # ১৬টি কানেকশন
                        '-k', '10M',   # 🔥 FIX: 1MB এর বদলে 10MB (ডিস্ক এরর কমাবে)
                        '-s', '16',
                        '--min-split-size=10M'
                    ] if ARIA2_EXECUTABLE else []
                }
                
                if mode == "aud":
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
                else:
                    ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best" if res != "best" else "best"
                    ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

                def run_dl():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return ydl.prepare_filename(info), info
                
                temp_path, info = await asyncio.to_thread(run_dl)
                final_path = temp_path
                
                # এক্সটেনশন চেক
                base, ext = os.path.splitext(temp_path)
                if mode == "aud" and ext != ".mp3": final_path = base + ".mp3"
                elif mode == "vid" and ext != ".mp4": final_path = base + ".mp4"
                
                if not os.path.exists(final_path): final_path = temp_path # যদি কনভার্ট না হয়

                thumb_path = base + ".jpg"
                if not os.path.exists(thumb_path): thumb_path = base + ".webp"
                if not os.path.exists(thumb_path): thumb_path = None
                duration = int(info.get('duration', 0))

            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED")
            
            # সাইজ চেক
            if os.path.exists(final_path) and os.path.getsize(final_path) > 2 * 1024 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            await message.edit("⬆️ **Uploading...**")
            start_time = time.time()
            caption = f"🎬 **{file_name}**\n✅ Downloaded by Bot"
            
            if mode == "aud": 
                await client.send_audio(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, progress=upload_hook, progress_args=(message, start_time, task_id))
            else: 
                await client.send_video(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, supports_streaming=True, progress=upload_hook, progress_args=(message, start_time, task_id))
            
            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: logger.error(e); await message.edit(f"❌ **Error:** `{str(e)[:100]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None)

@app.on_message(filters.document)
async def cookie_handler(c, m): 
    await m.download(file_name=COOKIE_FILE)
    await m.reply("✅ **Cookies Updated!**")

@app.on_message(filters.command("start"))
async def start(c, m): 
    await m.reply("👋 **Superfast Bot Ready!**\n\n✅ Aria2c Engine: ON\n✅ Auto-Resume: ON\n\nSend Link -> Select Quality -> Enjoy!")

print("🔥 Bot Started with Optimized Aria2 Engine...")
app.run()
