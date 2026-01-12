import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
import gc # Thư viện dọn rác RAM
from PIL import Image, ImageOps, ImageChops, ImageFilter, ImageDraw 
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
def home(): return "Bot OCR Final Optimized."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264 
# Cache chống spam (50 tin gần nhất)
processed_cache = deque(maxlen=50)

# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def solve_ocr_fast(image_bytes):
    """
    ENGINE XỬ LÝ ẢNH (FINAL OPTIMIZED)
    - Resize x5 (Lanczos)
    - Subtract Red-Blue (Tách nền)
    - Flood Fill (Xóa viền đen lỗi)
    - MinFilter (Làm đậm nét)
    - Vertical Stack (Gộp dọc)
    - Quản lý RAM chặt chẽ
    """
    crops = []
    
    try:
        # Load ảnh vào RAM
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            w_img, h_img = img.size
            
            card_w = w_img / 3
            ratio_top, ratio_bottom = 0.88, 0.94
            ratio_left, ratio_right = 0.54, 0.78 

            for i in range(3):
                # 1. CẮT & RESIZE
                card_x_start = int(i * card_w)
                box = (
                    int(card_x_start + (card_w * ratio_left)), 
                    int(h_img * ratio_top),                    
                    int(card_x_start + (card_w * ratio_right)),
                    int(h_img * ratio_bottom)                  
                )
                
                # Resize x5 dùng thuật toán Lanczos (Nét nhất)
                crop = img.crop(box).resize(
                    (int((box[2]-box[0]) * 5), int((box[3]-box[1]) * 5)), 
                    Image.Resampling.LANCZOS
                )
                
                # 2. XỬ LÝ MÀU (Tách nền)
                if crop.mode != 'RGB': crop = crop.convert('RGB')
                r, g, b = crop.split()
                
                # Lấy Đỏ trừ Xanh Dương (Chữ vàng sẽ sáng lên)
                processed = ImageChops.subtract(r, b)
                
                # Xóa kênh màu thừa ngay để nhẹ RAM
                del r, g, b
                
                # Threshold & Đảo màu
                processed = processed.point(lambda p: 255 if p > 50 else 0)
                processed = ImageOps.invert(processed)
                
                # Làm đậm nét (Fix nét đứt)
                processed = processed.filter(ImageFilter.MinFilter(3))

                # 3. XÓA VIỀN ĐEN (FLOOD FILL) - TỐI ƯU
                # Chỉ kiểm tra 3 điểm neo để tốc độ nhanh nhất
                # Nếu phát hiện màu đen ở mép -> Tô trắng toàn bộ vùng dính liền
                if processed.getpixel((0, 0)) == 0:
                    ImageDraw.floodfill(processed, (0, 0), 255)
                
                mid_h = processed.height // 2
                if processed.getpixel((0, mid_h)) == 0:
                    ImageDraw.floodfill(processed, (0, mid_h), 255)

                w_p = processed.width - 1
                if processed.getpixel((w_p, 0)) == 0:
                    ImageDraw.floodfill(processed, (w_p, 0), 255)

                # Thêm viền trắng an toàn
                processed = ImageOps.expand(processed, border=50, fill='white')
                crops.append(processed)

        # Xóa ảnh gốc khỏi RAM
        del img

        # 4. GỘP DỌC
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 50
        
        final_img = Image.new('L', (w_c, total_h), color=255)
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 20))
        final_img.paste(crops[2], (0, (h_c * 2) + 40))

        # Xóa các mảnh crop
        del crops

        # 5. OCR
        # --psm 6: Đọc theo khối dọc
        # tessedit_do_invert=0: Tắt tính năng tự đảo màu (Tăng tốc)
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-·. -c tessedit_do_invert=0"
        
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
        # Xóa ảnh cuối cùng & Dọn rác
        del final_img
        gc.collect() 

        # 6. PARSE KẾT QUẢ
        matches = re.findall(r'\d+(?:[-·\.]\d+)?', text)
        results = []
        for i in range(3):
            if i < len(matches):
                clean_num = matches[i].replace('·', '-').replace('.', '-')
                results.append(clean_num)
            else:
                results.append("???")
        
        return results

    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        # Chắc chắn dọn rác dù có lỗi hay không
        gc.collect()

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT OCR ONLINE: {bot.user}')

@bot.event
async def on_message(message):
    # Chỉ nhận tin từ Karuta Bot
    if message.author.id != KARUTA_ID: return
    
    # Chỉ xử lý tin nhắn có ảnh
    if not message.attachments: return
    
    # Check cache để tránh xử lý trùng
    if message.id in processed_cache: return
    processed_cache.append(message.id)

    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        # 1. Tải ảnh về RAM
        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        # 2. Xử lý ảnh (Chạy ngầm để không chặn bot)
        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))
        
        # --- QUAN TRỌNG: XÓA DỮ LIỆU ẢNH GỐC NGAY LẬP TỨC ---
        del image_bytes 
        gc.collect()
        # ----------------------------------------------------

        if numbers:
            embed = discord.Embed(
                color=0x36393f, 
                timestamp=message.created_at
            )
            embed.set_footer(text="⚡ Fast & Accurate") 

            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            
            for i, num in enumerate(numbers):
                if num in ["???", "Err", "", []]:
                    description += f"▪️ {emojis[i]} | ⚠️ **Unknown**\n"
                else:
                    description += f"▪️ {emojis[i]} | **#{num}**\n"
            
            embed.description = description
            await message.reply(embed=embed, mention_author=False)
            
            # Xóa biến kết quả cho sạch sẽ
            del numbers
            gc.collect()

    except Exception as e:
        print(f"System Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
    else:
        print("❌ Thiếu Token")
