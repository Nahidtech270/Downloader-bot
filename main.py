import os
import time
import math
import asyncio
import requests
import yt_dlp
import logging
from bs4 import BeautifulSoup
from pyrogram import Client, filters

# ==========================================
# কনফিগারেশন
# ==========================================
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738  # আপনার API ID দিন
API_HASH = "297f51aaab99720a09e80273628c3c24" # আপনার API HASH দিন

DOWNLOAD_FOLDER = "downloads"

# লগিং কনফিগারেশন
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# বট সেটআপ (In-Memory সেশন সহ - Disk I/O Error সমাধানের জন্য)
app = Client(
    "my_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True  # <--- এটি সার্ভার ক্র্যাশ আটকাবে
)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# ১. সাইজ ফরম্যাটার
# ==========================================
def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f} PB"

# ==========================================
# ২. এমবেডেড ভিডিও খোঁজা (GilliTV Fix)
# ==========================================
def find_embedded_video(url):
    # যদি ডাইরেক্ট লিংক হয়
    if any(x in url for x in ["youtube.com", "youtu.be", "dailymotion.com", "streamtape.com"]):
        return url
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src:
                if any(domain in src for domain in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                    return 'https:' + src if src.startswith('//') else src
    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    
    return url

# ==========================================
# ৩. প্রোগ্রেস বার
# ==========================================
async def progress(current, total, message, start_time, status_text):
    now = time.time()
    diff = now - start_time
    
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        
        progress_str = "[{0}{1}]".format(
            ''.join(["●" for i in range(math.floor(percentage / 10))]),
            ''.join(["○" for i in range(10 - math.floor(percentage / 10))])
        )

        tmp = (
            f"{status_text}\n"
            f"{progress_str} **{round(percentage, 2)}%**\n\n"
            f"📦 **সাইজ:** {human_readable_size(current)} / {human_readable_size(total)}\n"
            f"🚀 **স্পিড:** {human_readable_size(speed)}/s"
        )
        try:
            await message.edit(tmp)
        except:
            pass

# ==========================================
# ৪. ডাউনলোড লজিক
# ==========================================
async def download_worker(url, message, status_msg):
    target_url = await asyncio.to_thread(find_embedded_video, url)
    await status_msg.edit(f"✅ সোর্স: {target_url}\n⬇️ ডাউনলোড শুরু হচ্ছে...")

    timestamp = int(time.time())
    out_templ = f"{DOWNLOAD_FOLDER}/video_{timestamp}.%(ext)s"

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': out_templ,
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
    }

    try:
        def run_yt_dlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info), info

        file_path, info = await asyncio.to_thread(run_yt_dlp)
        
        # ----------------------------------------------------
        # এই অংশটিই আপনার এরর ফিক্স করবে (Float to Int)
        # ----------------------------------------------------
        video_title = info.get('title', 'Video')
        duration = int(info.get('duration', 0)) # <--- float কে int করা হলো
        width = int(info.get('width', 0)) if info.get('width') else 0
        height = int(info.get('height', 0)) if info.get('height') else 0
        
        if not os.path.exists(file_path):
             await status_msg.edit("❌ ফাইল পাওয়া যাচ্ছে না।")
             return

        file_size = os.path.getsize(file_path)
        await status_msg.edit(f"⬇️ ডাউনলোড সম্পন্ন!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ আপলোড হচ্ছে...")

        start_time = time.time()
        
        # থাম্বনেইল হ্যান্ডলিং
        thumb_path = None
        possible_thumb = file_path.rsplit('.', 1)[0] + ".jpg"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb

        await app.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{video_title}**\n💾 Size: {human_readable_size(file_size)}",
            duration=duration,
            width=width,
            height=height,
            thumb=thumb_path,
            supports_streaming=True,
            progress=progress,
            progress_args=(status_msg, start_time, "⬆️ **টেলিগ্রামে আপলোড হচ্ছে...**")
        )

        await status_msg.delete()
        if os.path.exists(file_path): os.remove(file_path)
        if thumb_path: os.remove(thumb_path)

    except Exception as e:
        await status_msg.edit(f"❌ এরর: `{str(e)}`")
        logger.error(f"Error: {e}")
        # ক্লিনআপ
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# ৫. হ্যান্ডলার
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 হ্যালো! লিংক দিন।")

@app.on_message(filters.text)
async def handle_url(client, message):
    url = message.text.strip()
    if not url.startswith("http"): return
    msg = await message.reply_text("🕵️‍♂️ প্রসেসিং...")
    asyncio.create_task(download_worker(url, message, msg))

print("🤖 Bot Started...")
app.run()
