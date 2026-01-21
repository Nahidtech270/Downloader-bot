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
# কনফিগারেশন (আপনার তথ্যগুলো ঠিক আছে)
# ==========================================
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738
API_HASH = "297f51aaab99720a09e80273628c3c24"

DOWNLOAD_FOLDER = "downloads"
COOKIE_FILE = "cookies.txt" # কুকিজ সেভ করার ফাইল

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
# ২. শক্তিশালী লিংক ডিটেক্টর (আপনার আগের কোডটি ফেরত আনা হয়েছে)
# ==========================================
def get_target_url(url):
    # ডাইরেক্ট সাইট হলে সরাসরি লিংক ফেরত দেবে
    direct_sites = [
        "youtube.com", "youtu.be", 
        "facebook.com", "fb.watch", 
        "instagram.com", "tiktok.com", 
        "dailymotion.com", "vimeo.com",
        "twitter.com", "x.com"
    ]
    
    if any(site in url for site in direct_sites):
        return url

    # GilliTV বা ড্রামা সাইট হলে স্ক্র্যাপ করবে (আপনার আগের লজিক)
    logger.info(f"Scraping external site: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # iframe খোঁজা
            iframes = soup.find_all('iframe')
            for iframe in iframes:
                src = iframe.get('src')
                if src:
                    # পরিচিত ভিডিও প্লেয়ার পেলেই সেটা রিটার্ন করবে
                    if any(domain in src for domain in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru', 'vk.com']):
                        final_url = 'https:' + src if src.startswith('//') else src
                        logger.info(f"Found embedded video: {final_url}")
                        return final_url
    except Exception as e:
        logger.error(f"Scraping Error: {e}")
    
    return url # কিছু না পেলে যা লিংক ছিল তাই ফেরত দেবে

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

        try:
            await message.edit(
                f"{status_text}\n"
                f"{progress_str} **{round(percentage, 2)}%**\n"
                f"📦 **Size:** {human_readable_size(current)} / {human_readable_size(total)}\n"
                f"🚀 **Speed:** {human_readable_size(speed)}/s"
            )
        except:
            pass

# ==========================================
# ৪. মেইন ডাউনলোড প্রসেস
# ==========================================
async def download_worker(url, message, status_msg):
    target_url = await asyncio.to_thread(get_target_url, url)
    await status_msg.edit(f"✅ প্রসেসিং শুরু...\n⬇️ ডাউনলোড হচ্ছে...")

    timestamp = int(time.time())
    out_templ = f"{DOWNLOAD_FOLDER}/video_{timestamp}.%(ext)s"

    # yt-dlp সেটিংস
    ydl_opts = {
        'format': 'best[ext=mp4]/best', 
        'outtmpl': out_templ,
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0', 
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    # কুকিজ চেক করা (YouTube এর জন্য)
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE
    else:
        # কুকিজ না থাকলে সাধারণ চেষ্টা
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}

    try:
        def run_yt_dlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info), info

        file_path, info = await asyncio.to_thread(run_yt_dlp)
        
        # মেটাডাটা প্রসেসিং (ক্র্যাশ ফিক্স সহ)
        video_title = info.get('title', 'Downloaded Video')
        duration = int(info.get('duration', 0)) if info.get('duration') else 0
        width = int(info.get('width', 0)) if info.get('width') else 0
        height = int(info.get('height', 0)) if info.get('height') else 0
        
        if not os.path.exists(file_path):
             await status_msg.edit("❌ ডাউনলোড ফেইল হয়েছে (ফাইল পাওয়া যায়নি)।")
             return

        file_size = os.path.getsize(file_path)
        await status_msg.edit(f"⬇️ ডাউনলোড কমপ্লিট!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ আপলোড হচ্ছে...")

        start_time = time.time()
        
        # থাম্বনেইল হ্যান্ডলিং
        thumb_path = None
        possible_thumb = file_path.rsplit('.', 1)[0] + ".jpg"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb

        # আপলোড
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
        if os.path.exists(file_path): os.remove(file_path)
        if thumb_path: os.remove(thumb_path)

    except Exception as e:
        err = str(e)
        if "Sign in" in err or "429" in err:
            await status_msg.edit("❌ **YouTube এরর:** সার্ভার ব্লকড।\nঅনুগ্রহ করে আপনার `cookies.txt` ফাইলের লেখাগুলো কপি করে এখানে পেস্ট করুন।")
        else:
            await status_msg.edit(f"❌ এরর: `{err[:200]}...`")
        
        logger.error(f"Error: {e}")
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# ৫. মেসেজ এবং কুকিজ হ্যান্ডলার (All-in-One)
# ==========================================
@app.on_message(filters.text)
async def handle_message(client, message):
    text = message.text.strip()
    
    # ১. যদি কুকিজ টেক্সট হয় (Netscape Format)
    if text.startswith(("# Netscape", ".youtube.com", ".google.com")) or "TRUE" in text:
        with open(COOKIE_FILE, "w") as f:
            f.write(text)
        await message.reply("✅ **Cookies আপডেট করা হয়েছে!**\nএখন আপনি ইউটিউব থেকে ডাউনলোড করতে পারবেন।")
        return

    # ২. যদি লিংক হয়
    if text.startswith("http"):
        msg = await message.reply_text("🕵️‍♂️ লিংক চেক করা হচ্ছে...")
        asyncio.create_task(download_worker(text, message, msg))
        return
        
    if message.text == "/start":
        await message.reply("👋 হ্যালো! লিংক দিন (GilliTV, YouTube, FB, Insta)।\n\nইউটিউব সমস্যা হলে কুকিজ টেক্সট পেস্ট করুন।")
    else:
        await message.reply("❌ দয়া করে সঠিক লিংক দিন অথবা কুকিজ টেক্সট দিন।")

# ডকুমেন্ট হ্যান্ডলার (যদি ফাইল হিসেবে কুকিজ দেয়)
@app.on_message(filters.document)
async def handle_document(client, message):
    if message.document.file_name == "cookies.txt":
        await message.download(file_name=COOKIE_FILE)
        await message.reply("✅ **Cookies ফাইল সেট করা হয়েছে!**")

print("🤖 Universal Bot Started (Robust Mode)...")
app.run()
