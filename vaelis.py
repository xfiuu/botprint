import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta Embed Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def clean_ocr_result(text):
    """Làm sạch kết quả OCR: thay dấu chấm thành gạch ngang, lọc rác"""
    if not text: return "???"
    # Thay các ký tự lạ thường gặp ở Karuta thành gạch ngang
    text = text.replace('·', '-').replace('.', '-').replace(',', '-')
    # Chỉ giữ lại số và gạch ngang
    clean = re.sub(r'[^\d-]', '', text)
    # Regex tìm dạng: số (VD: 123) hoặc số-số (VD: 123-4)
    matches = re.findall(r'\d+(?:-\d+)?', clean)
    if matches:
        # Lấy kết quả dài nhất (tránh lấy nhầm số 1 lẻ loi)
        return max(matches, key=len)
    return "???"

def process_single_crop(img, i, card_w, h_img):
    """Xử lý cắt và đọc 1 thẻ duy nhất"""
    # Tỷ lệ cắt chuẩn (đã test)
    ratio_top = 0.88
    ratio_bottom = 0.94
    ratio_left = 0.54
    ratio_right = 0.78 # Mở rộng sang phải chút

    card_x_start = int(i * card_w)
    box = (
        int(card_x_start + (card_w * ratio_left)), 
        int(h_img * ratio_top),                    
        int(card_x_start + (card_w * ratio_right)),
        int(h_img * ratio_bottom)                  
    )
    
    crop = img.crop(box)
    
    # --- XỬ LÝ ẢNH (PRE-PROCESSING) ---
    # 1. Upscale (BICUBIC nhanh hơn LANCZOS)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.BICUBIC)
    
    # 2. Grayscale & Contrast
    crop = crop.convert('L')
    enhancer = ImageEnhance.Contrast(crop)
    crop = enhancer.enhance(2.5) # Tăng tương phản mạnh
    
    # 3. Threshold (Quan trọng để tách chữ trắng nền tối)
    # Biến pixel tối -> đen (0), sáng -> trắng (255)
    crop = crop.point(lambda p: 0 if p < 130 else 255)
    
    # 4. Invert (Đảo màu) -> Vì Tesseract thích chữ Đen nền Trắng
    crop = ImageOps.invert(crop)
    
    # 5. Padding (Thêm viền trắng xung quanh để số không sát mép)
    crop = ImageOps.expand(crop, border=20, fill='white')

    # --- OCR ---
    # psm 7: Treat the image as a single text line.
    config = r"--psm 7 -c tessedit_char_whitelist=0123456789-."
    raw_text = pytesseract.image_to_string(crop, config=config)
    
    return clean_ocr_result(raw_text)

def process_image_full(image_bytes):
    """Hàm chạy trong Thread Pool"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        card_w = w_img / 3
        
        results = []
        # Xử lý tuần tự 3 thẻ (nhưng rất nhanh vì đã bỏ bớt bước thừa)
        for i in range(3):
            res = process_single_crop(img, i, card_w, h_img)
            results.append(res)
            
        return results
    except Exception as e:
        print(f"Lỗi xử lý ảnh: {e}")
        return ["Err", "Err", "Err"]

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot Embed Mode Online: {bot.user}')

@bot.event
async def on_message(message):
    if message.author.id != KARUTA_ID or not message.attachments: return
    att = message.attachments[0]
    if not att.content_type or "image" not in att.content_type: return

    try:
        # Tải ảnh bất đồng bộ
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # Đẩy xử lý ảnh sang luồng khác để không lag bot
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(process_image_full, image_bytes))

        if numbers:
            # --- TẠO EMBED ---
            embed = discord.Embed(color=0x2b2d31) # Màu xám tối giống Discord
            
            description_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num in ["???", "Err", ""]:
                    line = f"▪️ {emojis[i]} | ⚠️ **Can't read**"
                else:
                    line = f"▪️ {emojis[i]} | **#{num}**"
                description_lines.append(line)

            # Nối các dòng lại với nhau
            embed.description = "\n".join(description_lines)
            
            # Gửi embed (reply không ping)
            await message.reply(embed=embed, mention_author=False)
            print(f"✅ Đã gửi: {numbers}")

    except Exception as e:
        print(f"❌ Lỗi Bot: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
