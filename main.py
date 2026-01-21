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
# কনফিগারেশন (আপনার টোকেনগুলো এখানে দিন)
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
# ২. স্মার্ট লিংক ডিটেক্টর (Universal Logic)
# ==========================================
def get_target_url(url):
    """
    এই ফাংশনটি চেক করবে লিংকটি ডাইরেক্ট সাইটের নাকি স্ক্র্যাপ করতে হবে।
    """
    # ১. এই সাইটগুলো yt-dlp সরাসরি সাপোর্ট করে (কোনো স্ক্র্যাপিং দরকার নেই)
    direct_sites = [
        "youtube.com", "youtu.be", 
        "facebook.com", "fb.watch", 
        "instagram.com", 
        "tiktok.com", 
        "dailymotion.com", 
        "vimeo.com",
        "twitter.com", "x.com"
    ]
    
    if any(site in url for site in direct_sites):
        logger.info(f"Direct Site Detected: {url}")
        return url

    # ২. যদি উপরের সাইট না হয়, তবে GilliTV এর মতো পেজ থেকে ভিডিও খোঁজো
    logger.info(f"Scraping external site: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # iframe খোঁজা
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if src:
                # পরিচিত ভিডিও প্লেয়ার পেলেই সেটা রিটার্ন করবে
                if any(domain in src for domain in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                    return 'https:' + src if src.startswith('//') else src
    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    
    # ৩. কিছু না পেলে যা লিংক ছিল তাই ফেরত দেবে (yt-dlp চেষ্টা করবে)
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
# ৪. মেইন ডাউনলোড প্রসেস
# ==========================================
async def download_worker(url, message, status_msg):
    # লিংক ডিটেকশন
    target_url = await asyncio.to_thread(get_target_url, url)
    await status_msg.edit(f"✅ প্রসেসিং শুরু...\n🔗 সোর্স: {target_url}\n⬇️ ডাউনলোড হচ্ছে...")

    timestamp = int(time.time())
    out_templ = f"{DOWNLOAD_FOLDER}/video_{timestamp}.%(ext)s"

    # yt-dlp কনফিগারেশন (Facebook/Insta এর জন্য শক্তিশালী করা হয়েছে)
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best', # বেস্ট কোয়ালিটি মার্জ করবে
        'outtmpl': out_templ,
        'merge_output_format': 'mp4', # সব কিছু MP4 এ কনভার্ট করবে
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
        # ফেইসবুক/ইনস্টাগ্রাম ব্লক এড়াতে ব্রাউজারের পরিচয়
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    try:
        def run_yt_dlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info), info

        file_path, info = await asyncio.to_thread(run_yt_dlp)
        
        # Meta Data বের করা
        video_title = info.get('title', 'Downloaded Video')
        
        # --- আগের ফিক্স (Float to Int) ---
        duration = int(info.get('duration', 0)) if info.get('duration') else 0
        width = int(info.get('width', 0)) if info.get('width') else 0
        height = int(info.get('height', 0)) if info.get('height') else 0
        
        if not os.path.exists(file_path):
             await status_msg.edit("❌ ডাউনলোড ফেইল হয়েছে (ফাইল পাওয়া যায়নি)।")
             return

        file_size = os.path.getsize(file_path)
        await status_msg.edit(f"⬇️ ডাউনলোড সম্পন্ন!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ টেলিগ্রামে আপলোড হচ্ছে...")

        start_time = time.time()
        
        # থাম্বনেইল
        thumb_path = None
        possible_thumb = file_path.rsplit('.', 1)[0] + ".jpg"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb

        # ভিডিও পাঠানো
        await app.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{video_title}**\n\n💾 Size: {human_readable_size(file_size)}\n✅ Downloaded by Bot",
            duration=duration,
            width=width,
            height=height,
            thumb=thumb_path,
            supports_streaming=True,
            progress=progress,
            progress_args=(status_msg, start_time, "⬆️ **আপলোড হচ্ছে (Cloud)...**")
        )

        await status_msg.delete()
        # ক্লিনআপ
        if os.path.exists(file_path): os.remove(file_path)
        if thumb_path: os.remove(thumb_path)

    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 200: error_msg = error_msg[:200] + "..."
        await status_msg.edit(f"❌ এরর: `{error_msg}`")
        logger.error(f"Error: {e}")
        # ক্লিনআপ
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# ৫. মেসেজ হ্যান্ডলার
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 হ্যালো! আমি এখন Universal Downloader।\n\nYouTube, Facebook, Instagram, TikTok বা GilliTV - যেকোনো লিংক দিন।")

@app.on_message(filters.text)
async def handle_url(client, message):
    url = message.text.strip()
    
    # সাধারণ ভ্যালিডেশন
    if not url.startswith(("http://", "https://")):
        await message.reply_text("❌ দয়া করে সঠিক লিংক দিন (http/https)।")
        return

    msg = await message.reply_text("🕵️‍♂️ লিংক চেক করছি...")
    asyncio.create_task(download_worker(url, message, msg))

# বট রান
print("🤖 Universal Bot Started...")
app.run()
