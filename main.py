import os
import time
import math
import asyncio
import requests
import yt_dlp
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import Message

# ==========================================
# কনফিগারেশন (অবশ্যই পূরণ করবেন)
# ==========================================
BOT_TOKEN = "8437509974:AAFEVweRFb653-PlahAgAYUcFFAJY_OYcyc"
API_ID = 29462738  # আপনার API ID (সংখ্যা)
API_HASH = "297f51aaab99720a09e80273628c3c24" # আপনার API HASH (টেক্সট)

DOWNLOAD_FOLDER = "downloads"

# বট সেটআপ (Pyrogram)
app = Client(
    "my_video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ==========================================
# হেল্পার ১: ফরম্যাটেড সাইজ (MB/GB)
# ==========================================
def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f} PB"

# ==========================================
# হেল্পার ২: এমবেডেড ভিডিও খোঁজা (GilliTV ফিক্স)
# ==========================================
def find_embedded_video(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        if any(x in url for x in ["youtube.com", "youtu.be", "dailymotion.com"]):
            return url
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            iframes = soup.find_all('iframe')
            for iframe in iframes:
                src = iframe.get('src')
                if src and any(x in src for x in ['dailymotion', 'youtube', 'vidoza', 'streamtape', 'ok.ru']):
                    return 'https:' + src if src.startswith('//') else src
    except:
        pass
    return url

# ==========================================
# প্রোগ্রেস বার (আপলোডের সময় দেখাবে)
# ==========================================
async def progress(current, total, message, start_time, status_text):
    now = time.time()
    diff = now - start_time
    
    # প্রতি ৫ সেকেন্ডে একবার এডিট করবে
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        estimated_total_time = elapsed_time + time_to_completion

        # প্রোগ্রেস বার ডিজাইন
        progress_str = "[{0}{1}]".format(
            ''.join(["●" for i in range(math.floor(percentage / 10))]),
            ''.join(["○" for i in range(10 - math.floor(percentage / 10))])
        )

        tmp = (
            f"{status_text}\n"
            f"{progress_str} **{round(percentage, 2)}%**\n\n"
            f"📦 **Size:** {human_readable_size(current)} / {human_readable_size(total)}\n"
            f"🚀 **Speed:** {human_readable_size(speed)}/s\n"
            f"⏳ **ETA:** {time_to_completion // 1000}s"
        )
        try:
            await message.edit(tmp)
        except:
            pass

# ==========================================
# মেইন ডাউনলোড লজিক
# ==========================================
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 হ্যালো! আমি ২ জিবি পর্যন্ত ভিডিও ডাউনলোড করতে পারি।\nযেকোনো লিংক দিন।")

@app.on_message(filters.text)
async def handle_url(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.reply_text("❌ দয়া করে সঠিক http লিংক দিন।")
        return

    status_msg = await message.reply_text("🕵️‍♂️ লিংক চেক করা হচ্ছে...")
    
    # ১. লিংক প্রসেস করা
    target_url = find_embedded_video(url)
    await status_msg.edit(f"✅ ভিডিও পাওয়া গেছে!\n⬇️ সার্ভারে ডাউনলোড শুরু হচ্ছে...")

    # ২. ডাউনলোডের জন্য yt-dlp সেটআপ
    video_path = f"{DOWNLOAD_FOLDER}/video_{int(time.time())}.mp4"
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': video_path,
        'quiet': True,
        'writethumbnail': True,
    }

    try:
        # ডাউনলোড হচ্ছে... (সার্ভারে)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            video_title = info.get('title', 'Downloaded Video')
            duration = info.get('duration', 0)
            width = info.get('width', 0)
            height = info.get('height', 0)
            
            # আসল ভিডিও পাথ এবং থাম্বনেইল পাথ আপডেট
            if os.path.exists(video_path):
                final_path = video_path
            else:
                # yt-dlp নাম চেঞ্জ করলে সেটা ধরা
                final_path = ydl.prepare_filename(info)

            thumb_path = None
            possible_thumb = final_path.rsplit('.', 1)[0] + ".jpg"
            if os.path.exists(possible_thumb):
                thumb_path = possible_thumb
            
            # ফাইলের সাইজ দেখা
            file_size = os.path.getsize(final_path)
            await status_msg.edit(f"⬇️ ডাউনলোড সম্পন্ন!\n📦 সাইজ: {human_readable_size(file_size)}\n⬆️ এখন টেলিগ্রামে আপলোড হচ্ছে...")

            # ৩. টেলিগ্রামে আপলোড (Pyrogram দিয়ে - ২ জিবি সাপোর্ট)
            start_time = time.time()
            await app.send_video(
                chat_id=message.chat.id,
                video=final_path,
                caption=f"🎬 **{video_title}**\n\n✅ Downloaded via Bot",
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_path,
                supports_streaming=True,
                progress=progress,
                progress_args=(status_msg, start_time, "⬆️ **আপলোড হচ্ছে (Cloud)...**")
            )

            # কাজ শেষ হলে ক্লিনআপ
            await status_msg.delete()
            if os.path.exists(final_path): os.remove(final_path)
            if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
            
            await message.reply_text("✅ কাজ সম্পন্ন!")

    except Exception as e:
        await status_msg.edit(f"❌ এরর হয়েছে: {str(e)}")
        # এরর হলেও ফাইল ডিলিট করা
        if 'final_path' in locals() and os.path.exists(final_path):
            os.remove(final_path)

# বট রান করা
print("🤖 Pyrogram Bot Started...")
app.run()
