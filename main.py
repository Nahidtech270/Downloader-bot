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
from datetime import datetime

# ==========================================
# 🛠 স্মার্ট ডিপেন্ডেন্সি চেকার
# ==========================================
def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        print(f"🔄 Installing missing package: {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

required_packages = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "bs4", "imageio_ffmpeg", "aiohttp"]
for pkg in required_packages:
    install_and_import(pkg)

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
    'Referer': 'https://google.com/'
}

try:
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"✅ FFmpeg found at: {FFMPEG_LOCATION}")
except Exception:
    FFMPEG_LOCATION = "ffmpeg"

MAX_CONCURRENT_DOWNLOADS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

TASK_STORE = {} 
USER_STATE = {}
CANCEL_EVENTS = {} 
LAST_UPDATE_TIME = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltimateBot")

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
# 🛠 FFmpeg কনভার্টার (ভিডিও ফিক্স করার জন্য)
# ==========================================
async def convert_to_mp4(input_path, output_path):
    cmd = [
        FFMPEG_LOCATION, '-i', input_path,
        '-c:v', 'copy', '-c:a', 'copy', # ফাস্ট কপি (এনকোডিং ছাড়াই)
        '-movflags', '+faststart', # স্ট্রিমিং সাপোর্টের জন্য
        output_path, '-y'
    ]
    # যদি কপি না কাজ করে, তবে রি-এনকোড করবে (সেফটি)
    process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    await process.communicate()
    
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return True
    return False

