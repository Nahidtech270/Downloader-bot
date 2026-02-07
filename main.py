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

# ==========================================
# 🛠 ১. সিস্টেম ও ডিপেন্ডেন্সি (No Shortuts)
# ==========================================
print("⚙️ System Initializing: Installing Core Modules...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing: {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except: pass

required_packages = [
    "pyrogram", "tgcrypto", "yt_dlp", "requests", 
    "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent", "cloudscraper"
]

for pkg in required_packages:
    install_and_import(pkg)

import cloudscraper
import requests
import aiohttp
from fake_useragent import UserAgent
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

try:
    import imageio_ffmpeg
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

# ==========================================
# 🛠 ২. Aria2c সেটআপ
# ==========================================
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

# ==========================================
# ⚙️ ৩. বট কনফিগারেশন
# ==========================================
BOT_TOKEN = "7671188399:AAHDUsNWxGBT7HmzAb68LDV8UugM9aC9WOU"
API_ID = 28870226
API_HASH = "a5b1ff3f75941649bf5bc159782f0f00"

DOWNLOAD_FOLDER = "downloads"

app = Client(
    "final_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN, 
    in_memory=True, 
    workers=20, 
    max_concurrent_transmissions=10
)

MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FinalBot")

if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 ৪. হেল্পার ফাংশন
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
# 🕵️‍♂️ ৫. সুপার স্ক্র্যাপার (The Fix)
# ==========================================
def get_real_video_link(page_url):
    """
    এই ফাংশনটি পুরো পেজ স্ক্যান করে লুকানো .m3u8 বা .mp4 লিংক বের করবে।
    এটি Cloudscraper ব্যবহার করে যাতে Cloudflare বাইপাস হয়।
    """
    print(f"🕵️‍♂️ Deep Scanning: {page_url}")
    
    # ব্রাউজার হেডার
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://google.com/'
    }

    try:
        # ১. Cloudscraper দিয়ে পেজ সোর্স আনা
        scraper = cloudscraper.create_scraper()
        response = scraper.get(page_url, headers=headers, timeout=20)
        html = response.text
        final_url = page_url
        is_stream = False

        # ২. শক্তিশালী Regex সার্চ (সব প্যাটার্ন)
        patterns = [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',  # যেকোনো m3u8 লিংক
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',   # যেকোনো mp4 লিংক
            r'file:\s*["\']([^"\']+)["\']',               # JWPlayer/Plyr pattern
            r'src:\s*["\']([^"\']+)["\']',
            r'source\s*=\s*["\']([^"\']+)["\']',
        ]

        found_links = []
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                # আবর্জনা পরিষ্কার করা
                clean_link = match.replace('\\/', '/')
                if not clean_link.startswith('http'):
                    # রিলেটিভ লিংক হলে ডোমেইন জোড়া লাগানো
                    clean_link = urljoin(page_url, clean_link)
                
                # ভ্যালিড এক্সটেনশন চেক
                if '.m3u8' in clean_link or '.mp4' in clean_link:
                    found_links.append(clean_link)

        # ৩. সেরা লিংকটি বাছাই করা
        if found_links:
            # সাধারণত শেষের দিকের লিংকটি আসল হয় (High Quality)
            # তবে আমরা m3u8 কে প্রাধান্য দেব
            m3u8_links = [l for l in found_links if '.m3u8' in l]
            if m3u8_links:
                final_url = m3u8_links[0] # প্রথম m3u8 টা নিচ্ছি
                is_stream = True
            else:
                final_url = found_links[0]
                is_stream = True
            
            print(f"✅ Extracted Video Link: {final_url}")
        else:
            print("⚠️ No hidden link found via Regex. Using original URL.")

        return {
            'original_url': page_url,
            'video_url': final_url,
            'is_stream': is_stream,
            'headers': {
                'User-Agent': headers['User-Agent'],
                'Referer': page_url # 🔥 আসল পেজটিকেই Referer হিসেবে ব্যবহার করব
            }
        }

    except Exception as e:
        print(f"❌ Scrape Failed: {e}")
        return {
            'original_url': page_url,
            'video_url': page_url,
            'is_stream': False,
            'headers': headers
        }

