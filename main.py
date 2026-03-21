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
from urllib.parse import urljoin
from aiohttp import web

# ==========================================
# ⚙️ ১. অটো ডিপেন্ডেন্সি ইন্সটলার
# ==========================================
def install_requirements():
    pkgs = ["pyrogram", "tgcrypto", "yt_dlp", "requests", "aiohttp", "cloudscraper", "imageio_ffmpeg"]
    for pkg in pkgs:
        try:
            importlib.import_module(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

install_requirements()

import requests
import yt_dlp
import cloudscraper
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait

# ==========================================
# 🛠 ২. মেটা ডেটা ও পাথ সেটআপ
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8464633052:AAEaO33QeUy14LM7yNVSUvbH6uxtYkwvE7k")
API_ID = int(os.environ.get("API_ID", 28870226))
API_HASH = os.environ.get("API_HASH", "a5b1ff3f75941649bf5bc159782f0f00")
PORT = int(os.environ.get("PORT", 8080))

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltraDownloader")

# Aria2c Static Path
ARIA2_PATH = os.path.join(os.getcwd(), "aria2c")

def setup_aria2():
    if os.path.exists(ARIA2_PATH): return ARIA2_PATH
    try:
        url = "https://github.com/q3aql/aria2-static-builds/releases/download/v1.36.0/aria2-1.36.0-linux-gnu-64bit-build1.tar.bz2"
        r = requests.get(url)
        with open("aria.tar.bz2", "wb") as f: f.write(r.content)
        with tarfile.open("aria.tar.bz2", "r:bz2") as tar:
            for m in tar.getmembers():
                if m.name.endswith("aria2c"):
                    m.name = "aria2c"
                    tar.extract(m, path=os.getcwd())
                    break
        os.chmod(ARIA2_PATH, 0o755)
        return ARIA2_PATH
    except: return None

ARIA2_EXE = setup_aria2()

# ==========================================
# 🕵️‍♂️ ৩. ডিপ স্ক্র্যাপার (Hidden Links)
# ==========================================
def get_hidden_video_link(url):
    scraper = cloudscraper.create_scraper()
    try:
        html = scraper.get(url, timeout=15).text
        patterns = [
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']'
        ]
        for p in patterns:
            match = re.search(p, html)
            if match: return match.group(1).replace('\\/', '/')
        return url
    except: return url

# ==========================================
# 📊 ৪. প্রগ্রেস ও ইউটিলিটি
# ==========================================
def hms(n):
    for unit in ['B','KB','MB','GB']:
        if n < 1024: return f"{n:.2f} {unit}"
        n /= 1024

async def update_status(current, total, msg, start_time, status_text):
    try:
        now = time.time()
        if round((now - start_time) % 4) == 0 or current == total:
            percentage = current * 100 / total
            speed = current / (now - start_time) if (now - start_time) > 0 else 0
            tmp = (f"**{status_text}**\n"
                   f"📊 `{percentage:.1f}%` | `{hms(current)}/{hms(total)}`\n"
                   f"🚀 Speed: `{hms(speed)}/s`")
            await msg.edit(tmp)
    except: pass

# ==========================================
# 🤖 ৫. বট হ্যান্ডলার
# ==========================================
app = Client("FinalBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
TASK_DATA = {}
USER_STATE = {}

@app.on_message(filters.command("start"))
async def start_handler(c, m):
    await m.reply("🔥 **বট প্রস্তুত!** যেকোনো লিঙ্ক দিন আমি ডাউনলোড করে দিচ্ছি।")

@app.on_message(filters.text & ~filters.command("start"))
async def link_handler(c, m):
    chat_id = m.chat.id
    url = m.text.strip()

    # Rename Logic
    if chat_id in USER_STATE:
        data = USER_STATE.pop(chat_id)
        msg = data['msg']
        task_id = data['task_id']
        TASK_DATA[task_id]['custom_name'] = re.sub(r'[\\/*?:"<>|]', '', url)
        await msg.edit(f"✅ নাম সেট হয়েছে: `{url}`\n📥 ডাউনলোড শুরু হচ্ছে...")
        asyncio.create_task(process_task(c, msg, task_id))
        return

    if not url.startswith("http"): return

    status_msg = await m.reply("🔎 **লিঙ্ক এনালাইজ করছি...**")
    task_id = str(uuid.uuid4())[:8]

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
            title = info.get('title', 'Video_File')
        
        real_url = await asyncio.to_thread(get_hidden_video_link, url)
        TASK_DATA[task_id] = {'url': real_url, 'title': title, 'custom_name': None}
        
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Download Video", callback_data=f"go_{task_id}")],
            [InlineKeyboardButton("📝 Rename & Download", callback_data=f"rename_{task_id}")]
        ])
        await status_msg.edit(f"📂 **ফাইল:** `{title}`\n\nকি করতে চান?", reply_markup=btn)
    except Exception as e:
        await status_msg.edit(f"❌ এরর: {str(e)[:100]}")

@app.on_callback_query(filters.regex("^go_|^rename_"))
async def cb_handler(c, q: CallbackQuery):
    action, task_id = q.data.split("_")
    if task_id not in TASK_DATA: return await q.answer("পুরানো টাস্ক!")

    if action == "rename":
        USER_STATE[q.message.chat.id] = {'task_id': task_id, 'msg': q.message}
        await q.message.edit("📝 **নতুন নামটি লিখে পাঠান:**")
    else:
        await q.message.edit("📥 **ডাউনলোড শুরু হচ্ছে...**")
        asyncio.create_task(process_task(c, q.message, task_id))

# ==========================================
# 🚀 ৬. কোর প্রসেসর (Download & Upload)
# ==========================================
async def process_task(client, message, task_id):
    data = TASK_DATA.get(task_id)
    path = os.path.join(DOWNLOAD_DIR, task_id)
    os.makedirs(path, exist_ok=True)
    
    file_name = data['custom_name'] if data['custom_name'] else data['title']
    start_time = time.time()

    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            current = d.get('downloaded_bytes', 0)
            if total > 0:
                asyncio.run_coroutine_threadsafe(
                    update_status(current, total, message, start_time, "⬇️ Downloading"),
                    asyncio.get_event_loop()
                )

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f"{path}/{file_name}.%(ext)s",
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
    }
    if ARIA2_EXE:
        ydl_opts.update({'external_downloader': ARIA2_EXE, 'external_downloader_args': ['-x', '16', '-k', '1M']})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.download, [data['url']])
        
        downloaded_file = os.path.join(path, os.listdir(path)[0])
        await message.edit("📤 **টেলিগ্রামে আপলোড হচ্ছে...**")
        
        await client.send_video(
            message.chat.id, 
            video=downloaded_file, 
            caption=f"✅ `{file_name}`",
            supports_streaming=True,
            progress=update_status,
            progress_args=(message, time.time(), "⬆️ Uploading")
        )
        await message.delete()
    except Exception as e:
        await message.edit(f"❌ এরর: {str(e)[:150]}")
    finally:
        shutil.rmtree(path, ignore_errors=True)
        TASK_DATA.pop(task_id, None)

# ==========================================
# 🌐 ৭. ওয়েব সার্ভার ও রানার
# ==========================================
async def web_handler(request): return web.Response(text="Bot is Active")

async def main():
    server = web.Application(); server.add_routes([web.get('/', web_handler)])
    runner = web.AppRunner(server); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await app.start(); await idle(); await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
