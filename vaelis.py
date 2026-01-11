import discord
from discord.ext import commands
import os
import re
import aiohttp
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
def home(): return "Bot OCR Karuta Ultimate Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264

# Nếu chạy trên Windows thì mở dòng dưới
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def process_image_ultimate(image_bytes):
    """
    Kỹ thuật: STITCHING + BINARIZATION
    1. Cắt 3 vùng ảnh.
    2. Xử lý thành Đen/Trắng tuyệt đối (giống tool bạn của bạn).
    3. Ghép lại thành 1 ảnh dài với khoảng cách CỰC LỚN để tránh dính số.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        card_w = w_img / 3
        
        # Tọa độ cắt (Đã chuẩn)
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78 

        processed_crops = []
        
        # Bước 1: Cắt và Xử lý từng mảnh
        for i in range(3):
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), 
                int(h_img * ratio_top),                    
                int(card_x_start + (card_w * ratio_right)),
                int(h_img * ratio_bottom)                  
            )
            crop = img.crop(box)

            # --- BẮT CHƯỚC FILTER CỦA TOOL BẠN KIA ---
            # 1. Resize nhẹ để chữ rõ nét hơn
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC)
            # 2. Chuyển xám
            crop = crop.convert('L')
            # 3. Tăng tương phản cực đại
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.0)
            # 4. Threshold (Nhị phân hóa): Biến tất cả điểm ảnh mờ thành trắng, chữ rõ thành đen
            # Số 140 là ngưỡng: Màu sáng hơn 140 -> 255 (Trắng), tối hơn -> 0 (Đen)
            crop = crop.point(lambda p: 255 if p > 140 else 0)
            # 5. Đảo màu (Vì Tesseract thích chữ Đen nền Trắng, nhưng Karuta gốc là chữ Trắng nền Đen)
            # Sau bước trên ta đang có chữ Trắng nền Đen, giờ đảo lại:
            crop = ImageOps.invert(crop)
            
            processed_crops.append(crop)

        # Bước 2: Gộp ảnh (Stitching) với Khoảng Cách An Toàn
        w_crop, h_crop = processed_crops[0].size
        gap = 100 # Khoảng trắng 100px giữa các thẻ (Rất rộng để không bị đọc dính)
        
        # Tạo ảnh nền trắng dài
        total_width = (w_crop * 3) + (gap * 2)
        stitched_img = Image.new('L', (total_width, h_crop), color=255) # 255 là màu trắng
        
        stitched_img.paste(processed_crops[0], (0, 0))
        stitched_img.paste(processed_crops[1], (w_crop + gap, 0))
        stitched_img.paste(processed_crops[2], ((w_crop + gap) * 2, 0))

        # Bước 3: OCR 1 lần duy nhất (Tốc độ tối đa)
        # psm 6: Đọc thành 1 dòng văn bản duy nhất
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-"
        text = pytesseract.image_to_string(stitched_img, config=custom_config)
        
        # Bước 4: Tách chuỗi kết quả
        # Vì khoảng cách rất xa, Tesseract sẽ trả về dạng "1234    5678    9012"
        # Ta dùng Regex tìm tất cả các cụm số
        matches = re.findall(r'\d+(?:-\d+)?', text)
        
        # Chuẩn hóa đầu ra thành list 3 phần tử
        results = []
        for i in range(3):
            if i < len(matches):
                results.append(matches[i])
            else:
                results.append("???") # Không đọc được
                
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
    print(f'🚀 Bot Karuta Speed Demon: {bot.user}')

@bot.event
async def on_message(message):
    if message.author.id != KARUTA_ID or not message.attachments: return
    att = message.attachments[0]
    if not att.content_type or "image" not in att.content_type: return

    try:
        # Tải ảnh Async (Không lag bot)
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # Xử lý ảnh ở luồng phụ (Non-blocking)
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(process_image_ultimate, image_bytes))

        if numbers:
            # --- TẠO EMBED ĐẸP ---
            embed = discord.Embed(
                color=0x36393f, # Màu xám đậm Discord
                timestamp=message.created_at
            )
            # Footer nhỏ thể hiện tốc độ (tùy chọn)
            embed.set_footer(text="⚡ Fast OCR") 

            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                # Format dòng dọc như yêu cầu
                if num in ["???", "Err", ""]:
                    description += f"▪️ {emojis[i]} | ⚠️ **Unknown**\n"
                else:
                    description += f"▪️ {emojis[i]} | **#{num}**\n"
            
            embed.description = description
            
            # Reply ngay lập tức
            await message.reply(embed=embed, mention_author=False)
            print(f"✅ Result: {numbers}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