# ==========================================
# 🤖 ৬. বট হ্যান্ডলার
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
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info, task_id, custom_name))
        return

    if not text.startswith("http"):
        await message.reply("❌ **Invalid Link!**")
        return

    status_msg = await message.reply("🕵️‍♂️ **Hacking Link Protection...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        # 🔥 স্ক্র্যাপার কল করা হচ্ছে
        link_data = await asyncio.to_thread(get_real_video_link, text)
        
        # টাইটেল বের করা
        title = "Video_File"
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'http_headers': link_data['headers']}
            # আমরা অরিজিনাল ইউআরএল থেকে টাইটেল নেব, কিন্তু ডাউনলোড করব video_url থেকে
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(link_data['original_url'], download=False))
            title = info.get('title', f"Video_{task_id}")
        except:
            title = f"Video_{task_id}"

        # টাস্ক স্টোর
        TASK_STORE[task_id] = {
            "link_data": link_data,
            "title": title
        }

        # বাটন
        ctrl_buttons = [
            [InlineKeyboardButton("🎬 Download (Auto)", callback_data=f"q_{task_id}_vid_best")],
            [InlineKeyboardButton("📁 Document (Raw)", callback_data=f"q_{task_id}_doc_best")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close")]
        ]

        await status_msg.edit(
            f"📂 **Found:** `{title[:60]}`\n"
            f"🔗 **Real Source:** `{link_data['video_url'][:40]}...`\n"
            f"🛡️ **Referer:** Set to Original Page", 
            reply_markup=InlineKeyboardMarkup(ctrl_buttons)
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
        
        await query.message.edit(f"♻️ **Starting Engines...**")
        asyncio.create_task(run_download_upload(client, query.message, TASK_STORE[task_id], task_id, None))

# ==========================================
# 🚀 ৭. মেইন ডাউনলোডার ইঞ্জিন (Manual Header Injection)
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

async def run_download_upload(client, message, task_info, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        
        # ডাটা লোড
        link_data = task_info['link_data']
        # 🔥 আসল ভিডিও লিংক ব্যবহার করছি, পেজ লিংক নয়
        target_url = link_data['video_url'] 
        headers = link_data['headers']
        
        mode = task_info['mode']
        file_name = clean_filename(custom_name if custom_name else task_info.get('title', 'video'))
        final_path = ""
        thumb_path = None
        duration = 0

        try:
            await message.edit("🚀 **Downloading (Extracted Link)...**")
            out_templ = f"{temp_dir}/{file_name}.%(ext)s"
            
            # 🔥 yt-dlp কনফিগারেশন (Header Mirroring)
            ydl_opts = {
                'outtmpl': out_templ,
                'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                
                # 🔥 এই অংশটি সবচেয়ে গুরুত্বপূর্ণ: Referer পাস করা
                'http_headers': headers,
                
                'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                'socket_timeout': 60,
                'retries': 20,
            }

            # ইঞ্জিন সেটিংস
            # যদি m3u8 লিংক হয়, তবে Native ব্যবহার করব (Safe)
            if ".m3u8" in target_url:
                ydl_opts['hls_prefer_native'] = True
                ydl_opts['hls_use_mpegts'] = True
                ydl_opts['external_downloader'] = None 
            else:
                # ডাইরেক্ট mp4 হলে Aria2
                ydl_opts['external_downloader'] = ARIA2_EXECUTABLE
                ydl_opts['external_downloader_args'] = ['-x', '16', '-k', '1M']

            # ফরম্যাট
            if mode == "aud":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
            elif mode == "doc":
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['keepvideo'] = True
            else:
                ydl_opts['format'] = "bestvideo+bestaudio/best"
                ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

            # 📥 ডাউনলোড শুরু
            try:
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=True))
            except Exception as e:
                # যদি এক্সট্র্যাক্টেড লিংক কাজ না করে, তবে অরিজিনাল লিংক দিয়ে শেষ চেষ্টা
                print(f"Extraction failed, trying original: {e}")
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(link_data['original_url'], download=True))

            # ফাইল খোঁজা
            for f in os.listdir(temp_dir):
                if f.endswith((".mp4", ".mkv", ".mp3", ".webm", ".ts")):
                    final_path = os.path.join(temp_dir, f)
                    break
            
            if not os.path.exists(final_path): raise Exception("Download Failed! No file found.")
            
            # সাইজ চেক
            file_size = os.path.getsize(final_path)
            if file_size > 2 * 1024 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return
            
            # যদি ফাইল খুব ছোট হয় (এরর পেজ), তবে ওয়ার্নিং
            if file_size < 50 * 1024:
                await message.edit("⚠️ **Warning:** Downloaded file is too small (might be an error page). Uploading anyway...")

            thumb_path = f"{temp_dir}/{file_name}.jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            # 📤 আপলোড
            async def upload_progress(current, total):
                if CANCEL_EVENTS.get(task_id): app.stop_transmission()
                now = time.time()
                if (now - LAST_UPDATE_TIME.get(task_id, 0)) >= 4:
                    LAST_UPDATE_TIME[task_id] = now
                    pct = current * 100 / total
                    spd = current / (now - start_time) if (now - start_time) > 0 else 0
                    await update_progress(message, pct, current, total, spd, "⬆️ Uploading...")

            await message.edit(f"⬆️ **Uploading ({mode.upper()})...**")
            start_time = time.time()
            caption = f"📁 **{file_name}**\n💾 Size: {human_readable_size(file_size)}\n🤖 Universal Bot"

            if mode == "aud": 
                await client.send_audio(message.chat.id, final_path, caption=caption, thumb=thumb_path, progress=upload_progress)
            elif mode == "doc":
                await client.send_document(message.chat.id, final_path, caption=caption, thumb=thumb_path, force_document=True, progress=upload_progress)
            else: 
                await client.send_video(message.chat.id, final_path, caption=caption, thumb=thumb_path, supports_streaming=True, progress=upload_progress)
            
            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: logger.error(e); await message.edit(f"❌ **Error:** `{str(e)[:150]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None)

@app.on_message(filters.command("start"))
async def start(c, m): 
    await m.reply("👋 **Final Fixed Bot!**\n\n✅ Regex Stream Extractor: ON\n✅ Referer Mirroring: ON\n✅ Force HLS Download: ON")

print("🔥 Bot Started (Manual Extraction Mode)...")
app.run()
