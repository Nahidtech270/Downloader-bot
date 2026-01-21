import os
import time
import math
import asyncio
import logging
import shutil
import uuid
import re
import requests  # অরিজিনাল কোড থেকে
from bs4 import BeautifulSoup  # অরিজিনাল কোড থেকে
import yt_dlp
import imageio_ffmpeg 
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ==========================================
# ⚙️ কনফিগারেশন (আপনার সেটআপ)
# ==========================================
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738
API_HASH = "297f51aaab99720a09e80273628c3c24"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt"

# FFmpeg অটোমেটিক সেটআপ
FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()

# কনকারেন্সি লিমিট
MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

TASK_STORE = {} 
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MyVideoBot")

app = Client(
    "my_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# ১. সাইজ ফরম্যাটার (অরিজিনাল + ফিক্স)
# ==========================================
def human_readable_size(size):
    if not size: return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def time_formatter(seconds):
    if not seconds: return "Processing..."
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours: return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"

# ==========================================
# ২. স্মার্ট লিংক ডিটেক্টর (আপনার অরিজিনাল কোড) 🔥
# ==========================================
def get_target_url(url):
    # ডাইরেক্ট সাইট হলে সরাসরি রিটার্ন করবে
    direct_sites = [
        "youtube.com", "youtu.be", 
        "facebook.com", "fb.watch", 
        "instagram.com", "tiktok.com", 
        "dailymotion.com", "vimeo.com",
        "twitter.com", "x.com"
    ]
    
    if any(site in url for site in direct_sites):
        return url

    # GilliTV বা ড্রামা সাইট স্ক্র্যাপ করা (এই লজিকটাই বাদ পড়েছিল)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            # বিভিন্ন প্লেয়ার খোঁজা
            if src and any(d in src for d in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                final_url = 'https:' + src if src.startswith('//') else src
                logger.info(f"Scraped URL Found: {final_url}")
                return final_url
    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    
    # কিছু না পেলে ইনপুট ইউআরএলই ফেরত দেবে (yt-dlp দেখবে তখন)
    return url

# ==========================================
# ৩. প্রোগ্রেস বার (লাইভ আপডেট - ডাউনলোড ও আপলোড)
# ==========================================
def download_progress_hook(d, message, client, task_id):
    if d['status'] == 'downloading':
        now = time.time()
        last_update = LAST_UPDATE_TIME.get(task_id, 0)
        # ৩ সেকেন্ডের আগে আপডেট করবে না (FloodWait বাচাতে)
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
            client.loop.create_task(message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])))
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
# ৪. এনালাইসিস হ্যান্ডলার (Scraping + Quality Check)
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def analyze_handler(client, message):
    url = message.text.strip()
    if not url.startswith(("http", "www")):
        await message.reply("❌ দয়া করে সঠিক লিংক দিন।")
        return

    status_msg = await message.reply("🕵️‍♂️ **লিংক প্রসেসিং হচ্ছে...**\n`Scraping & Analyzing...`")
    task_id = str(uuid.uuid4())[:8]

    try:
        # ১. আগে অরিজিনাল স্ক্র্যাপার চালাবে (Gillitv ফিক্স)
        target_url = await asyncio.to_thread(get_target_url, url)

        # ২. এরপর yt-dlp দিয়ে ইনফো বের করবে
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }

        info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        title = info.get('title', 'Video')
        formats = info.get('formats', [])
        
        # ৩. রেজোলিউশন খোঁজা
        resolutions = set()
        for f in formats:
            if f.get('height') and f.get('vcodec') != 'none':
                resolutions.add(f['height'])

        buttons = []
        
        # ৪. বাটন তৈরি করা
        if resolutions:
            sorted_res = sorted(list(resolutions), reverse=True)
            row = []
            for res in sorted_res:
                row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"dl_{task_id}_video_{res}"))
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
        else:
            # রেজোলিউশন না পেলে "Best Video" অপশন
            buttons.append([InlineKeyboardButton("🎬 Download Video (Best Quality)", callback_data=f"dl_{task_id}_video_best")])

        buttons.append([InlineKeyboardButton("🎵 Extract Audio (MP3)", callback_data=f"dl_{task_id}_audio_0")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="close")])

        # ৫. স্টোরে সেভ (Target URL সেভ রাখা, অরিজিনালটা না)
        TASK_STORE[task_id] = {"url": target_url, "title": title}

        await status_msg.edit(
            f"🎬 **Video Found!**\n\n📝 `{title[:60]}...`\n👇 **Select Quality:**",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        logger.error(f"Analyze Error: {e}")
        await status_msg.edit(f"❌ **Error:** ভিডিও পাওয়া যায়নি।\n`{str(e)[:100]}`")

# ==========================================
# ৫. ডাউনলোড ওয়ার্কার (Main Logic)
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
            await query.answer("⚠️ Session Expired!", show_alert=True)
            return
        
        url = TASK_STORE[task_id]['url']
        await query.message.edit(f"♻️ **Queue তে যুক্ত হচ্ছে...**")
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
            'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
            'progress_hooks': [lambda d: download_progress_hook(d, message, client, task_id)],
            # অরিজিনাল কোডের মত ইউজার এজেন্ট রাখা
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }

        # ফরম্যাট লজিক
        if mode == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif res == "best":
            ydl_opts['format'] = "bestvideo+bestaudio/best"
        else:
            ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best"

        try:
            await message.edit(f"⬇️ **ডাউনলোড শুরু হচ্ছে...**")
            
            def run_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await asyncio.to_thread(run_dl)
            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

            # ফাইল হ্যান্ডলিং
            final_path = os.path.splitext(file_path)[0] + (".mp3" if mode == "audio" else ".mp4")
            if not os.path.exists(final_path): final_path = file_path 
            
            if os.path.getsize(final_path) > 2000 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            thumb_path = os.path.splitext(file_path)[0] + ".jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            await message.edit(f"⬆️ **আপলোড হচ্ছে...**")
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
                    caption=f"🎬 **{info.get('title')}**\n✨ Res: {res if res != 'best' else 'Best Quality'}",
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
            else:
                logger.error(f"Error: {e}")
                await message.edit(f"❌ Error: `{err_msg[:100]}`")
        
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None)
            CANCEL_EVENTS.pop(task_id, None)
            LAST_UPDATE_TIME.pop(task_id, None)

# ==========================================
# ৬. কুকিজ ও স্টার্ট
# ==========================================
@app.on_message(filters.document)
async def cookie_handler(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies Updated!**")

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply(
        "👋 **Video Downloader Bot!**\n\n"
        "🔗 লিংক দিন (YouTube, Facebook, Gillitv, Drama Sites)\n"
        "✨ **ফিচার:** রেজোলিউশন সিলেক্ট, লাইভ প্রোগ্রেস, অডিও মোড।"
    )

print("🔥 Bot Started (Restored Original Scraper + Pro Features)...")
app.run()