# ==========================================
# 💾 ডাইরেক্ট ডাউনলোড হেল্পার (আপডেটেড)
# ==========================================
async def direct_download(url, file_path, message, task_id):
    # m3u8 বা স্ট্রিম লিংক হলে FFmpeg দিয়ে ডাউনলোড করবে
    if ".m3u8" in url or "stream" in url:
        cmd = [
            FFMPEG_LOCATION, '-headers', f'User-Agent: {FAKE_HEADERS["User-Agent"]}',
            '-i', url, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', file_path, '-y'
        ]
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await process.communicate()
        return

    # সাধারণ ফাইল হলে aiohttp দিয়ে ডাউনলোড
    async with aiohttp.ClientSession(headers=FAKE_HEADERS) as session:
        async with session.get(url) as response:
            if response.status not in [200, 206]:
                raise Exception(f"Direct Download Failed: HTTP {response.status}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()

            with open(file_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(1024 * 1024): # 1MB chunks
                    if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # প্রোগ্রেস আপডেট
                        now = time.time()
                        last_update = LAST_UPDATE_TIME.get(task_id, 0)
                        if (now - last_update) >= 3:
                            LAST_UPDATE_TIME[task_id] = now
                            percentage = downloaded * 100 / total_size if total_size > 0 else 0
                            speed = downloaded / (now - start_time) if (now - start_time) > 0 else 0
                            
                            filled = int(percentage // 10)
                            bar = "▰" * filled + "▱" * (10 - filled)
                            text = (f"⬇️ **Direct Downloading...**\n[{bar}] **{percentage:.1f}%**\n"
                                    f"📦 `{human_readable_size(downloaded)}` | ⚡ `{human_readable_size(speed)}/s`")
                            try:
                                await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
                            except: pass

# ==========================================
# 🕵️‍♂️ স্ক্র্যাপার এবং ডিটেক্টর
# ==========================================
def get_target_url(url):
    direct_sites = ["youtube.com", "youtu.be", "facebook.com", "fb.watch", "instagram.com", "tiktok.com", "dailymotion.com", "vimeo.com", "twitter.com", "x.com"]
    if any(site in url for site in direct_sites): return url

    try:
        response = requests.get(url, headers=FAKE_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. HLS Stream (m3u8) খোঁজা
        if "m3u8" in response.text:
            m3u8_match = re.search(r'(https?://[^\s"]+\.m3u8)', response.text)
            if m3u8_match: return m3u8_match.group(1)

        # 2. Iframe খোঁজা
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src and any(d in src for d in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                return 'https:' + src if src.startswith('//') else src
                
        # 3. Video Tag
        video = soup.find('video')
        if video:
            if video.get('src'): return video.get('src')
            source = video.find('source')
            if source and source.get('src'): return source.get('src')

    except: pass
    return url

# ==========================================
# 📥 প্রোগ্রেস হুক (yt-dlp)
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
        
        if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")

        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        text = (f"⬇️ **Downloading...**\n[{bar}] **{percentage:.1f}%**\n"
                f"📦 `{human_readable_size(current)} / {human_readable_size(total)}`\n"
                f"⚡ `{human_readable_size(speed)}/s`")
        try:
            client.loop.create_task(message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])))
        except: pass

async def upload_progress_hook(current, total, message, start_time, task_id):
    if CANCEL_EVENTS.get(task_id): app.stop_transmission(); return
    now = time.time()
    if round((now - start_time) % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
        filled = int(percentage // 10)
        bar = "▰" * filled + "▱" * (10 - filled)
        text = (f"⬆️ **Uploading...**\n[{bar}] **{percentage:.1f}%**\n"
                f"📦 `{human_readable_size(current)} / {human_readable_size(total)}`\n"
                f"⚡ `{human_readable_size(speed)}/s`")
        try: await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
        except: pass

# ==========================================
# 📨 টেক্সট হ্যান্ডলার
# ==========================================
@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def text_handler(client, message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id in USER_STATE and USER_STATE[chat_id]['state'] == 'waiting_name':
        task_id = USER_STATE[chat_id]['task_id']
        custom_name = clean_filename(text)
        msg_to_edit = USER_STATE[chat_id]['msg']
        await msg_to_edit.edit(f"📝 **Name Set:** `{custom_name}`\n♻️ **Processing...**")
        del USER_STATE[chat_id]
        
        task_info = TASK_STORE[task_id]
        asyncio.create_task(run_download_upload(client, msg_to_edit, task_info['url'], task_info['mode'], task_info['res'], task_id, custom_name))
        return

    if not text.startswith(("http", "www")):
        await message.reply("❌ Invalid Link")
        return

    status_msg = await message.reply("🕵️‍♂️ **Analyzing Link...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        target_url = await asyncio.to_thread(get_target_url, text)
        is_direct = False
        info = {}

        ydl_opts = {
            'quiet': True, 'no_warnings': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'http_headers': FAKE_HEADERS,
        }

        try:
            info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
        except Exception as e:
            err_msg = str(e)
            if any(x in err_msg for x in ["Unsupported URL", "HTTP Error", "503", "Service Unavailable", "403", "Forbidden"]):
                logger.info(f"Switching to Direct Mode due to: {err_msg[:50]}")
                is_direct = True
                info = {'title': 'Universal_Video', 'formats': []}
            elif "ExtractorError" in err_msg:
                await status_msg.edit("🔧 **Updating System...**")
                await asyncio.to_thread(smart_update_ytdlp)
                try:
                    info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(target_url, download=False))
                except: is_direct = True; info = {'title': 'Universal_Video', 'formats': []}
            else:
                is_direct = True
                info = {'title': 'Universal_Video', 'formats': []}

        title = info.get('title', 'Video')
        formats = info.get('formats', [])
        
        buttons = []
        if not is_direct and formats:
            resolutions = set()
            for f in formats:
                if f.get('height') and f.get('vcodec') != 'none': resolutions.add(f['height'])
            
            if resolutions:
                sorted_res = sorted(list(resolutions), reverse=True)
                row = []
                for res in sorted_res:
                    row.append(InlineKeyboardButton(f"🎬 {res}p", callback_data=f"qual_{task_id}_video_{res}"))
                    if len(row) == 3: buttons.append(row); row = []
                if row: buttons.append(row)
            else:
                buttons.append([InlineKeyboardButton("🎬 Download Video", callback_data=f"qual_{task_id}_video_best")])
            buttons.append([InlineKeyboardButton("🎵 Extract Audio", callback_data=f"qual_{task_id}_audio_0")])
        else:
            buttons.append([InlineKeyboardButton("⬇️ Force Download (Video)", callback_data=f"qual_{task_id}_direct_best")])

        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="close")])

        TASK_STORE[task_id] = {"url": target_url, "title": title, "is_direct": is_direct}
        await status_msg.edit(f"📂 **Found:** `{title[:50]}`\n✨ **Select Option:**", reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)[:100]}`")

# ==========================================
# 🔘 কলব্যাক হ্যান্ডলার
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

    if data.startswith("qual_"):
        parts = data.split("_")
        task_id, mode, res = parts[1], parts[2], parts[3]
        if task_id not in TASK_STORE: await query.answer("⚠️ Expired!", show_alert=True); return
        
        TASK_STORE[task_id].update({'mode': mode, 'res': res})
        default_name = TASK_STORE[task_id]['title']
        
        USER_STATE[query.message.chat.id] = {'state': 'waiting_name', 'task_id': task_id, 'msg': query.message}
        await query.message.edit(
            f"📝 **File Name:**\n`{default_name}`\n\n👇 **Rename?**\n1. Send new name (Text)\n2. Click Default",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Use Default Name", callback_data=f"startdef_{task_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="close")]
            ])
        )

    if data.startswith("startdef_"):
        task_id = data.split("_")[1]
        if task_id not in TASK_STORE: await query.answer("⚠️ Expired!", show_alert=True); return
        if query.message.chat.id in USER_STATE: del USER_STATE[query.message.chat.id]
        
        info = TASK_STORE[task_id]
        await query.message.edit(f"♻️ **Processing...**")
        asyncio.create_task(run_download_upload(client, query.message, info['url'], info['mode'], info['res'], task_id, None))

# ==========================================
# 📥 মেইন ডাউনলোড প্রসেস
# ==========================================
async def run_download_upload(client, message, url, mode, res, task_id, custom_name):
    async with semaphore:
        temp_dir = f"{DOWNLOAD_FOLDER}/{task_id}"
        if not os.path.exists(temp_dir): os.makedirs(temp_dir)
        CANCEL_EVENTS[task_id] = False
        
        file_name = custom_name if custom_name else TASK_STORE[task_id].get('title', 'video')
        file_name = clean_filename(file_name)
        
        is_direct = TASK_STORE[task_id].get('is_direct', False) or mode == 'direct'
        
        # আমরা ফাইলটিকে প্রথমে 'downloaded_file' হিসেবে সেভ করব, তারপর কনভার্ট করব
        temp_path = f"{temp_dir}/downloaded_file"
        final_path = f"{temp_dir}/{file_name}.mp4"
        thumb_path = None
        duration = 0

        try:
            if is_direct:
                await message.edit(f"⬇️ **Direct Downloading...**\n`Trying to bypass blocks...`")
                await direct_download(url, temp_path, message, task_id)
                
                # 🔥 আপডেট: ফাইলটি কি প্লে করার যোগ্য? চেক করা ও ফিক্স করা
                await message.edit(f"🔧 **Processing Video...**\n`Making it playable...`")
                if not await convert_to_mp4(temp_path, final_path):
                    # কনভার্ট ফেইল হলে অরিজিনালটাই রিনেম করে দেব
                    os.rename(temp_path, final_path)
            
            else:
                # yt-dlp Logic
                await message.edit(f"⬇️ **Downloading (yt-dlp)...**")
                out_templ = f"{temp_dir}/{file_name}.%(ext)s"
                
                ydl_opts = {
                    'outtmpl': out_templ,
                    'quiet': True, 'nocheckcertificate': True, 'writethumbnail': True,
                    'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
                    'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION),
                    'http_headers': FAKE_HEADERS,
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

                def run_dl():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return ydl.prepare_filename(info), info
                
                downloaded_path, info = await asyncio.to_thread(run_dl)
                
                # পাথ ফিক্স করা
                if mode == "audio":
                    final_path = os.path.splitext(downloaded_path)[0] + ".mp3"
                else:
                    final_path = os.path.splitext(downloaded_path)[0] + ".mp4"
                
                if not os.path.exists(final_path): final_path = downloaded_path
                thumb_path = os.path.splitext(downloaded_path)[0] + ".jpg"
                if not os.path.exists(thumb_path): thumb_path = None
                duration = int(info.get('duration', 0))

            if CANCEL_EVENTS.get(task_id): raise Exception("CANCELLED_BY_USER")
            
            if os.path.getsize(final_path) > 2000 * 1024 * 1024:
                await message.edit("❌ **File > 2GB (Telegram Limit).**")
                return

            await message.edit(f"⬆️ **Uploading...**")
            start_time = time.time()
            
            caption = f"🎬 **{file_name}**\n✅ Downloaded by Bot"
            
            if mode == "audio": 
                await client.send_audio(
                    chat_id=message.chat.id,
                    audio=final_path,
                    caption=caption,
                    thumb=thumb_path,
                    duration=duration,
                    progress=upload_progress_hook,
                    progress_args=(message, start_time, task_id)
                )
            else: 
                await client.send_video(
                    chat_id=message.chat.id,
                    video=final_path,
                    caption=caption,
                    thumb=thumb_path,
                    duration=duration,
                    supports_streaming=True,
                    progress=upload_progress_hook,
                    progress_args=(message, start_time, task_id)
                )
            
            await message.delete()

        except Exception as e:
            if "CANCELLED" in str(e): await message.edit("⛔ **Cancelled!**")
            else: logger.error(e); await message.edit(f"❌ **Error:** `{str(e)[:100]}`")
        
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            TASK_STORE.pop(task_id, None); CANCEL_EVENTS.pop(task_id, None); LAST_UPDATE_TIME.pop(task_id, None)

@app.on_message(filters.document)
async def cookie(c, m): await m.download(file_name=COOKIE_FILE); await m.reply("✅ Cookies Updated")
@app.on_message(filters.command("start"))
async def start(c, m): await m.reply("👋 **Bot Ready!**\nSend Link -> Quality -> Rename -> Enjoy!")

print("🔥 Bot Started with Video Fixer...")
app.run()
