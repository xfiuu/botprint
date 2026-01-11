# main.py - Phiên bản SIÊU TỐC ĐỘ (Batch OCR & Async)
import discord
from discord.ext import commands
import os
import re
import aiohttp # Cần cài: pip install aiohttp
import io
from PIL import Image, ImageOps, ImageEnhance
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Speed Mode Running."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def process_image_fast(image_bytes):
    """
    Hàm xử lý ảnh chạy trong Thread riêng (CPU bound).
    Cắt 3 vùng -> Ghép thành 1 ảnh ngang -> OCR 1 lần duy nhất.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        card_w = w_img / 3
        
        # Tọa độ cắt (giữ nguyên config cũ của bạn vì nó đã chuẩn)
        ratio_top = 0.88
        ratio_bottom = 0.94   
        ratio_left = 0.54     
        ratio_right = 0.78 # Mở rộng sang phải chút để tránh mất số cuối

        # List chứa 3 ảnh con
        crops = []
        
        for i in range(3):
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), # Left
                int(h_img * ratio_top),                    # Top
                int(card_x_start + (card_w * ratio_right)),# Right
                int(h_img * ratio_bottom)                  # Bottom
            )
            crop = img.crop(box)
            crops.append(crop)

        # --- GỘP ẢNH (STITCHING) ---
        # Tạo 1 dải ảnh dài chứa cả 3 số, cách nhau bởi khoảng trắng
        # Upscale nhẹ (2x) bằng BICUBIC (Nhanh hơn LANCZOS)
        scale_factor = 2 
        w_crop, h_crop = crops[0].size
        w_crop, h_crop = w_crop * scale_factor, h_crop * scale_factor
        
        padding = 50 # Khoảng trắng giữa các số để Tesseract phân biệt
        total_width = (w_crop * 3) + (padding * 2)
        
        # Tạo ảnh nền trắng
        stitched_img = Image.new('L', (total_width, h_crop), color=255)
        
        for i, crop in enumerate(crops):
            # Resize nhanh
            crop = crop.resize((w_crop, h_crop), Image.Resampling.BICUBIC)
            # Xử lý màu: Grayscale -> Tăng tương phản -> Threshold
            crop = crop.convert('L')
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.0)
            # Threshold: Chữ thành đen, nền thành trắng (Inverted logic for clarity)
            # Ở đây ta giữ Chữ Đen trên nền Trắng
            crop = crop.point(lambda p: 0 if p > 130 else 255) 
            
            # Dán vào ảnh to
            x_paste = i * (w_crop + padding)
            stitched_img.paste(crop, (x_paste, 0))

        # --- OCR 1 LẦN DUY NHẤT ---
        # psm 6: Assume a single uniform block of text (đọc 1 hàng ngang)
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-"
        text = pytesseract.image_to_string(stitched_img, config=custom_config)
        
        # Tách chuỗi kết quả thành list số
        # Regex tìm các cụm số, bỏ qua khoảng trắng rác
        raw_numbers = re.findall(r'\d+(?:-\d+)?', text)
        
        # Đảm bảo luôn trả về 3 phần tử (nếu thiếu thì điền ???)
        final_results = []
        for i in range(3):
            if i < len(raw_numbers):
                final_results.append(raw_numbers[i])
            else:
                final_results.append("???")
                
        return final_results

    except Exception as e:
        print(f"Lỗi xử lý: {e}")
        return ["Err", "Err", "Err"]

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'⚡ Bot Siêu Tốc: {bot.user}')

@bot.event
async def on_message(message):
    if message.author.id != KARUTA_ID or not message.attachments: return
    # Kiểm tra nhanh content type mà không cần regex phức tạp
    att = message.attachments[0]
    if not att.content_type or "image" not in att.content_type: return

    # In log nhỏ để biết bot đang chạy
    print(f"⚡ Scan: {att.filename}")

    try:
        # 1. Tải ảnh ASYNC (Không chặn luồng)
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # 2. Đưa tác vụ xử lý ảnh nặng vào Thread Pool để không lag Bot
        # Đây là chìa khóa để bot phản hồi mượt mà
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(process_image_fast, image_bytes))

        # 3. Trả kết quả gọn nhẹ (Text only)
        if numbers:
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            # Format kết quả trên 1 dòng để gọn hoặc 3 dòng tùy thích
            res = " | ".join([f"{emojis[i]} **{num}**" for i, num in enumerate(numbers)])
            await message.reply(res, mention_author=False)

    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
