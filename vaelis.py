import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
from PIL import Image, ImageOps
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools
from collections import deque

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Embed Speed Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
# KARUTA_ID = 646937666251915264 # ID của Karuta Bot
KARUTA_ID = 646937666251915264 

# Cache chống spam (50 tin gần nhất)
processed_cache = deque(maxlen=50)

# Nếu chạy trên Windows thì mở dòng dưới, trên Hosting linux thì đóng lại
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def solve_ocr_fast(image_bytes):
    """
    ENGINE XỬ LÝ SIÊU TỐC (UPDATE: XẾP DỌC)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Chia 3 lá bài
        card_w = w_img / 3
        
        # Tọa độ cắt (Đã tinh chỉnh để lấy trúng phần số in đậm ở dưới)
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78 

        crops = []
        for i in range(3):
            # 1. CẮT VÙNG CHỨA SỐ
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), 
                int(h_img * ratio_top),                    
                int(card_x_start + (card_w * ratio_right)),
                int(h_img * ratio_bottom)                  
            )
            crop = img.crop(box)

            # 2. XỬ LÝ ẢNH (Bắt chước style ảnh bên phải của bạn)
            # Resize to lên để nét hơn
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)
            crop = crop.convert('L') # Chuyển xám
            
            # Threshold: Chữ màu vàng/trắng sẽ thành màu trắng hẳn, nền tối thành đen
            # Số 130 là ngưỡng, bạn có thể chỉnh lên xuống (100-150) tùy độ sáng ảnh
            crop = crop.point(lambda p: 255 if p > 130 else 0)
            
            # Đảo màu: Thành chữ ĐEN nền TRẮNG (Tesseract thích cái này nhất)
            crop = ImageOps.invert(crop)
            
            # Thêm viền trắng bao quanh để số không bị dính mép
            crop = ImageOps.expand(crop, border=20, fill='white')
            
            crops.append(crop)

        # 3. GỘP ẢNH THEO CHIỀU DỌC (Vertical Stack)
        # Gộp dọc giúp Tesseract hiểu đây là 3 dòng chữ riêng biệt
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 20 # +20 padding giữa các dòng
        
        final_img = Image.new('L', (w_c, total_h), color=255) # Nền trắng
        
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 10))
        final_img.paste(crops[2], (0, (h_c * 2) + 20))

        # Debug: Lưu ảnh ra xem nếu cần
        # final_img.save("debug_ocr.png")

        # 4. OCR
        # --psm 6: Assume a single uniform block of text. (Đọc nguyên khối văn bản)
        # whitelist: Chỉ lấy số và các ký tự phân cách
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-·."
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
        # 5. LỌC KẾT QUẢ
        # Tìm tất cả các cụm số. Ví dụ: "1234", "1234-5", "455 . 1"
        # Regex này bắt: Số + (dấu - hoặc . hoặc · tùy chọn) + Số tùy chọn
        matches = re.findall(r'\d+(?:[-·\.]\d+)?', text)
        
        results = []
        # Lấy 3 kết quả đầu tiên tìm được
        for i in range(3):
            if i < len(matches):
                # Làm sạch chuỗi kết quả (bỏ dấu chấm thừa nếu có)
                clean_num = matches[i].replace('·', '-').replace('.', '-')
                results.append(clean_num)
            else:
                results.append("???")
        
        return results

    except Exception as e:
        print(f"OCR Error: {e}")
        return []

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT OCR READY: {bot.user}')

@bot.event
async def on_message(message):
    # Chỉ nhận tin nhắn từ Karuta Bot hoặc chính mình để test
    if message.author.id != KARUTA_ID: return
    
    if not message.attachments: return
    
    if message.id in processed_cache: return
    processed_cache.append(message.id)

    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        # Tải ảnh Async
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # Chạy OCR trong luồng riêng để không chặn bot
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))

        if numbers:
            embed = discord.Embed(
                color=0x36393f, 
                timestamp=message.created_at
            )
            embed.set_footer(text="⚡ v2.0 Vertical Stack") 

            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num in ["???", "Err", "", []]:
                    description += f"▪️ {emojis[i]} | ⚠️ **Unknown**\n"
                else:
                    description += f"▪️ {emojis[i]} | **#{num}**\n"
            
            embed.description = description
            await message.reply(embed=embed, mention_author=False)

    except Exception as e:
        print(f"Message Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
