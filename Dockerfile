# পাইথনের অফিশিয়াল ইমেজ ব্যবহার করা হচ্ছে
FROM python:3.9-slim

# কাজের ফোল্ডার সেট করা
WORKDIR /app

# সিস্টেম আপডেট এবং FFmpeg ইন্সটল করা (ভিডিও প্রসেসিংয়ের জন্য এটি মাস্ট)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# requirements ফাইল কপি এবং ইন্সটল করা
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# বাকি সব ফাইল কপি করা
COPY . .

# বট রান করার কমান্ড
CMD ["python", "main.py"]
