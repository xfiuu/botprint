# main.py - Phiên bản Tự Động Căn Chỉnh (Auto-Scale) + Debug Mode

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageStat, ImageEnhance
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- PHẦN 1: WEB SERVER (Giữ bot online trên Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot OCR Karuta đang hoạt động."

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- PHẦN 2: CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Nếu chạy trên Windows thì mở comment dòng dưới
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def clean_print_number(text):
    """Lọc bỏ ký tự rác, chỉ giữ lại số"""
    if not text: return "???"
    text = re.sub(r'[^\d]', '', text) 
    return text if text else "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # In log kích thước ảnh để kiểm tra
        print(f"  [DEBUG] Kích thước ảnh gốc: {w_img}x{h_img}")

        # Tính toán kích thước 1 thẻ (Ảnh Karuta drop 3 thẻ ngang)
        card_w = w_img / 3
        
        # --- CẤU HÌNH CẮT THEO TỈ LỆ % (QUAN TRỌNG) ---
        # Thay vì dùng pixel cố định, ta dùng % để áp dụng cho mọi size ảnh
        
        # Left: Bắt đầu từ 35% chiều ngang của thẻ (để lấy phần số bên phải)
        # Top: Bắt đầu từ 88% chiều dọc của thẻ (để lấy phần đáy chứa số)
        ratio_left = 0.35  
        ratio_top = 0.88   
        
        # Tính ra pixel thực tế
        rel_top = int(h_img * ratio_top)
        rel_bottom = h_img # Đáy ảnh
        rel_left = int(card_w * ratio_left)
        rel_right = int(card_w * 0.99) # Sát mép phải (chừa 1% viền)

        results = []
        debug_images = [] # Danh sách ảnh cắt được để gửi lại Discord

        for i in range(3):
            # 1. Xác định tọa độ X bắt đầu của từng thẻ
            card_x_start = int(i * card_w)
            
            # 2. Tính tọa độ cắt chính xác trên ảnh gốc
            box_left = card_x_start + rel_left
            box_top = rel_top
            box_right = card_x_start + rel_right
            box_bottom = rel_bottom

            # 3. Cắt ảnh
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- XỬ LÝ ẢNH NÂNG CAO ---
            # Phóng to gấp 4 lần để Tesseract đọc rõ hơn
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            
            # Chuyển sang ảnh xám
            crop = crop.convert('L')
            
            # Tự động nhận diện nền Sáng hay Tối
            stat = ImageStat.Stat(crop)
            avg_brightness = stat.mean[0]
            
            # Nếu nền tối (đen) -> Đảo màu thành nền trắng chữ đen
            if avg_brightness < 100: 
                crop = ImageOps.invert(crop)

            # Tăng độ tương phản mạnh
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.0)
            
            # Chuẩn hóa trắng đen (Threshold)
            crop = crop.point(lambda p: 255 if p > 160 else 0)

            # Lưu ảnh vào bộ nhớ để gửi lại Discord (Debug)
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            debug_images.append(discord.File(img_byte_arr, filename=f"debug_card_{i+1}.png"))

            # 4. Đọc OCR
            # psm 7: Coi ảnh là một dòng văn bản đơn lẻ
            custom_config = r"--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789"
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            
            cleaned = clean_print_number(raw_text)
            results.append(cleaned)
            print(f"  [Card {i+1}] Raw: {raw_text} -> Clean: {cleaned}")

        return results, debug_images

    except Exception as e:
        print(f"Lỗi xử lý ảnh: {e}")
        return [], []

# --- PHẦN 3: BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot đã online: {bot.user}')

@bot.event
async def on_message(message):
    # Chỉ nhận tin nhắn từ Karuta có đính kèm ảnh
    if not (message.author.id == KARUTA_ID and message.attachments):
        return

    attachment = message.attachments[0]
    if not attachment.content_type.startswith('image/'):
        return

    print("\n" + "="*30)
    print("🔎 Phát hiện ảnh Karuta Drop...")

    try:
        response = requests.get(attachment.url)
        image_bytes = response.content
        
        # Gọi hàm xử lý (Nhận về kết quả số VÀ hình ảnh debug)
        numbers, debug_imgs = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi tin nhắn kèm theo 3 tấm ảnh bot đã cắt
            await message.reply(content=reply_text, files=debug_imgs)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
    print("="*30 + "\n")

# --- PHẦN 4: KHỞI CHẠY ---
if __name__ == "__main__":
    if TOKEN:
        # Chạy Bot ở luồng riêng
        t = threading.Thread(target=bot.run, args=(TOKEN,))
        t.start()
        # Chạy Web Server
        run_web_server()
    else:
        print("❌ LỖI: Chưa có DISCORD_TOKEN trong file .env")
