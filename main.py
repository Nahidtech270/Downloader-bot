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
import requests
from urllib.parse import urljoin
from aiohttp import web

# ==========================================
# 🛠 ১. ডিপেন্ডেন্সি ও সিস্টেম চেক
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FinalBot")

# এই লাইব্রেরিগুলো requirements.txt এ থাকা ভালো, তবুও সেফটি চেক
required_packages = ["pyrogram", "tgcrypto", "yt-dlp", "cloudscraper", "imageio_ffmpeg", "fake_useragent"]
for pkg in required_packages:
    if importlib.util.find_spec(pkg.replace("-", "_")) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

import cloudscraper
import yt_dlp
from fake_useragent import UserAgent
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait

try:
    import imageio_ffmpeg
    FFMPEG_LOCATION = imageio_ffmpeg.get_ffmpeg_exe()
except:
    FFMPEG_LOCATION = "ffmpeg"

# ==========================================
# ⚙️ ২. কনফিগারেশন (Safe Load)
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464633052:AAEaO33QeUy14LM7yNVSUvbH6uxtYkwvE7k")
API_ID = int(os.environ.get("API_ID", 28870226))
API_HASH = os.environ.get("API_HASH", "a5b1ff3f75941649bf5bc159782f0f00")
PORT = int(os.environ.get("PORT", 8080))
DOWNLOAD_FOLDER = "downloads"

if not os.path.exists(DOWNLOAD_FOLDER): os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# 🛠 ৩. Aria2c সেটআপ (Safe Fix)
# ==========================================
ARIA2_BIN_PATH = os.path.join(os.getcwd(), "aria2c")

def install_aria2_static():
    try:
        if os.path.exists(ARIA2_BIN_PATH): return ARIA2_BIN_PATH
        aria_sys = shutil.which("aria2c")
        if aria_sys: return aria_sys

        print("🚀 Downloading Aria2c Engine...")
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
        r = requests.get(url, stream=True, timeout=20)
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
    except Exception as e:
        print(f"⚠️ Aria2 install failed: {e}")
        return None

ARIA2_EXECUTABLE = install_aria2_static()

# ==========================================
# 🕵️‍♂️ ৪. সুপার স্ক্র্যাপার (Hidden Link Logic)
# ==========================================
def get_real_video_link(page_url):
    headers = {'User-Agent': UserAgent().random, 'Referer': 'https://google.com/'}
    try:
        scraper = cloudscraper.create_scraper()
        html = scraper.get(page_url, headers=headers, timeout=20).text
        patterns = [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
            r'file:\s*["\']([^"\']+)["\']'
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                link = match.group(1).replace('\\/', '/')
                return link if link.startswith('http') else urljoin(page_url, link)
        return page_url
    except: return page_url

# ==========================================
# 📊 ৫. হেল্পার ফাংশন
# ==========================================
def human_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

async def update_progress(message, current, total, start_time, status_text, task_id):
    try:
        now = time.time()
        if round((now - start_time) % 4) == 0 or current == total:
            percentage = current * 100 / total
            speed = current / (now - start_time) if (now - start_time) > 0 else 0
            filled = int(percentage // 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            text = (f"**{status_text}**\n[{bar}] `{percentage:.1f}%`\n"
                    f"📦 `{human_size(current)} / {human_size(total)}` | 🚀 `{human_size(speed)}/s`")
            await message.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"stop_{task_id}")]]))
    except: pass

