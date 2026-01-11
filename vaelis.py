# main.py - Phiên bản OPTIMIZED (Tăng tương phản & Làm nét)

import discord
from discord.ext import commands
import os
import re
import requests
import io
from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFilter
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract

# --- SERVER GIỮ BOT ONLINE (Dành cho Render/Heroku) ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Karuta đang chạy ổn định."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# LƯU Ý: Nếu chạy trên Windows, hãy bỏ comment dòng dưới và trỏ đúng đường dẫn
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_number_with_regex(text):
    """
    Lọc lấy số print từ chuỗi OCR.
    Xử lý các trường hợp: '7752-5', '42764 · 2', '42764 . 2'
    """
    if not text: return "???"
    
    # 1. Thay thế các ký tự dễ nhầm lẫn thành gạch ngang hoặc khoảng trắng
    # Karuta hay dùng dấu '·' (middle dot) giữa số print và edition
    text = text.replace('·', '-').replace('.', '-')
    
    # 2. Chỉ giữ lại số và dấu gạch ngang
    clean_text = re.sub(r'[^\d-]', ' ', text)
    
    # 3. Tìm tất cả các cụm số
    # Regex này tìm chuỗi số, có thể kèm theo gạch ngang và số đuôi (VD: 1234-5)
    matches = re.findall(r'\d+(?:-\d+)?', clean_text)
    
    if matches:
        # Lấy chuỗi dài nhất tìm được (ưu tiên số Print to hơn số Edition đơn lẻ)
        matches.sort(key=len, reverse=True)
        return matches[0]
        
    return "???"

async def get_print_numbers_from_image(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        # Tạo ảnh debug
        debug_draw_img = img.copy()
        draw = ImageDraw.Draw(debug_draw_img)

        card_w = w_img / 3
        
        # --- CẤU HÌNH VÙNG CẮT (ĐÃ TINH CHỈNH CHO GIẢI PHÁP 1) ---
        # ratio_left: 0.58 -> Bỏ qua phần tên Series bên trái, tập trung vào góc phải
        ratio_top = 0.88
        ratio_bottom = 0.96   
        ratio_left = 0.58     
        ratio_right = 0.96

        rel_top = int(h_img * ratio_top)
        rel_bottom = int(h_img * ratio_bottom)

        results = []
        cropped_images = [] 

        for i in range(3):
            card_x_start = int(i * card_w)
            
            rel_left_px = int(card_w * ratio_left)
            rel_right_px = int(card_w * ratio_right)
            
            box_left = card_x_start + rel_left_px
            box_top = rel_top
            box_right = card_x_start + rel_right_px
            box_bottom = rel_bottom

            # 1. Vẽ khung đỏ debug
            draw.rectangle([box_left, box_top, box_right, box_bottom], outline="red", width=3)

            # 2. Cắt ảnh con
            crop = img.crop((box_left, box_top, box_right, box_bottom))

            # --- QUY TRÌNH XỬ LÝ ẢNH (PRE-PROCESSING) ---
            
            # B1: Upscale gấp 4 lần (LANCZOS giúp giữ chi tiết tốt hơn)
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            
            # B2: Chuyển sang Grayscale (Thang xám)
            crop = crop.convert('L')
            
            # B3: Tăng độ tương phản (Contrast) - QUAN TRỌNG
            # Giúp tách chữ trắng ra khỏi nền xám mờ của thẻ
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.5) # Tăng tương phản lên 2.5 lần
            
            # B4: Làm sắc nét (Sharpen) để viền chữ rõ hơn
            crop = crop.filter(ImageFilter.SHARPEN)

            # B5: Thresholding (Lọc ngưỡng)
            # Vì chữ Print là màu trắng nhất, ta lọc lấy các điểm ảnh rất sáng (>135)
            # Các phần nền xám, vàng, tối sẽ bị biến thành đen (0)
            crop = crop.point(lambda p: 255 if p > 135 else 0)
            
            # B6: Đảo màu (Invert)
            # Tesseract đọc tốt nhất với "Chữ Đen trên Nền Trắng"
            crop = ImageOps.invert(crop)

            # B7: Thêm viền trắng (Padding)
            crop = ImageOps.expand(crop, border=30, fill='white')

            # Lưu ảnh crop vào bộ nhớ để gửi lên Discord (Debug visual)
            img_byte_arr = io.BytesIO()
            crop.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            cropped_images.append(discord.File(img_byte_arr, filename=f"debug_crop_{i+1}.png"))

            # 3. OCR Config
            # Thêm dấu chấm (.) và dấu ngã (~) vào whitelist vì đôi khi dấu gạch ngang bị đọc nhầm
            custom_config = r"--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789-.~·" 
            
            raw_text = pytesseract.image_to_string(crop, config=custom_config).strip()
            final_num = extract_number_with_regex(raw_text)
            
            results.append(final_num)
            print(f"  [Card {i+1}] OCR Raw: '{raw_text}' -> Clean: '{final_num}'")

        # Lưu ảnh Debug toàn cảnh
        full_debug_byte = io.BytesIO()
        debug_draw_img.save(full_debug_byte, format='PNG')
        full_debug_byte.seek(0)
        debug_file = discord.File(full_debug_byte, filename="DEBUG_FULL.png")

        return results, debug_file, cropped_images

    except Exception as e:
        print(f"Lỗi xử lý ảnh: {e}")
        return [], None, []

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')

@bot.event
async def on_message(message):
    # Chỉ xử lý tin nhắn từ Karuta (ID: 646937666251915264) có ảnh đính kèm
    if not (message.author.id == KARUTA_ID and message.attachments): return
    if not message.attachments[0].content_type.startswith('image/'): return

    print("\n" + "="*30)
    print("🔎 Phát hiện ảnh Karuta, bắt đầu quét...")

    try:
        response = requests.get(message.attachments[0].url)
        image_bytes = response.content
        
        # Gọi hàm xử lý
        numbers, debug_full, debug_crops = await get_print_numbers_from_image(image_bytes)

        if numbers:
            reply_lines = []
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num == "???":
                    reply_lines.append(f"▪️ {emojis[i]} | ⚠️ Không đọc được")
                else:
                    reply_lines.append(f"▪️ {emojis[i]} | **#{num}**")
            
            reply_text = "\n".join(reply_lines)
            
            # Gửi kết quả kèm ảnh debug
            all_files = [debug_full] + debug_crops
            
            await message.reply(content=reply_text, files=all_files)
            print("✅ Đã gửi kết quả.")

    except Exception as e:
        print(f"❌ Lỗi Bot: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ LỖI: Chưa set DISCORD_TOKEN trong file .env")
