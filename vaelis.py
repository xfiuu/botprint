# main.py - Phiên bản Hoàn Chỉnh: Đọc Print Number (Upscale + Khử nhiễu)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- PHẦN 1: CẤU HÌNH WEB SERVER (Giữ bot online trên Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Discord (OCR Print Number) đang hoạt động."

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- PHẦN 2: CẤU HÌNH BOT ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Nếu chạy trên Windows, bỏ comment dòng dưới và trỏ đúng đường dẫn
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def clean_print_number(text):
    """
    Làm sạch kết quả OCR:
    - Chỉ giữ lại số.
    - Cắt bỏ phần thừa sau các dấu chấm, gạch ngang (nếu có).
    """
    if not text:
        return "???"
    
    # Tách chuỗi tại các dấu phân cách thường gặp: . - ·
    parts = re.split(r'[.\-\u00B7]', text)
    first_part = parts[0]
    
    # Chỉ giữ lại số
    cleaned_number = re.sub(r'\D', '', first_part)
    
    return cleaned_number if cleaned_number else "???"

async def get_print_numbers_from_image(image_bytes):
    """
    Xử lý ảnh: Cắt góc dưới phải -> Phóng to -> Khử nhiễu -> Đọc số
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        
        # Bỏ qua nếu ảnh quá nhỏ (không phải ảnh drop 3 thẻ)
        if width < 830 or height < 300:
            return []

        # Thông số kỹ thuật của thẻ Karuta
        card_width = 278
        card_height = 248
        x_coords = [0, 279, 558] 
        y_offset = 32           

        # Tọa độ cắt vùng Print Number (tương đối trong 1 thẻ)
        # Left=100: Lấy rộng ra để bắt được số dài
        # Top=230: Vừa khít dòng số
        # Right=275: Sát mép phải
        # Bottom=247: Sát mép dưới
        print_box_relative = (100, 230, 275, 247)

        print_numbers = []

        for i in range(3): 
            # 1. Cắt từng thẻ lớn
            card_box = (x_coords[i], y_offset, x_coords[i] + card_width, y_offset + card_height)
            card_img = img.crop(card_box)

            # 2. Cắt vùng chứa số
            print_img = card_img.crop(print_box_relative)
            
            # --- XỬ LÝ ẢNH NÂNG CAO (QUAN TRỌNG) ---
            
            # A. Phóng to ảnh gấp 3 lần (Upscale) để Tesseract nhìn rõ số bé
            new_size = (print_img.width * 3, print_img.height * 3)
            print_img = print_img.resize(new_size, Image.Resampling.LANCZOS)
            
            # B. Chuyển sang ảnh xám
            print_img = print_img.convert('L')
            
            # C. Tăng tương phản (Binarization/Thresholding)
            # Biến màu xám mờ thành trắng, xám đậm thành đen tuyệt đối
            print_img = print_img.point(lambda p: 255 if p > 140 else 0)

            # D. Đảo ngược màu (Chuyển thành chữ đen nền trắng)
            print_img_inverted = ImageOps.invert(print_img)

            # 3. Đọc OCR
            # --psm 7: Treat the image as a single text line.
            # whitelist: Chỉ đọc số và ký tự phân cách
            custom_config = r"--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789.-·"
            raw_text = pytesseract.image_to_string(print_img_inverted, config=custom_config).strip()
            
            # 4. Làm sạch số liệu
            cleaned_num = clean_print_number(raw_text)
            print_numbers.append(cleaned_num)
            
            # (Tùy chọn) In ra console để debug nếu cần
            print(f"  [Thẻ {i+1}] Raw: '{raw_text}' -> Clean: '{cleaned_num}'")

        return print_numbers

    except Exception as e:
        print(f"  [LỖI OCR] {e}")
        return []

# --- PHẦN 3: SỰ KIỆN DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot đã online: {bot.user}')

@bot.event
async def on_message(message):
    # Chỉ xử lý tin nhắn từ Bot Karuta có đính kèm ảnh
    if not (message.author.id == KARUTA_ID and message.attachments):
        return

    attachment = message.attachments[0]
    if not attachment.content_type.startswith('image/'):
        return

    print("\n" + "="*40)
    print(f"🔎 Phát hiện ảnh Karuta. Đang xử lý...")

    try:
        # Tải ảnh về bộ nhớ
        response = requests.get(attachment.url)
        response.raise_for_status()
        image_bytes = response.content

        # Gọi hàm OCR
        print_numbers_list = await get_print_numbers_from_image(image_bytes)

        if not print_numbers_list:
            print("  -> Không nhận dạng được số nào.")
            print("="*40 + "\n")
            return

        async with message.channel.typing():
            await asyncio.sleep(0.5) 
            
            # Tạo nội dung trả lời theo định dạng yêu cầu
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            reply_lines = []
            
            for i, num in enumerate(print_numbers_list):
                # Format: ▪️ 1️⃣ | #12345
                line = f"▪️ {emojis[i]} | #{num}"
                reply_lines.append(line)
            
            reply_content = "\n".join(reply_lines)
            await message.reply(reply_content)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"  [LỖI] {e}")
    print("="*40 + "\n")

# --- PHẦN 4: KHỞI ĐỘNG ---
if __name__ == "__main__":
    if TOKEN:
        # Chạy Bot ở luồng riêng
        bot_thread = threading.Thread(target=bot.run, args=(TOKEN,))
        bot_thread.start()
        # Chạy Web Server để Render không tắt bot
        run_web_server()
    else:
        print("❌ LỖI: Chưa cấu hình DISCORD_TOKEN trong file .env")
