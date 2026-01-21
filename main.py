import os
import time
import math
import asyncio
import logging
import shutil
import uuid
import re
import yt_dlp
# নতুন ইম্পোর্ট
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

# FFmpeg এর লোকেশন অটোমেটিক সেট করা হচ্ছে
FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()

MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

TASK_STORE = {} 
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraBot")

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 সিস্টেম চেক (System Check)
# ==========================================
# বট অন হওয়ার সাথে সাথে চেক করবে FFmpeg আছে কিনা
print(f"🔧 System Check: FFmpeg found at: {FFMPEG_LOCATION}")

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
# 📊 লাইভ প্রোগ্রেস বার
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
        
        text = (
            f"⬇️ **Downloading...**\n"
            f"[{bar}] **{percentage:.1f}%**\n\n"
            f"📦 Size: `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"⚡ Speed: `{human_readable_size(speed)}/s`\n"
            f"⏳ ETA: `{time_formatter(eta)}`"
        )
        try:
            client.loop.create_task(
                message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
            )
        except: pass

async def upload_progress_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id):
        app.stop_transmission()
        return

    now = time.time()
    if round((now - start_time) % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
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
            await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
        except: pass

# ==========================================
# 🧠 ফেজ ১: ভিডিও এনালাইসিস
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def analyze_url(client, message):
    url = message.text.strip()
    if not url.startswith(("http", "www")):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Analyzing Link...**")
    task_id = str(uuid.uuid4())[:8]

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
        await status_msg.edit(f"🎬 **Video Found!**\n\n📝 **Title:** `{title[:60]}`\n✨ **Select Quality:**", reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)[:100]}`")

# ==========================================
# 📥 ফেজ ২: ডাউনলোড এবং আপলোড
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
            await query.answer("⚠️ Timeout!", show_alert=True)
            return
        url = TASK_STORE[task_id]['url']
        await query.message.edit(f"♻️ **Processing...**")
        asyncio.create_task(run_download_upload(client, query.message, url, mode, res, task_id))

async def run_download_upload(client, message, url, mode, res, task_id):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        out_templ = f"{temp_dir}/%(title)s.%(ext)s"

        ydl_opts = {
            'outtmpl': out_templ,
            'quiet': True,
            'nocheckcertificate': True,
            'writethumbnail': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            # ✅ FFmpeg লোকেশন ম্যানুয়ালি সেট করা হলো
            'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
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
            
            def run_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await asyncio.to_thread(run_dl)
            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

            final_path = os.path.splitext(file_path)[0] + (".mp3" if mode == "audio" else ".mp4")
            if not os.path.exists(final_path): final_path = file_path 
            
            if os.path.getsize(final_path) > 2000 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            thumb_path = os.path.splitext(file_path)[0] + ".jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            await message.edit(f"⬆️ **Uploading...**")
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
            err_msg = str(e)
            if "CANCELLED" in err_msg:
                await message.edit("⛔ **Cancelled!**")
            elif "ffmpeg" in err_msg.lower():
                await message.edit("❌ **Server Error:** FFmpeg not installed!")
            else:
                logger.error(f"Error: {e}")
                await message.edit(f"❌ Error: `{err_msg[:100]}`")
        
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None)
            CANCEL_EVENTS.pop(task_id, None)
            LAST_UPDATE_TIME.pop(task_id, None)

@app.on_message(filters.document)
async def cookie_handler(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies Updated!**")

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply("👋 **Bot is Online!**\nSend a link to start.")

print("🔥 Bot Started with FFmpeg Support...")
app.run()
