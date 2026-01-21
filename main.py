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
API_ID = 29462738
API_HASH = "297f51aaab99720a09e80273628c3c24"

DOWNLOAD_FOLDER = "downloads"

# লগিং
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# বট সেটআপ
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
# ১. সাইজ ফরম্যাটার
# ==========================================
def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f} PB"

# ==========================================
# ২. স্মার্ট লিংক ডিটেক্টর
# ==========================================
def get_target_url(url):
    direct_sites = [
        "youtube.com", "youtu.be", 
        "facebook.com", "fb.watch", 
        "instagram.com", "tiktok.com", 
        "dailymotion.com", "vimeo.com",
        "twitter.com", "x.com"
    ]
    
    if any(site in url for site in direct_sites):
        return url

    # GilliTV বা অন্যান্য সাইট স্ক্র্যাপ করা
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src and any(d in src for d in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
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
            f"📦 **Size:** {human_readable_size(current)} / {human_readable_size(total)}\n"
            f"🚀 **Speed:** {human_readable_size(speed)}/s"
        )
        try:
            await message.edit(tmp)
        except:
            pass

# ==========================================
# ৪. মেইন ডাউনলোড ওয়ার্কার
# ==========================================
async def download_worker(url, message, status_msg):
    target_url = await asyncio.to_thread(get_target_url, url)
    await status_msg.edit(f"✅ সোর্স পাওয়া গেছে!\n⬇️ ডাউনলোড হচ্ছে...")

    timestamp = int(time.time())
    out_templ = f"{DOWNLOAD_FOLDER}/video_{timestamp}.%(ext)s"

    # ---------------------------------------------------------
    # সবচেয়ে গুরুত্বপূর্ণ পরিবর্তন (FFmpeg ছাড়া ডাউনলোড)
    # ---------------------------------------------------------
    ydl_opts = {
        # 'bestvideo+bestaudio' বাদ দিয়ে 'best' দেওয়া হলো যাতে FFmpeg না লাগে
        'format': 'best[ext=mp4]/best', 
        'outtmpl': out_templ,
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
        # ইউটিউব ফিক্স (অ্যান্ড্রয়েড ক্লায়েন্ট সাজা)
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        # ফেইসবুক/ইনস্টাগ্রাম ইউজার এজেন্ট
        'user_agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36',
    }

    try:
        def run_yt_dlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info), info

        file_path, info = await asyncio.to_thread(run_yt_dlp)
        
        video_title = info.get('title', 'Downloaded Video')
        
        # Float to Int কনভার্শন (ক্র্যাশ ফিক্স)
        duration = int(info.get('duration', 0)) if info.get('duration') else 0
        width = int(info.get('width', 0)) if info.get('width') else 0
        height = int(info.get('height', 0)) if info.get('height') else 0
        
        if not os.path.exists(file_path):
             await status_msg.edit("❌ ডাউনলোড ফেইল হয়েছে।")
             return

        file_size = os.path.getsize(file_path)
        await status_msg.edit(f"⬇️ ডাউনলোড কমপ্লিট!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ আপলোড হচ্ছে...")

        start_time = time.time()
        
        thumb_path = None
        possible_thumb = file_path.rsplit('.', 1)[0] + ".jpg"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb

        await app.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{video_title}**\n\n✅ Downloaded by Bot",
            duration=duration,
            width=width,
            height=height,
            thumb=thumb_path,
            supports_streaming=True,
            progress=progress,
            progress_args=(status_msg, start_time, "⬆️ **আপলোড হচ্ছে...**")
        )

        await status_msg.delete()
        if os.path.exists(file_path): os.remove(file_path)
        if thumb_path: os.remove(thumb_path)

    except Exception as e:
        # এরর মেসেজ ক্লিন করা
        err = str(e)
        if "Sign in" in err:
            err = "YouTube কুকিজ বা সাইন-ইন চাচ্ছে (Server IP Blocked)।"
        elif "ffmpeg" in err:
            err = "FFmpeg সমস্যা (তবে এই কোডে এটি হওয়ার কথা না)।"
        
        await status_msg.edit(f"❌ এরর: `{err[:200]}...`")
        logger.error(f"Error: {e}")
        
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# ৫. হ্যান্ডলার
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 Universal Downloader!\nGilliTV, YouTube, FB, Insta লিংক দিন।")

@app.on_message(filters.text)
async def handle_url(client, message):
    url = message.text.strip()
    if not url.startswith("http"): return
    msg = await message.reply_text("🕵️‍♂️ প্রসেসিং...")
    asyncio.create_task(download_worker(url, message, msg))

print("🤖 Universal Bot Running...")
app.run()
