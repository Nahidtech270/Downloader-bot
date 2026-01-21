import os
import sys
import time
import math
import asyncio
import logging
import shutil
import uuid
import re
import subprocess
import importlib.util

# ==========================================
# 🛠 স্মার্ট ডিপেন্ডেন্সি চেকার (বট চালুর আগেই চেক করবে)
# ==========================================
def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing missing package: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# প্রয়োজনীয় লাইব্রেরি চেক
required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg"]
for pkg in required_packages:
    install_and_import(pkg)

import requests
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

# FFmpeg লোকেশন সেটআপ
print("🔧 Checking System Tools...")
try:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"✅ FFmpeg found at: {FFMPEG_LOCATION}")
except Exception as e:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()

MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# মেমোরি স্টোর
TASK_STORE = {} 
USER_STATE = {} # ইউজার এখন কোন অবস্থায় আছে (লিংক দিচ্ছে নাকি নাম দিচ্ছে)
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AdvancedBot")

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

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
    return re.sub(r'[\\/*?:"<>|]', '', name)

# ==========================================
# 🕵️‍♂️ অরিজিনাল স্ক্র্যাপার (আপনার অরিজিনাল কোড)
# ==========================================
def get_target_url(url):
    direct_sites = ["youtube.com", "youtu.be", "facebook.com", "fb.watch", "instagram.com", "tiktok.com", "dailymotion.com", "vimeo.com", "twitter.com", "x.com"]
    if any(site in url for site in direct_sites): return url

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src and any(d in src for d in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                return 'https:' + src if src.startswith('//') else src
    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    return url

# ==========================================
# 📊 প্রোগ্রেস হুক
# ==========================================
def download_progress_hook(d, message, client, task_id):
    if d['status'] == 'downloading':
        now = time.time()
        last_update = LAST_UPDATE_TIME.get(task_id, 0)
        if (now - last_update) < 3: return
        LAST_UPDATE_TIME[task_id] = now
        
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        current = d.get('downloaded_bytes', 0)
        percentage = current * 100 / total if total > 0 else 0
        speed = d.get('speed') or 0
        eta = d.get('eta') or 0
        
        if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        text = (f"⬇️ **Downloading...**\n[{bar}] **{percentage:.1f}%**\n\n"
                f"📦 Size: `{human_readable_size(current)} / {human_readable_size(total)}`\n"
                f"⚡ Speed: `{human_readable_size(speed)}/s`\n⏳ ETA: `{time_formatter(eta)}`")
        try:
            client.loop.create_task(message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])))
        except: pass