# ==========================================
# 🤖 ৬. বট ক্লায়েন্ট ও হ্যান্ডলার
# ==========================================
app = Client("final_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
TASK_STORE = {}; USER_STATE = {}; CANCEL_EVENTS = {}

@app.on_message(filters.command("start"))
async def start(c, m): await m.reply("🔥 **বট অনলাইন!** লিঙ্ক পাঠান।")

@app.on_message(filters.text & ~filters.command("start"))
async def handle_text(c, m):
    chat_id = m.chat.id
    if chat_id in USER_STATE:
        state = USER_STATE.pop(chat_id)
        task_id = state['task_id']
        TASK_STORE[task_id]['custom_name'] = re.sub(r'[\\/*?:"<>|]', '', m.text)
        await state['msg'].edit(f"✅ নাম সেট: `{m.text}`\n📥 ডাউনলোড শুরু...")
        asyncio.create_task(run_task(c, state['msg'], task_id))
        return

    if not m.text.startswith("http"): return
    msg = await m.reply("🔎 এনালাইজ করছি...")
    task_id = str(uuid.uuid4())[:8]
    
    try:
        real_url = await asyncio.to_thread(get_real_video_link, m.text)
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, m.text, download=False)
            title = info.get('title', 'video')
        
        TASK_STORE[task_id] = {'url': real_url, 'title': title, 'custom_name': None}
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Download", callback_data=f"dl_{task_id}"), InlineKeyboardButton("📝 Rename", callback_data=f"rn_{task_id}")]])
        await msg.edit(f"📂 **ফাইল:** `{title}`", reply_markup=btn)
    except Exception as e: await msg.edit(f"❌ এরর: {e}")

@app.on_callback_query(filters.regex("^dl_|^rn_|^stop_"))
async def cb_handler(c, q: CallbackQuery):
    if q.data.startswith("stop_"):
        CANCEL_EVENTS[q.data.split("_")[1]] = True
        return await q.answer("🛑 ক্যানসেল হচ্ছে...", show_alert=True)
    
    action, tid = q.data.split("_")
    if action == "rn":
        USER_STATE[q.message.chat.id] = {'task_id': tid, 'msg': q.message}
        await q.message.edit("📝 নতুন নাম লিখে পাঠান:")
    else:
        await q.message.edit("📥 কিউতে যোগ হচ্ছে...")
        asyncio.create_task(run_task(c, q.message, tid))

# ==========================================
# 🚀 ৭. কোর প্রসেসর
# ==========================================
async def run_task(c, msg, tid):
    data = TASK_STORE.get(tid); path = os.path.join(DOWNLOAD_FOLDER, tid)
    os.makedirs(path, exist_ok=True); CANCEL_EVENTS[tid] = False
    name = data['custom_name'] if data['custom_name'] else data['title']
    
    def hook(d):
        if CANCEL_EVENTS.get(tid): raise Exception("CANCELLED")
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            if total > 0:
                asyncio.run_coroutine_threadsafe(update_progress(msg, d['downloaded_bytes'], total, time.time(), "📥 ডাউনলোড হচ্ছে", tid), asyncio.get_event_loop())

    ydl_opts = {'format': 'best', 'outtmpl': f"{path}/{name}.%(ext)s", 'progress_hooks': [hook], 'ffmpeg_location': os.path.dirname(FFMPEG_LOCATION) if FFMPEG_LOCATION else None}
    if ARIA2_EXECUTABLE: ydl_opts.update({'external_downloader': ARIA2_EXECUTABLE, 'external_downloader_args': ['-x', '16', '-k', '1M']})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: await asyncio.to_thread(ydl.download, [data['url']])
        file = os.path.join(path, os.listdir(path)[0])
        await msg.edit("📤 আপলোড হচ্ছে...")
        await c.send_video(msg.chat.id, video=file, caption=f"`{name}`", supports_streaming=True, progress=update_progress, progress_args=(msg, time.time(), "📤 আপলোড হচ্ছে", tid))
        await msg.delete()
    except Exception as e: await msg.edit(f"❌ এরর: {e}")
    finally: shutil.rmtree(path, ignore_errors=True)

# ==========================================
# 🔥 ৮. ফাইনাল এক্সিকিউশন (Render Fixed)
# ==========================================
routes = web.RouteTableDef()
@routes.get("/", allow_head=True)
async def root_handler(request): return web.Response(text="Bot is Alive!")

async def main_process():
    try:
        web_app = web.Application(); web_app.add_routes(routes)
        runner = web.AppRunner(web_app); await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        print(f"✅ Web Server running on Port: {PORT}")
        await app.start(); print("✅ Bot Started"); await idle()
    except Exception as e: print(f"❌ FATAL: {e}")
    finally:
        await app.stop(); print("🛑 Bot Stopped")

if __name__ == "__main__":
    asyncio.run(main_process())
