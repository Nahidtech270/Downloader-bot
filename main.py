import os
import time
import math
import asyncio
import logging
import shutil
import uuid
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

# ==========================================
# ⚙️ কনফিগারেশন (Configuration)
# ==========================================
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738
API_HASH = "297f51aaab99720a09e80273628c3c24"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt"

# কনকারেন্সি লিমিট (একসাথে ৩টা প্রসেস)
MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# মেমোরি স্টোরেজ (টেম্পোরারি ডাটা রাখার জন্য)
TASK_STORE = {} 
CANCEL_EVENTS = {} # ডাউনলোড ক্যান্সেল করার জন্য ইভেন্ট স্টোর

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraBot")

app = Client("ultra_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 হেল্পার ফাংশনস (Helpers)
# ==========================================
def human_readable_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def time_formatter(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours: return f"{hours}h {minutes}m {seconds}s"
    if minutes: return f"{minutes}m {seconds}s"
    return f"{seconds}s"

# ==========================================
# 📊 স্মার্ট প্রোগ্রেস বার (Smart Progress)
# ==========================================
async def progress_hook(current, total, message, start_time, task_id):
    # যদি ইউজার ক্যান্সেল বাটন চাপে, তবে এরর রেইজ করবে
    if task_id in CANCEL_EVENTS and CANCEL_EVENTS[task_id]:
        raise Exception("CANCELLED")

    now = time.time()
    diff = now - start_time
    
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        
        # গ্রাফিক্যাল বার
        filled = int(percentage // 10)
        bar = "▓" * filled + "░" * (10 - filled)
        
        text = (
            f"⬇️ **Downloading...**\n"
            f"[{bar}] **{percentage:.1f}%**\n\n"
            f"💾 **Done:** `{human_readable_size(current)} / {human_readable_size(total)}`\n"
            f"🚀 **Speed:** `{human_readable_size(speed)}/s`\n"
            f"⏳ **ETA:** `{time_formatter(eta)}`"
        )
        
        try:
            # ক্যান্সেল বাটন সহ এডিট
            await message.edit(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])
            )
        except:
            pass

# ==========================================
# 🧠 ফেজ ১: ভিডিও এনালাইসিস (Analysis)
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def analyze_url(client, message):
    url = message.text.strip()
    if not url.startswith(("http", "www")):
        await message.reply("❌ Invalid URL")
        return

    status_msg = await message.reply("🔍 **Analyzing Link...**\n`Please wait while I fetch formats...`")
    
    # টাস্ক আইডি তৈরি (Unique ID)
    task_id = str(uuid.uuid4())[:8]
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    try:
        # ডাউনলোড না করে শুধু মেটাডাটা আনা (Extract Info)
        info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        
        # টাইটেল ছোট করা
        title = info.get('title', 'Video')
        if len(title) > 50: title = title[:50] + "..."
        
        # বাটন তৈরি করা
        buttons = []
        
        # ভিডিও অপশন (Best Quality)
        buttons.append([InlineKeyboardButton(f"🎬 Video (Best Quality)", callback_data=f"dl_{task_id}_video")])
        
        # অডিও অপশন
        buttons.append([InlineKeyboardButton(f"🎵 Audio (MP3)", callback_data=f"dl_{task_id}_audio")])
        
        # ক্লোজ বাটন
        buttons.append([InlineKeyboardButton("❌ Close", callback_data="close")])

        # মেমোরিতে ডাটা সেভ রাখা
        TASK_STORE[task_id] = {
            "url": url,
            "title": title,
            "chat_id": message.chat.id,
            "msg_id": status_msg.id
        }

        await status_msg.edit(
            f"🎬 **Found:** `{title}`\n\n❓ **Select Format:**",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** Could not fetch info.\n`{str(e)[:100]}`")

# ==========================================
# 📥 ফেজ ২: ডাউনলোড হ্যান্ডলার (Callback)
# ==========================================
@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    
    if data == "close":
        await query.message.delete()
        return

    if data.startswith("cancel_"):
        task_id = data.split("_")[1]
        CANCEL_EVENTS[task_id] = True # ক্যান্সেল ফ্ল্যাগ সেট করা
        await query.answer("🛑 Cancelling...", show_alert=False)
        return

    if data.startswith("dl_"):
        _, task_id, mode = data.split("_")
        
        if task_id not in TASK_STORE:
            await query.answer("⚠️ Session Expired!", show_alert=True)
            return

        task_info = TASK_STORE[task_id]
        url = task_info['url']
        
        # ডাউনলোড শুরু
        await query.message.edit(f"⏳ **Added to Queue...**")
        asyncio.create_task(start_download(client, query.message, url, mode, task_id))

async def start_download(client, message, url, mode, task_id):
    async with semaphore: # কিউ কন্ট্রোল
        # ফোল্ডার পাথ সেটআপ
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        
        out_templ = f"{temp_dir}/%(title)s.%(ext)s"
        CANCEL_EVENTS[task_id] = False # রিসেট

        ydl_opts = {
            'outtmpl': out_templ,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'writethumbnail': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            # প্রোগ্রেস হুক সেট করা হচ্ছে না সরাসরি, কারণ yt-dlp এর হুক async সাপোর্ট করে না ভালোভাবে, 
            # আমরা ম্যানুয়ালি হ্যান্ডেল করবো অথবা basic logger ব্যবহার করবো। 
            # *Pro Tip:* Pyrogram এর progress bar upload এর সময় কাজ করবে। ডাউনলোডের সময় yt-dlp এর output পার্স করা জটিল, 
            # তাই এখানে সিম্পলিসিটির জন্য ডাউনলোডের সময় "Downloading..." দেখাবে, আপলোডের সময় রিয়েল প্রোগ্রেস দেখাবে।
        }

        # মোড অনুযায়ী ফরম্যাট সেট
        if mode == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
            # সব ভিডিও MP4 এ কনভার্ট হবে (Telegram Friendly)
            ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

        try:
            await message.edit(f"⬇️ **Downloading ({mode.upper()})...**\n`Please wait, large files take time.`", 
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))

            # রান YT-DLP
            def run_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info

            # ক্যান্সেল চেক করার জন্য লুপে ফেলার চেয়ে থ্রেডে রান করাই ভালো, তবে ক্যান্সেল এখানে ফোর্সফুলি করা কঠিন।
            # তাই আমরা আপলোডের সময় ক্যান্সেল অপশনটা বেশি কার্যকর করবো।
            file_path, info = await asyncio.to_thread(run_dl)

            # ক্যান্সেল চেক
            if CANCEL_EVENTS.get(task_id):
                raise Exception("CANCELLED")

            # ফাইল প্রসেসিং (MP3/MP4 এক্সটেনশন ফিক্স)
            if mode == "audio":
                file_path = os.path.splitext(file_path)[0] + ".mp3"
            elif mode == "video" and not os.path.exists(file_path):
                file_path = os.path.splitext(file_path)[0] + ".mp4"

            if not os.path.exists(file_path):
                raise Exception("File not found after download.")

            # মেটাডাটা
            title = info.get('title', 'Downloaded Media')
            duration = int(info.get('duration', 0))
            thumb = file_path.rsplit(".", 1)[0] + ".jpg" # থাম্বনেইল পাথ
            if not os.path.exists(thumb): thumb = None

            # আপলোড ফেজ
            await message.edit(f"⬆️ **Uploading...**")
            start_time = time.time()

            if mode == "video":
                await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=f"🎬 **{title}**\n✅ Downloaded by UltraBot",
                    thumb=thumb,
                    duration=duration,
                    supports_streaming=True,
                    progress=progress_hook,
                    progress_args=(message, start_time, task_id)
                )
            else:
                await client.send_audio(
                    chat_id=message.chat.id,
                    audio=file_path,
                    caption=f"🎵 **{title}**\n✅ Downloaded by UltraBot",
                    thumb=thumb,
                    duration=duration,
                    progress=progress_hook,
                    progress_args=(message, start_time, task_id)
                )

            await message.delete()

        except Exception as e:
            err = str(e)
            if "CANCELLED" in err:
                await message.edit("⛔ **Download Cancelled by User.**")
            else:
                logger.error(f"Error: {e}")
                await message.edit(f"❌ **Failed:** `{err[:100]}`")

        finally:
            # ক্লিনআপ (ফোল্ডার ডিলিট)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            if task_id in TASK_STORE: del TASK_STORE[task_id]
            if task_id in CANCEL_EVENTS: del CANCEL_EVENTS[task_id]

# ==========================================
# 🍪 কুকি রিসিভার
# ==========================================
@app.on_message(filters.document)
async def handle_cookies(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies Updated!**\nSystem is now refreshed.")

# ==========================================
# 🏁 স্টার্ট কমান্ড
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "👋 **Welcome to Ultra Pro Downloader!**\n\n"
        "🔥 **Features:**\n"
        "• Quality Selection (Video/Audio)\n"
        "• Smart Queue System\n"
        "• Cancel Button\n"
        "• Auto MP4/MP3 Conversion\n\n"
        "🔗 **Just send me any link to start!**"
    )

print("🚀 Ultra Pro Bot is Running...")
app.run()
