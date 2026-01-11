# main.py (Phiên bản CHỈ ĐỌC PRINT NUMBER - Góc dưới phải)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps # Cần thêm ImageOps để xử lý ảnh
from dotenv import load_dotenv
import threading
from flask import Flask
import asyncio
import pytesseract

# --- PHẦN 1: CẤU HÌNH WEB SERVER (Giữ nguyên để bot chạy trên host) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Discord (Đọc Print Number) đang hoạt động."

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- PHẦN 2: CẤU HÌNH VÀ CÁC HÀM CỦA BOT DISCORD ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Cấu hình đường dẫn Tesseract (Nếu chạy trên Windows thì bỏ comment dòng dưới)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def clean_print_number(text):
    """
    Làm sạch chuỗi OCR để chỉ lấy số print đầu tiên.
    Quy tắc: Gặp dấu chấm (.), gạch ngang (-) hoặc chấm giữa (·) thì bỏ phần sau.
    Chỉ giữ lại các ký tự số.
    """
    if not text:
        return "???"
    
    # Dùng regex để tách chuỗi tại các dấu phân cách thường gặp
    # Ký tự \u00B7 là dấu chấm giữa (·) thường thấy trên thẻ Karuta
    parts = re.split(r'[.\-\u00B7]', text)
    
    # Lấy phần đầu tiên (trước dấu phân cách)
    first_part = parts[0]
    
    # Chỉ giữ lại các ký tự số trong phần đầu tiên
    cleaned_number = re.sub(r'\D', '', first_part)
    
    return cleaned_number if cleaned_number else "???"

async def get_print_numbers_from_image(image_bytes):
    """
    Cắt ảnh tại góc dưới bên phải của 3 thẻ và đọc số Print Number.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        
        # Kiểm tra kích thước ảnh drop 3 thẻ (khoảng 836x312)
        if width < 830 or height < 300:
            print(f"  [OCR] Kích thước ảnh không phù hợp ({width}x{height}), bỏ qua.")
            return []

        # Kích thước cố định cho mỗi thẻ
        card_width = 278
        card_height = 248
        x_coords = [0, 279, 558] # Tọa độ x bắt đầu của mỗi thẻ
        y_offset = 32            # Tọa độ y bắt đầu của các thẻ

        # Tọa độ tương đối để cắt vùng số ở góc dưới phải (Relative crop box)
        # (Left, Top, Right, Bottom) tính từ góc trên trái của MỖI THẺ
        # Đã căn chỉnh dựa trên ảnh mẫu để lấy vừa đủ vùng số đen
        print_box_relative = (170, 225, 275, 248)

        print_numbers = []

        for i in range(3): # Xử lý 3 thẻ
            # 1. Cắt từng thẻ lớn ra khỏi ảnh gốc
            card_box = (x_coords[i], y_offset, x_coords[i] + card_width, y_offset + card_height)
            card_img = img.crop(card_box)

            # 2. Cắt lấy vùng nhỏ chứa số print ở góc dưới phải thẻ đó
            print_img = card_img.crop(print_box_relative)
            
            # 3. Xử lý ảnh trước khi đưa vào OCR (QUAN TRỌNG)
            # Chuyển sang ảnh xám (grayscale)
            print_img_gray = print_img.convert('L')
            # Đảo ngược màu: Biến chữ màu sáng trên nền tối thành chữ đen trên nền trắng
            # Tesseract đọc dạng này tốt hơn nhiều.
            print_img_inverted = ImageOps.invert(print_img_gray)

            # 4. Đọc chữ bằng Tesseract
            # Cấu hình chỉ cho phép đọc số và các dấu phân cách
            custom_config = r"--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789.-·"
            raw_text = pytesseract.image_to_string(print_img_inverted, config=custom_config).strip()
            
            # 5. Làm sạch dữ liệu theo yêu cầu
            cleaned_num = clean_print_number(raw_text)
            print_numbers.append(cleaned_num)
            print(f"  [Thẻ {i+1}] Raw: '{raw_text}' -> Cleaned: '{cleaned_num}'")

        return print_numbers

    except Exception as e:
        print(f"  [LỖI OCR] Đã xảy ra lỗi khi xử lý ảnh: {e}")
        return []

# --- PHẦN CHÍNH CỦA BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot Discord đã đăng nhập: {bot.user}')
    print('Bot đang chạy chế độ chỉ đọc Print Number.')

@bot.event
async def on_message(message):
    # Chỉ xử lý tin nhắn từ Karuta bot có đính kèm ảnh
    if not (message.author.id == KARUTA_ID and message.attachments):
        return

    attachment = message.attachments[0]
    if not attachment.content_type.startswith('image/'):
        return

    print("\n" + "="*40)
    print(f"🔎 [LOG] Phát hiện ảnh drop Karuta. Đang đọc số Print...")

    try:
        response = requests.get(attachment.url)
        response.raise_for_status()
        image_bytes = response.content

        # Gọi hàm xử lý ảnh mới
        print_numbers_list = await get_print_numbers_from_image(image_bytes)

        if not print_numbers_list:
            print("  -> Không đọc được số nào. Bỏ qua.")
            print("="*40 + "\n")
            return

        async with message.channel.typing():
            await asyncio.sleep(0.5) # Nghỉ nhẹ một chút cho tự nhiên
            
            # Danh sách emoji số thứ tự
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            reply_lines = []
            
            # Tạo nội dung tin nhắn trả về theo định dạng yêu cầu
            for i, num in enumerate(print_numbers_list):
                # Định dạng: ▪️ 1️⃣ | #12345
                line = f"▪️ {emojis[i]} | #{num}"
                reply_lines.append(line)
            
            reply_content = "\n".join(reply_lines)
            await message.reply(reply_content)
            print("✅ ĐÃ GỬI KẾT QUẢ PRINT NUMBER")

    except Exception as e:
        print(f"  [LỖI] Đã xảy ra lỗi: {e}")
    print("="*40 + "\n")

# --- PHẦN KHỞI ĐỘNG ---
if __name__ == "__main__":
    if TOKEN:
        bot_thread = threading.Thread(target=bot.run, args=(TOKEN,))
        bot_thread.start()
        run_web_server()
    else:
        print("❌ LỖI: Thiếu DISCORD_TOKEN trong file .env")