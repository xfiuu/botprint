# main.py - Phiên bản SIÊU CHÍNH XÁC (Threshold + Whitelist)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageEnhance
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta High Precision"
def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Nếu chạy Windows thì mở dòng này:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_print_number(text):
    """
    Xử lý chuỗi thô từ OCR.
    Thường định dạng là: '12345-1' hoặc '12345.1'
    Mục tiêu: Lấy '12345'
    """
    if not text: return "???"
    
    # 1. Thay thế các ký tự gây nhiễu thường gặp
    text = text.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    
    # 2. Tìm nhóm số đứng trước dấu gạch ngang (-) hoặc dấu chấm (.)
    # Ví dụ: 79096-1 -> Lấy 79096
    match = re.search(r'(\d+)[-.]\d+', text)
    if match:
        return match.group(1)
    
    # 3. Nếu không có dấu gạch ngang, lấy chuỗi số dài nhất tìm thấy
    numbers = re.findall(r'\d+', text)
    if numbers:
        # Lấy số dài nhất (để tránh lấy nhầm số 1 của edition)
        return max(numbers, key=len)
        
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Tính kích thước 1 thẻ
        card_w = w_img / 3
        
        # --- TỌA ĐỘ CẮT MỚI (SIÊU THẤP) ---
        # Chỉ nhắm vào cái "viên thuốc" đen ở góc dưới
        # Top: 93.5% (Bỏ qua hoàn toàn tên Series)
        # Left: 55% (Bỏ qua phần bên trái)
        
        ratio_top = 0.935 
        ratio_left = 0.55
        
        rel_top = int(h_img * ratio_top)
        rel_bottom = h_img - 2 # Cách đáy 2 pixel cho an toàn
        rel_left = int(card_w * ratio_left)
        rel_right = int(card_w * 0.98) # Cách mép phải một chút

        results = []
        debug_images = [] 

        for i in range(3):
            card_x_start = int(i * card_w)
            
            box_left = card_x_start + rel_left
            box_top = rel_top
            box_right = card_x_start + rel_right
            box_bottom = rel_bottom

            # 1. Cắt ảnh
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH CHUYÊN SÂU ---
            
            # A. Phóng to gấp 5 lần
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            
            # B. Chuyển xám
            crop = crop.convert('L')
            
            # C. THRESHOLDING (Quan trọng nhất)
            # Biến tất cả điểm ảnh: Màu xám nhẹ -> Trắng tinh. Màu xám đậm -> Đen tuyền.
            # Ngưỡng 100: Nếu điểm ảnh tối hơn 100 (khá tối) thì giữ là đen, còn lại thành trắng.
            # Điều này giúp loại bỏ nền loang lổ.
            crop = crop.point(lambda p: 255 if p > 90 else 0)
            
            # D. Đảo màu (để thành chữ Đen nền Trắng - Tesseract thích cái này nhất)
            crop = ImageOps.invert(crop)
            
            # E. Thêm viền trắng xung quanh (padding) để số không bị sát mép quá
            crop = ImageOps.expand(crop, border=10, fill='white')

            # Lưu ảnh debug để bạn xem bot nhìn thấy gì
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            debug_images.append(discord.File(img_byte_arr, filename=f"card_{i+1}_clean.png"))

            # 2. OCR với CONFIG CHẶT CHẼ
            # --psm 7: Coi là 1 dòng văn bản duy nhất
            # -c tessedit_char_whitelist: CHỈ cho phép đọc số và dấu gạch ngang
            custom_config = r"--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789-"
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            
            final_num = extract_print_number(raw_text)
            results.append(final_num)
            print(f"  [Card {i+1}] Raw: '{raw_text}' -> Final: '{final_num}'")

        return results, debug_images

    except Exception as e:
        print(f"Lỗi: {e}")
        return [], []

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready(): print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    if not (message.author.id == KARUTA_ID and message.attachments): return
    if not message.attachments[0].content_type.startswith('image/'): return

    print("🔎 Đang đọc số Print...")
    try:
        response = requests.get(message.attachments[0].url)
        numbers, debug_imgs = await get_print_numbers_from_image(response.content)

        if numbers:
            reply_text = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                reply_text += f"▪️ {emojis[i]} | **#{num}**\n"
            
            # Gửi kết quả + Ảnh trắng đen bot đã nhìn thấy
            await message.reply(content=reply_text, files=debug_imgs)

    except Exception as e:
        print(f"❌ Lỗi: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
