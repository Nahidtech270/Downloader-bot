import os
import time
import math
import asyncio
import logging
import shutil
import uuid
import re
import yt_dlp
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

MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

TASK_STORE = {} 
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {} # প্রোগ্রেস আপডেট টাইমার

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraBot")

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 হেল্পার ফাংশনস
# ==========================================
def human_readable_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def time_formatter(seconds):
    if not seconds: return "0s"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours: return f"{hours}h {minutes}m {seconds}s"
    if minutes: return f"{minutes}m {seconds}s"
    return f"{seconds}s"

# ==========================================
# 📊 লাইভ প্রোগ্রেস বার (Download & Upload)
# ==========================================

# ১. ডাউনলোড প্রোগ্রেস হুক (yt-dlp এর জন্য)
def download_progress_hook(d, message, client, task_id):
    # যদি স্ট্যাটাস 'downloading' হয়
    if d['status'] == 'downloading':
        now = time.time()
        
        # প্রতি ৩ সেকেন্ড পর পর আপডেট করবে (API Limit এড়াতে)
        last_update = LAST_UPDATE_TIME.get(task_id, 0)
        if (now - last_update) < 3: 
            return

        LAST_UPDATE_TIME[task_id] = now
        
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes > 0:
            percentage = downloaded_bytes * 100 / total_bytes
        else:
            percentage = 0
            
        speed = d.get('speed') or 0
        eta = d.get('eta') or 0
        
        # ক্যান্সেল চেক
        if CANCEL_EVENTS.get(task_id):
            raise Exception("CANCELLED_BY_USER")

        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        
        text = (
            f"⬇️ **Downloading...**\n"
            f"[{bar}] **{percentage:.1f}%**\n\n"
            f"📦 Size: `{human_readable_size(downloaded_bytes)} / {human_readable_size(total_bytes)}`\n"
            f"⚡ Speed: `{human_readable_size(speed)}/s`\n"
            f"⏳ ETA: `{time_formatter(eta)}`"
        )

        # Threadsafe ভাবে মেসেজ এডিট কল করা
        try:
            client.loop.create_task(
                message.edit(
                    text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])
                )
            )
        except:
            pass

# ২. আপলোড প্রোগ্রেস হুক (Pyrogram এর জন্য)
async def upload_progress_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id):
        # Pyrogram stop transmission exception
        app.stop_transmission()
        return

    now = time.time()
    diff = now - start_time
    
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        
        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        
        text = (
            f"⬆️ **Uploading...**\n"
            f"[{bar}] **{percentage:.1f}%**\n\n"
            f"📦 Size: `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"⚡ Speed: `{human_readable_size(speed)}/s`\n"
            f"⏳ ETA: `{time_formatter(eta)}`"
        )
        try:
            await message.edit(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])
            )
        except:
            pass

# ==========================================
# 🧠 ফেজ ১: ভিডিও এনালাইসিস
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def analyze_url(client, message):
    url = message.text.strip()
    if not url.startswith(("http", "www")):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Analyzing Link...**\n`Fetching formats...`")
    task_id = str(uuid.uuid4())[:8]

    # কুকি এবং অপশনস
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    }

    try:
        info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        title = info.get('title', 'Video')
        formats = info.get('formats', [])
        
        resolutions = set()
        for f in formats:
            if f.get('height') and f.get('vcodec') != 'none':
                resolutions.add(f['height'])

        sorted_res = sorted(list(resolutions), reverse=True)
        buttons = []
        row = []
        
        for res in sorted_res:
            row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"dl_{task_id}_video_{res}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row: buttons.append(row)

        buttons.append([InlineKeyboardButton("🎵 Extract Audio (MP3)", callback_data=f"dl_{task_id}_audio_0")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="close")])

        TASK_STORE[task_id] = {"url": url, "title": title}

        await status_msg.edit(
            f"🎬 **Video Found!**\n\n📝 **Title:** `{title[:60]}`\n✨ **Select Quality:**",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)[:50]}`")

# ==========================================
# 📥 ফেজ ২: ডাউনলোড এবং আপলোড প্রসেস
# ==========================================
@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    
    if data == "close":
        await query.message.delete()
        return

    if data.startswith("cancel_"):
        task_id = data.split("_")[1]
        CANCEL_EVENTS[task_id] = True
        await query.answer("🛑 Cancelling...", show_alert=False)
        return

    if data.startswith("dl_"):
        parts = data.split("_")
        task_id, mode, res = parts[1], parts[2], parts[3]
        
        if task_id not in TASK_STORE:
            await query.answer("⚠️ Timeout! Send link again.", show_alert=True)
            return

        url = TASK_STORE[task_id]['url']
        await query.message.edit(f"♻️ **Added to Queue...**")
        
        asyncio.create_task(run_download_upload(client, query.message, url, mode, res, task_id))

async def run_download_upload(client, message, url, mode, res, task_id):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        out_templ = f"{temp_dir}/%(title)s.%(ext)s"

        # এখানে আমরা প্রোগ্রেস হুক সেট করছি
        ydl_opts = {
            'outtmpl': out_templ,
            'quiet': True,
            'nocheckcertificate': True,
            'writethumbnail': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
            # এই লাইনটিই আসল কাজ করবে 👇
            'progress_hooks': [lambda d: download_progress_hook(d, message, client, task_id)],
        }

        if mode == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best"

        try:
            await message.edit(f"⬇️ **Starting Download...**")

            # ডাউনলোড শুরু (থ্রেডে)
            def run_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await asyncio.to_thread(run_dl)

            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

            # ফাইল পাথ ফিক্স
            if mode == "audio":
                final_path = os.path.splitext(file_path)[0] + ".mp3"
            else:
                final_path = os.path.splitext(file_path)[0] + ".mp4"
            
            if not os.path.exists(final_path): final_path = file_path 

            # সাইজ চেক
            if os.path.getsize(final_path) > 2000 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            # থাম্বনেইল
            thumb_path = os.path.splitext(file_path)[0] + ".jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            # আপলোড শুরু
            await message.edit(f"⬆️ **Preparing Upload...**")
            start_time = time.time()

            if mode == "audio":
                await client.send_audio(
                    chat_id=message.chat.id,
                    audio=final_path,
                    caption=f"🎵 **{info.get('title')}**\n✅ Quality: 192kbps",
                    duration=int(info.get('duration', 0)),
                    thumb=thumb_path,
                    progress=upload_progress_hook,
                    progress_args=(message, start_time, task_id)
                )
            else:
                await client.send_video(
                    chat_id=message.chat.id,
                    video=final_path,
                    caption=f"🎬 **{info.get('title')}**\n✨ Res: {res}p",
                    duration=int(info.get('duration', 0)),
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=upload_progress_hook,
                    progress_args=(message, start_time, task_id)
                )

            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e):
                await message.edit("⛔ **Cancelled!**")
            else:
                logger.error(f"Error: {e}")
                await message.edit(f"❌ Error: {str(e)[:100]}")
        
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None)
            CANCEL_EVENTS.pop(task_id, None)
            LAST_UPDATE_TIME.pop(task_id, None)

# ==========================================
# 🍪 স্টার্ট কমান্ড
# ==========================================
@app.on_message(filters.document)
async def cookie_handler(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies Updated!**")

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("👋 **Send me a link to Start!**\nWith Live Progress & Quality Selector.")

print("🔥 Bot Started with LIVE DOWNLOAD PROGRESS...")
app.run()
