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
from datetime import datetime

# ==========================================
# 🛠 ১. ডিপেন্ডেন্সি ও টুলস (Cloudscraper Required)
# ==========================================
print("⚙️ System Initializing (Session Injection Mode)...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent", "cloudscraper"]
for pkg in required_packages:
    install_and_import(pkg)

import cloudscraper
import requests
from fake_useragent import UserAgent

try:
    import imageio_ffmpeg
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ==========================================
# ⚙️ কনফিগারেশন
# ==========================================
BOT_TOKEN = "7849157640:AAFyGM8F-Yk7tqH2A_vOfVGqMx6bXPq-pTI"
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"

DOWNLOAD_FOLDER = "downloads"

app = Client("session_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, workers=10, max_concurrent_transmissions=5)

MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SessionBot")

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
# 🕵️‍♂️ CLOUDSCRAPER SESSION EXTRACTOR
# ==========================================
def get_stream_with_cookies(url):
    """
    Cloudscraper ব্যবহার করে লিংক এবং কুকিজ মেমোরিতে লোড করবে
    """
    try:
        # ইউটিউব বা ফেসবুক হলে বাইপাস দরকার নেই
        if any(x in url for x in ["youtube.com", "youtu.be", "facebook.com"]): 
            return url, url, None, None

        print(f"🛡️ Cracking Protection: {url}")
        
        # 🔥 Cloudflare Bypasser
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        response = scraper.get(url, timeout=15)
        
        # কুকিজ এবং হেডার এক্সট্রাক্ট করা (Session Hijack)
        cookies = scraper.cookies.get_dict()
        user_agent = scraper.headers.get('User-Agent')
        
        html = response.text
        
        # Regex to find hidden streams
        patterns = [
            r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'src:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'(https?://[^"\s]+\.m3u8[^"\s]*)',
            r'file:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']'
        ]
        
        stream_url = url # ডিফল্ট
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                found_url = match.group(1).replace('\\/', '/')
                print(f"✅ Found Protected Stream: {found_url}")
                stream_url = found_url
                break
        
        return stream_url, url, cookies, user_agent

    except Exception as e:
        print(f"⚠️ Bypass Error: {e}")
        return url, url, None, None

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
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['referer'], task_info['mode'], task_info['res'], task_id, custom_name, task_info['cookies'], task_info['ua']))
        return

    if not text.startswith("http"):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Bypassing Anti-Bot System...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        # 🔥 নতুন ফাংশন কল
        target_url, referer, cookies, ua = await asyncio.to_thread(get_stream_with_cookies, text)
        is_direct = False
        info = {}
        
        # হেডার কনফিগারেশন (কুকিজ সহ)
        headers = {
            'User-Agent': ua if ua else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': referer
        }

        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'http_headers': headers,
        }
        
        # কুকিজ যদি থাকে, yt-dlp তে পাস করা হবে
        # (এখানে আমরা info এক্সট্রাকশনের জন্য কুকি ফাইল ব্যবহার করছি না, সরাসরি ডাউনলোড ফেজে ইউজ করব)

        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        except:
            is_direct = True
            info = {'title': f'File_{task_id}', 'formats': []}

        title = info.get('title', f'File_{task_id}')
        formats = info.get('formats', [])
        
        buttons = []
        if not is_direct and formats:
            resolutions = sorted(list(set([f.get('height') for f in formats if f.get('height')])), reverse=True)
            if resolutions:
                row = []
                for res in resolutions[:5]:
                    row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"q_{task_id}_vid_{res}"))
                    if len(row) == 3: buttons.append(row); row = []
                if row: buttons.append(row)
        
        ctrl_buttons = [
            [InlineKeyboardButton("🎬 Download (Best)", callback_data=f"q_{task_id}_vid_best")],
            [InlineKeyboardButton("📁 Document (Raw)", callback_data=f"q_{task_id}_doc_best")],
            [InlineKeyboardButton("🎵 Audio Only", callback_data=f"q_{task_id}_aud_0")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close")]
        ]
        for btn in ctrl_buttons: buttons.append(btn)

        # কুকিজ স্টোর করা হচ্ছে
        TASK_STORE[task_id] = {
            "url": target_url, "referer": referer, "title": title, 
            "cookies": cookies, "ua": ua
        }
        
        await status_msg.edit(
            f"📂 **Found:** `{title[:60]}`\n"
            f"🔗 **Stream:** `{target_url[:30]}...`\n"
            f"🔓 **Cookies:** {'✅ Injeceted' if cookies else '❌ None'}", 
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
        asyncio.create_task(run_download_upload(client, query.message, info['url'], info['referer'], info['mode'], info['res'], task_id, None, info['cookies'], info['ua']))

# ==========================================
# 🚀 ULTRA ENGINE (Session Injection)
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

async def run_download_upload(client, message, url, referer, mode, res, task_id, custom_name, cookies, ua):
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
            await message.edit("🚀 **Starting Download (No Aria2)...**")
            out_templ = f"{temp_dir}/{file_name}.%(ext)s"
            
            # হেডার কনফিগারেশন
            req_headers = {
                'Referer': referer, 
                'User-Agent': ua if ua else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }

            ydl_opts = {
                'outtmpl': out_templ,
                'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                'http_headers': req_headers,
                'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                # 🔥 কুকি ডাইরেক্ট ইনজেকশন (ফাইল ছাড়াই)
                # 'cookies': cookies, # yt-dlp এর কিছু ভার্সনে সরাসরি dict সাপোর্ট করে না, তাই নিচের workaround
                
                # 🔥 ARIA2 DISABLED PERMANENTLY FOR THIS FIX
                # Aria2 কুকি সেশন মেইনটেইন করতে পারে না, তাই FFmpeg Native ব্যবহার হচ্ছে
                'external_downloader': None,
                'hls_prefer_native': True, 
                'hls_use_mpegts': True, # Corrupt হওয়া ঠেকায়
                'socket_timeout': 60,
                'retries': 20,
            }

            # কুকিজ থাকলে পাস করা
            if cookies:
                # yt-dlp কুকি ফাইল চায়, তাই আমরা মেমোরি থেকে টেম্প ফাইল বানাব
                temp_cookie = f"{temp_dir}/temp_cookies.txt"
                with open(temp_cookie, 'w') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for key, value in cookies.items():
                        f.write(f".instantdl.cfd\tTRUE\t/\tFALSE\t2600000000\t{key}\t{value}\n")
                ydl_opts['cookiefile'] = temp_cookie

            # Format Selection
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
            
            # 🛑 SIZE CHECK DISABLED
            # আমরা এখন সাইজ চেক বাদ দিচ্ছি কারণ কখনো কখনো স্ট্রিম শুরুতে ছোট থাকে
            # কিন্তু ডাউনলোড শেষে ঠিক হয়ে যায়। তবে ফাইল আছে কিনা চেক করব।
            if not os.path.exists(final_path):
                 raise Exception("❌ **Download Failed!** Stream refused connection.")

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
    await m.reply("👋 **Session Injector Ready!**\n\n✅ Aria2 Disabled (For Security)\n✅ Cookies Injection Active\n✅ 50KB Block Check Removed")

print("🔥 Bot Started (Session Injection Mode)...")
app.run()