async def upload_progress_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id): app.stop_transmission(); return
    now = time.time()
    if round((now - start_time) % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        text = (f"⬆️ **Uploading...**\n[{bar}] **{percentage:.1f}%**\n\n"
                f"📦 Size: `{human_readable_size(current)} / {human_readable_size(total)}`\n"
                f"⚡ Speed: `{human_readable_size(speed)}/s`\n⏳ ETA: `{time_formatter(eta)}`")
        try: await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
        except: pass

# ==========================================
# 📨 টেক্সট হ্যান্ডলার (লিংক + রিনেম ইনপুট)
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    # ১. রিনেম চেকিং: ইউজার কি নাম পরিবর্তন করার জন্য মেসেজ দিয়েছে?
    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        
        # নতুন নাম সেট করা
        custom_name = clean_filename(text)
        
        # আগের মেসেজটি আপডেট করা (যেখানে নাম দিতে বলা হয়েছিল)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Starting Download...**")
        
        # স্ট্যাটাস ক্লিয়ার
        del USER_STATE[chat_id]
        
        # মেইন ডাউনলোড ফাংশন কল করা
        task_info = TASK_STORE[task_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['mode'], task_info['res'], task_id, custom_name))
        return

    # ২. যদি রিনেম না হয়, তবে এটি একটি নতুন লিংক
    if not text.startswith(("http", "www")):
        await message.reply("❌ Invalid Link")
        return

    status_msg = await message.reply("🕵️‍♂️ **System Checking & Analyzing...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        target_url = await asyncio.to_thread(get_target_url, text) # অরিজিনাল স্ক্র্যাপার

        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        }

        # অটো আপডেট লজিক সহ ইনফো এক্সট্রাকশন
        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        except Exception as e:
            if "ExtractorError" in str(e) or "403" in str(e):
                await status_msg.edit("🔧 **System Updating...**")
                await asyncio.to_thread(smart_update_ytdlp)
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
            else: raise e

        title = info.get('title', 'Video')
        formats = info.get('formats', [])
        resolutions = set()
        for f in formats:
            if f.get('height') and f.get('vcodec') != 'none': resolutions.add(f['height'])

        buttons = []
        if resolutions:
            sorted_res = sorted(list(resolutions), reverse=True)
            row = []
            for res in sorted_res:
                row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"qual_{task_id}_video_{res}"))
                if len(row) == 3: buttons.append(row); row = []
            if row: buttons.append(row)
        else:
            buttons.append([InlineKeyboardButton("🎬 Download (Best Quality)", callback_data=f"qual_{task_id}_video_best")])

        buttons.append([InlineKeyboardButton("🎵 Only Audio (MP3)", callback_data=f"qual_{task_id}_audio_0")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="close")])

        TASK_STORE[task_id] = {"url": target_url, "title": title}
        await status_msg.edit(f"🎬 **Found:** `{title[:50]}`\n✨ **Select Quality:**", reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)[:100]}`")

# ==========================================
# 🔘 কলব্যাক হ্যান্ডলার (কোয়ালিটি এবং রিনেম)
# ==========================================
@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    
    if data == "close": 
        await query.message.delete()
        if query.message.chat.id in USER_STATE: del USER_STATE[query.message.chat.id]
        return

    if data.startswith("cancel_"):
        task_id = data.split("_")[1]
        CANCEL_EVENTS[task_id] = True
        await query.answer("🛑 Cancelling...", show_alert=False)
        return

    # ১. কোয়ালিটি সিলেক্ট করার পর -> নাম চাইবে
    if data.startswith("qual_"):
        parts = data.split("_")
        task_id, mode, res = parts[1], parts[2], parts[3]
        
        if task_id not in TASK_STORE: await query.answer("⚠️ Session Expired!", show_alert=True); return
        
        # টাস্কে ডাটা আপডেট
        TASK_STORE[task_id]['mode'] = mode
        TASK_STORE[task_id]['res'] = res
        
        # ইউজারকে রিনেম অপশন দেওয়া
        default_name = TASK_STORE[task_id]['title']
        
        # ইউজারের স্টেট সেট করা (এখন বট নামের জন্য অপেক্ষা করবে)
        USER_STATE[query.message.chat.id] = {
            'state': 'waiting_name',
            'task_id': task_id,
            'msg': query.message
        }

        await query.message.edit(
            f"📝 **File Name:**\n`{default_name}`\n\n"
            "👇 **Choose Option:**\n"
            "1. Send a **New Name** (Text Message)\n"
            "2. Click **Default Name** to keep original.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Use Default Name", callback_data=f"startdef_{task_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="close")]
            ])
        )

    # ২. ডিফল্ট নাম দিয়ে শুরু করা
    if data.startswith("startdef_"):
        task_id = data.split("_")[1]
        if task_id not in TASK_STORE: await query.answer("⚠️ Expired!", show_alert=True); return
        
        # স্টেট ক্লিয়ার
        if query.message.chat.id in USER_STATE: del USER_STATE[query.message.chat.id]

        task_info = TASK_STORE[task_id]
        await query.message.edit(f"♻️ **Starting Download...**")
        
        # ডিফল্ট টাইটেল পাস করা হবে (None মানে ডিফল্ট)
        asyncio.create_task(run_download_upload(client, query.message, task_info['url'], task_info['mode'], task_info['res'], task_id, None))

# ==========================================
# 📥 মেইন ডাউনলোড প্রসেস (কাস্টম নাম সহ)
# ==========================================
async def run_download_upload(client, message, url, mode, res, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        
        # নাম সেটআপ
        if custom_name:
            out_templ = f"{temp_dir}/{custom_name}.%(ext)s"
        else:
            out_templ = f"{temp_dir}/%(title)s.%(ext)s"

        ydl_opts = {
            'outtmpl': out_templ,
            'quiet': True,
            'nocheckcertificate': True,
            'writethumbnail': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
            'progress_hooks': [lambda d: download_progress_hook(d, message, client, task_id)],
        }

        if mode == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
        elif res == "best":
            ydl_opts['format'] = "bestvideo+bestaudio/best"
        else:
            ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best"

        try:
            await message.edit(f"⬇️ **Downloading...**")
            
            def run_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await asyncio.to_thread(run_dl)
            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

            final_path = os.path.splitext(file_path)[0] + (".mp3" if mode == "audio" else ".mp4")
            if not os.path.exists(final_path): final_path = file_path 
            
            # থাম্বনেইল
            thumb_path = os.path.splitext(file_path)[0] + ".jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            await message.edit(f"⬆️ **Uploading...**")
            start_time = time.time()

            # ক্যাপশন তৈরি
            file_name_display = custom_name if custom_name else info.get('title')
            caption = f"🎬 **{file_name_display}**\n✅ Downloaded by Bot"

            media_func = client.send_audio if mode == "audio" else client.send_video
            kwargs = {
                "chat_id": message.chat.id,
                "caption": caption,
                "thumb": thumb_path,
                "duration": int(info.get('duration', 0)),
                "progress": upload_progress_hook,
                "progress_args": (message, start_time, task_id)
            }
            if mode == "video":
                kwargs["video"] = final_path
                kwargs["supports_streaming"] = True
            else:
                kwargs["audio"] = final_path
            
            await media_func(**kwargs)
            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: await message.edit(f"❌ **Error:** `{str(e)[:100]}`")
        
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None); LAST_UPDATE_TIME.pop(task_id, None)

@app.on_message(filters.document)
async def cookie_handler(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies Updated!**")

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("👋 **Bot Online!**\nSend link -> Select Quality -> Rename (Optional) -> Enjoy!")

print("🔥 Bot Started with Rename System & Original Logic...")
app.run()
