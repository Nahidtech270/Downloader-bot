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

# লগিং সেটআপ (টার্মিনালে এরর দেখার জন্য)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# বট সেটআপ
app = Client(
    "my_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
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
# ২. উন্নত এমবেডেড ভিডিও খোঁজা (GilliTV Fix)
# ==========================================
def find_embedded_video(url):
    """
    GilliTV এবং এই ধরনের সাইট থেকে আসল ভিডিও লিংক বের করার উন্নত ফাংশন
    """
    # যদি আগে থেকেই ডাইরেক্ট লিংক হয়
    if any(x in url for x in ["youtube.com", "youtu.be", "dailymotion.com", "streamtape.com"]):
        return url
        
    logger.info(f"Scraping URL: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # পদ্ধতি ১: iframe খোঁজা
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src:
                # পরিচিত প্লেয়ার লিস্ট
                if any(domain in src for domain in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                    final_url = 'https:' + src if src.startswith('//') else src
                    logger.info(f"Found Iframe: {final_url}")
                    return final_url

    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    
    return url # কিছু না পেলে যা আছে তাই ফেরত দেবে

# ==========================================
# ৩. প্রোগ্রেস বার (টেলিগ্রামের জন্য)
# ==========================================
async def progress(current, total, message, start_time, status_text):
    now = time.time()
    diff = now - start_time
    
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
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
# ৪. ডাউনলোড এবং প্রসেসিং (Async Wrapper)
# ==========================================
async def download_worker(url, message, status_msg):
    target_url = await asyncio.to_thread(find_embedded_video, url)
    
    await status_msg.edit(f"✅ সোর্স: {target_url}\n⬇️ ডাউনলোড শুরু হচ্ছে... (অপেক্ষা করুন)")

    # ফাইলের নাম সেট করা
    timestamp = int(time.time())
    out_templ = f"{DOWNLOAD_FOLDER}/video_{timestamp}.%(ext)s"

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': out_templ,
        'quiet': False, # লগ দেখার জন্য False করা হলো
        'no_warnings': False,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
    }

    try:
        # ব্লকিং ফাংশন থ্রেডে চালানো
        def run_yt_dlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info), info

        file_path, info = await asyncio.to_thread(run_yt_dlp)
        
        video_title = info.get('title', 'Video')
        duration = info.get('duration', 0)
        
        # ফাইল আছে কিনা চেক
        if not os.path.exists(file_path):
             await status_msg.edit("❌ ডাউনলোড শেষ হয়েছে কিন্তু ফাইল পাওয়া যাচ্ছে না।")
             return

        file_size = os.path.getsize(file_path)
        await status_msg.edit(f"⬇️ ডাউনলোড সম্পন্ন!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ আপলোড হচ্ছে...")

        # আপলোড
        start_time = time.time()
        await app.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{video_title}**\n💾 Size: {human_readable_size(file_size)}",
            duration=duration,
            supports_streaming=True,
            progress=progress,
            progress_args=(status_msg, start_time, "⬆️ **টেলিগ্রামে আপলোড হচ্ছে...**")
        )

        # ক্লিনআপ
        await status_msg.delete()
        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        error_text = str(e)
        # এরর মেসেজ ছোট করে দেখানো
        if len(error_text) > 200: error_text = error_text[:200] + "..."
        await status_msg.edit(f"❌ এরর হয়েছে:\n`{error_text}`")
        logger.error(f"Download Failed: {e}")

# ==========================================
# ৫. মেইন হ্যান্ডলার
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 হ্যালো! লিংক দিন, আমি ডাউনলোড করে দেব (2GB সাপোর্ট সহ)।")

@app.on_message(filters.text)
async def handle_url(client, message):
    url = message.text.strip()
    
    if not url.startswith("http"):
        return

    msg = await message.reply_text("🕵️‍♂️ প্রসেসিং শুরু হচ্ছে...")
    
    # ব্যাকগ্রাউন্ড টাস্ক হিসেবে শুরু করা
    asyncio.create_task(download_worker(url, message, msg))

# বট রান
print("🤖 Bot Started with Verbose Logs...")
app.run()
