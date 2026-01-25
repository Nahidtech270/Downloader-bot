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
# 🛠 ১. সিস্টেম চেকিং ও ডিপেন্ডেন্সি ইনস্টলেশন (সম্পূর্ণ)
# ==========================================
print("⚙️ System Initializing: Checking Dependencies...")

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing required package: {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except Exception as e:
            print(f"❌ Failed to install {package}: {e}")

# প্রয়োজনীয় সব লাইব্রেরি
required_packages = [
    "pyrogram", "tgcrypto", "yt_dlp", "requests", 
    "bs4", "imageio_ffmpeg", "aiohttp", "fake_useragent", "cloudscraper"
]

for pkg in required_packages:
    install_and_import(pkg)

# ইম্পোর্ট সেকশন
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
# 🛠 ২. Aria2c অটোমেটিক সেটআপ (Full Code)
# ==========================================
ARIA2_BIN_PATH = os.path.join(os.getcwd(), "aria2c")

def install_aria2_static():
    if os.path.exists(ARIA2_BIN_PATH): 
        return ARIA2_BIN_PATH
    
    # সিস্টেমে আছে কিনা চেক
    aria_sys = shutil.which("aria2c")
    if aria_sys: 
        return aria_sys
    
    print("🚀 Downloading Aria2c High-Speed Engine...")
    try:
        # স্ট্যাটিক বাইনারি ডাউনলোড (Linux 64bit)
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
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
        
        # পারমিশন ফিক্স
        os.chmod(ARIA2_BIN_PATH, 0o755)
        if os.path.exists(tar_name): os.remove(tar_name)
        print("✅ Aria2c Engine Installed Successfully.")
        return ARIA2_BIN_PATH
    except Exception as e:
        print(f"⚠️ Aria2c Installation Failed (Using Native Mode): {e}")
        return None

ARIA2_EXECUTABLE = install_aria2_static()

# ==========================================
# ⚙️ ৩. বট কনফিগারেশন
# ==========================================
BOT_TOKEN = "7849157640:AAFyGM8F-Yk7tqH2A_vOfVGqMx6bXPq-pTI"
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt"

app = Client(
    "universal_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN, 
    in_memory=True, 
    workers=20, 
    max_concurrent_transmissions=10
)

# গ্লোবাল ভেরিয়েবলস
MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UniversalBot")

if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 ৪. ইউটিলিটি ফাংশন (Progress & Formatting)
# ==========================================
def human_readable_size(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def clean_filename(name):
    # ফাইলের নাম ক্লিন করা যাতে OS এরর না দেয়
    clean = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    return clean[:200] 

async def update_progress(message, percentage, current, total, speed, status_text):
    # প্রোগ্রেস বার আপডেটার (অ্যানিমেশন সহ)
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
# 🕵️‍♂️ ৫. অ্যাডভান্সড লিংক ডিটেক্টর (Cloudscraper + Headers)
# ==========================================
def resolve_url_info(url):
    """
    এই ফাংশনটি ইউজার এর লিংক চেক করে দেখবে সেটা কি:
    ১. সাধারণ ভিডিও লিংক (Youtube/FB)
    ২. ডাইরেক্ট ফাইল লিংক (.mp4/.mkv)
    ৩. প্রটেক্টেড স্ট্রিমিং লিংক (Cloudflare)
    """
    print(f"🕵️‍♂️ Analyzing: {url}")
    
    # ১. সাধারণ ডাইরেক্ট ফাইল চেক
    if url.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv')):
        return {
            'type': 'direct',
            'url': url,
            'title': 'Direct_Video_File',
            'cookies': None,
            'ua': UserAgent().chrome
        }

    # ২. Cloudflare বাইপাস এবং কুকি সংগ্রহ
    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        # হেড রিকোয়েস্ট দিয়ে চেক
        try:
            head = scraper.head(url, timeout=10)
            if 'video' in head.headers.get('Content-Type', ''):
                return {
                    'type': 'direct',
                    'url': url,
                    'title': 'Direct_Stream_File',
                    'cookies': scraper.cookies.get_dict(),
                    'ua': scraper.headers['User-Agent']
                }
        except: pass

        # ৩. পেজ সোর্স থেকে m3u8 বা mp4 খোঁজা
        response = scraper.get(url, timeout=15)
        html = response.text
        
        # Regex প্যাটার্ন (লুকানো ভিডিও বের করার জন্য)
        patterns = [
            r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'src:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'(https?://[^"\s]+\.m3u8[^"\s]*)',
            r'file:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']'
        ]
        
        found_stream = url # ডিফল্ট
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                found_stream = match.group(1).replace('\\/', '/')
                print(f"✅ Found Hidden Stream: {found_stream}")
                break
        
        return {
            'type': 'stream',
            'url': found_stream,
            'referer': url, # অরিজিনাল ইউআরএল হবে রেফারার
            'cookies': scraper.cookies.get_dict(),
            'ua': scraper.headers['User-Agent']
        }

    except Exception as e:
        print(f"⚠️ Resolve Error: {e}")
        # ফেইল করলে ডিফল্ট হিসেবে ফেরত দেব
        return {
            'type': 'general',
            'url': url,
            'cookies': None,
            'ua': UserAgent().chrome
        }

# ==========================================
# 🤖 ৬. বট হ্যান্ডলার (মেসেজ রিসিভ এবং প্রসেসিং)
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    # রিনেম মোড হ্যান্ডলিং
    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Adding to Queue...**")
        del USER_STATE[chat_id]
        
        task_info = TASK_STORE[task_id]
        # মেইন ডাউনলোডার কল করা হচ্ছে
        asyncio.create_task(process_download(client, msg_to_edit, task_info, task_id, custom_name))
        return

    if not text.startswith("http"):
        await message.reply("❌ **Invalid Link!** Please send a valid URL.")
        return

    status_msg = await message.reply("🕵️‍♂️ **Processing Link (Universal Mode)...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        # লিংক এনালাইসিস
        link_data = await asyncio.to_thread(resolve_url_info, text)
        
        # মেটাডাটা বের করার চেষ্টা (টাইটেল এর জন্য)
        title = "Video_File"
        formats = []
        is_direct = (link_data['type'] == 'direct')
        
        if not is_direct:
            try:
                ydl_opts = {
                    'quiet': True, 'no_warnings': True,
                    'http_headers': {'User-Agent': link_data['ua']}
                }
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(link_data['url'], download=False))
                title = info.get('title', title)
                formats = info.get('formats', [])
            except:
                title = f"File_{task_id}"

        # টাস্ক স্টোর করা
        TASK_STORE[task_id] = {
            "meta": link_data,
            "title": title
        }

        # বাটন জেনারেট
        buttons = []
        
        # কোয়ালিটি বাটন (যদি পাওয়া যায়)
        if formats:
            resolutions = sorted(list(set([f.get('height') for f in formats if f.get('height')])), reverse=True)
            if resolutions:
                row = []
                for res in resolutions[:5]:
                    row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"q_{task_id}_vid_{res}"))
                    if len(row) == 3: buttons.append(row); row = []
                if row: buttons.append(row)

        # কন্ট্রোল বাটন
        ctrl_buttons = [
            [InlineKeyboardButton("🎬 Best Video (Auto)", callback_data=f"q_{task_id}_vid_best")],
            [InlineKeyboardButton("📁 Document (Safe Mode)", callback_data=f"q_{task_id}_doc_best")],
            [InlineKeyboardButton("🎵 Audio Only", callback_data=f"q_{task_id}_aud_0")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close")]
        ]
        for btn in ctrl_buttons: buttons.append(btn)

        await status_msg.edit(
            f"📂 **Found:** `{title[:60]}`\n"
            f"🔗 **Type:** `{link_data['type'].upper()}`\n"
            f"🛡️ **Status:** Ready to Download", 
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
        
        TASK_STORE[task_id]['mode'] = mode
        TASK_STORE[task_id]['res'] = res
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
        
        await query.message.edit(f"♻️ **Initializing Engines...**")
        asyncio.create_task(process_download(client, query.message, TASK_STORE[task_id], task_id, None))

# ==========================================
# 🚀 ৭. ট্রিপল ইঞ্জিন ডাউনলোডার (The Core Logic)
# ==========================================
async def direct_download_engine(url, headers, file_path, message, task_id):
    """
    Engine C: Pure Python Downloader (aiohttp)
    Direct link এর জন্য সবচেয়ে শক্তিশালী এবং ফাস্ট।
    """
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(url, timeout=30) as response:
                if response.status not in [200, 206]:
                    raise Exception(f"HTTP Error {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()

                with open(file_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024 * 1024): # 1MB Chunks
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
            return True
        except Exception as e:
            print(f"Direct DL Error: {e}")
            return False

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
        
        client.loop.create_task(update_progress(message, percentage, current, total, speed, "⬇️ Engine Downloading..."))

async def process_download(client, message, task_info, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        CANCEL_EVENTS[task_id] = False
        
        meta = task_info['meta']
        url = meta['url']
        cookies = meta.get('cookies')
        ua = meta.get('ua')
        
        mode = task_info['mode']
        res = task_info.get('res', 'best')
        
        file_name = clean_filename(custom_name if custom_name else task_info.get('title', 'video'))
        final_path = ""
        thumb_path = None
        duration = 0
        
        # হেডারস সেটআপ
        req_headers = {
            'User-Agent': ua if ua else UserAgent().chrome,
            'Referer': meta.get('referer', 'https://google.com/')
        }

        try:
            # ----------------------------------------------------
            # 🔄 METHOD 1: YT-DLP (Native or Aria2)
            # ----------------------------------------------------
            success = False
            
            # কুকি ফাইল তৈরি (যদি থাকে)
            cookie_path = None
            if cookies:
                cookie_path = f"{temp_dir}/cookies.txt"
                with open(cookie_path, 'w') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for k, v in cookies.items():
                        f.write(f".example.com\tTRUE\t/\tFALSE\t2600000000\t{k}\t{v}\n")

            out_templ = f"{temp_dir}/{file_name}.%(ext)s"
            
            ydl_opts = {
                'outtmpl': out_templ,
                'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                'http_headers': req_headers,
                'cookiefile': cookie_path,
                'progress_hooks': [lambda d: yt_dlp_hook(d, message, client, task_id)],
                'socket_timeout': 30,
                'retries': 10,
            }

            # ইঞ্জিন সিলেকশন লজিক
            # যদি m3u8 বা জটিল লিংক হয় -> Native HLS ব্যবহার করব (Aria2 বাদ)
            if "m3u8" in url or "player" in url or meta['type'] == 'stream':
                await message.edit("🚀 **Downloading via Native Engine (HLS)...**")
                ydl_opts['hls_prefer_native'] = True
                ydl_opts['hls_use_mpegts'] = True
                ydl_opts['external_downloader'] = None # Aria2 Disabled
            else:
                # সাধারণ লিংকের জন্য Aria2 (সুপারফাস্ট)
                await message.edit("🚀 **Downloading via High-Speed Engine (Aria2)...**")
                ydl_opts['external_downloader'] = ARIA2_EXECUTABLE
                ydl_opts['external_downloader_args'] = ['-x', '16', '-k', '1M', '-s', '16']

            # ফরম্যাট সেটআপ
            if mode == "aud":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
            elif mode == "doc":
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['keepvideo'] = True
            else: # Video
                if res == "best": ydl_opts['format'] = "bestvideo+bestaudio/best"
                else: ydl_opts['format'] = f"bestvideo[height<={res}]+bestaudio/best"
                ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

            # ডাউনলোড চেষ্টা ১
            try:
                info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
                success = True
                duration = int(info.get('duration', 0))
            except Exception as e:
                print(f"Method 1 Failed: {e}")
                success = False

            # ফাইল খোঁজা
            for f in os.listdir(temp_dir):
                if f.endswith((".mp4", ".mkv", ".mp3", ".webm", ".ts", ".avi")):
                    final_path = os.path.join(temp_dir, f)
                    break
            
            # ভ্যালিডেশন: ফাইল যদি খুব ছোট হয় (যেমন ১০০ KB এর কম), তার মানে করাপ্ট বা ব্লকড
            if success and os.path.exists(final_path):
                if os.path.getsize(final_path) < 100 * 1024: # 100KB check
                    print("⚠️ File too small, triggering fallback...")
                    os.remove(final_path)
                    success = False

            # ----------------------------------------------------
            # 🔄 METHOD 2: Direct Fallback (aiohttp)
            # ----------------------------------------------------
            if not success:
                await message.edit("⚠️ **Method 1 Failed. Trying Direct Fallback...**")
                final_path = f"{temp_dir}/{file_name}.mp4" # ডিফল্ট এক্সটেনশন
                success = await direct_download_engine(url, req_headers, final_path, message, task_id)
            
            # ----------------------------------------------------
            # ✅ FINAL CHECK & UPLOAD
            # ----------------------------------------------------
            if not success or not os.path.exists(final_path):
                raise Exception("All download methods failed. Link might be expired or strictly DRM protected.")

            file_size = os.path.getsize(final_path)
            if file_size > 2 * 1024 * 1024 * 1024: # 2GB Check
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            thumb_path = f"{temp_dir}/{file_name}.jpg"
            if not os.path.exists(thumb_path): thumb_path = None

            # আপলোড স্টার্ট
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
            caption = f"📁 **{file_name}**\n💾 Size: {human_readable_size(file_size)}\n🤖 Powered by Universal Bot"

            if mode == "aud": 
                await client.send_audio(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, progress=upload_progress)
            elif mode == "doc":
                await client.send_document(message.chat.id, final_path, caption=caption, thumb=thumb_path, force_document=True, progress=upload_progress)
            else: 
                await client.send_video(message.chat.id, final_path, caption=caption, thumb=thumb_path, duration=duration, supports_streaming=True, progress=upload_progress)

            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: logger.error(e); await message.edit(f"❌ **Error:** `{str(e)[:200]}`")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None)

@app.on_message(filters.command("start"))
async def start(c, m): 
    await m.reply("👋 **Universal Downloader Ready!**\n\n✅ Supports Direct Links\n✅ Supports HLS/m3u8\n✅ Supports Cloudflare Links\n✅ Auto-Fallback System\n\n**Just send any link!**")

print("🔥 Bot Started (Final Enterprise Version)...")
app.run()
