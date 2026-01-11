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
from collections import deque

# --- SERVER GIỮ BOT ONLINE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Debug Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264 

processed_cache = deque(maxlen=50)

def solve_ocr_fast(image_bytes, return_image=False):
    """
    ENGINE XỬ LÝ: Có thêm tham số return_image
    - Nếu return_image = True: Trả về tấm ảnh đã xử lý (để debug)
    - Nếu return_image = False: Trả về kết quả số (để bot chạy)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        card_w = w_img / 3
        
        ratio_top, ratio_bottom = 0.88, 0.94
        ratio_left, ratio_right = 0.54, 0.78 

        crops = []
        for i in range(3):
            # 1. CẮT
            card_x_start = int(i * card_w)
            box = (
                int(card_x_start + (card_w * ratio_left)), 
                int(h_img * ratio_top),                    
                int(card_x_start + (card_w * ratio_right)),
                int(h_img * ratio_bottom)                  
            )
            crop = img.crop(box)

            # 2. XỬ LÝ MÀU
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)

            # Tăng màu (Tách vàng khỏi xám)
            enhancer = ImageEnhance.Color(crop)
            crop = enhancer.enhance(2.5) 

            # Tăng tương phản
            enhancer = ImageEnhance.Contrast(crop)
            crop = enhancer.enhance(2.0)

            # 3. BINARIZATION
            crop = crop.convert('L')
            crop = crop.point(lambda p: 255 if p > 100 else 0)
            crop = ImageOps.invert(crop)
            crop = ImageOps.expand(crop, border=20, fill='white')
            
            crops.append(crop)

        # 4. GỘP DỌC
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 20
        
        final_img = Image.new('L', (w_c, total_h), color=255)
        
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 10))
        final_img.paste(crops[2], (0, (h_c * 2) + 20))

        # --- NẾU LÀ LỆNH !OCR THÌ TRẢ VỀ ẢNH LUÔN ---
        if return_image:
            return final_img

        # 5. OCR (Nếu bot chạy tự động)
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-·."
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
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

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT READY: {bot.user}')

# --- LỆNH !OCR (MỚI) ---
@bot.command()
async def ocr(ctx):
    """Lệnh để test xem bot nhìn thấy gì"""
    target_url = None

    # Trường hợp 1: Có đính kèm ảnh trong tin nhắn lệnh
    if ctx.message.attachments:
        target_url = ctx.message.attachments[0].url
    # Trường hợp 2: Reply vào một tin nhắn có ảnh
    elif ctx.message.reference:
        original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if original_msg.attachments:
            target_url = original_msg.attachments[0].url

    if not target_url:
        await ctx.send("❌ Vui lòng gửi kèm ảnh hoặc Reply vào ảnh cần check.")
        return

    async with ctx.typing():
        # Tải ảnh
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url) as resp:
                if resp.status != 200:
                    await ctx.send("❌ Lỗi tải ảnh.")
                    return
                image_bytes = await resp.read()

        # Xử lý ảnh (Bật chế độ return_image=True)
        loop = asyncio.get_running_loop()
        # Dùng partial để truyền tham số return_image=True
        processed_img = await loop.run_in_executor(
            None, 
            functools.partial(solve_ocr_fast, image_bytes, return_image=True)
        )

        if processed_img:
            # Chuyển ảnh PIL thành file gửi Discord
            with io.BytesIO() as image_binary:
                processed_img.save(image_binary, 'PNG')
                image_binary.seek(0)
                await ctx.send(
                    content="**Ảnh bot đã xử lý (Cắt -> Chỉnh màu -> Gộp):**",
                    file=discord.File(fp=image_binary, filename='debug_view.png')
                )
        else:
            await ctx.send("❌ Lỗi xử lý ảnh.")

# --- AUTO OCR KARUTA (GIỮ NGUYÊN) ---
@bot.event
async def on_message(message):
    # Dòng này để bot vẫn nhận lệnh !ocr
    await bot.process_commands(message)

    if message.author.id != KARUTA_ID: return
    if not message.attachments: return
    if message.id in processed_cache: return
    processed_cache.append(message.id)

    try:
        att = message.attachments[0]
        if "image" not in att.content_type: return

        async with aiohttp.ClientSession() as session:
            async with session.get(att.url) as resp:
                if resp.status != 200: return
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        # Mặc định return_image=False
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))

        if numbers:
            embed = discord.Embed(color=0x36393f, timestamp=message.created_at)
            embed.set_footer(text="⚡ Color Filter") 
            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                status = f"**#{num}**" if num not in ["???", "Err"] else "⚠️ **Unknown**"
                description += f"▪️ {emojis[i]} | {status}\n"
            
            embed.description = description
            await message.reply(embed=embed, mention_author=False)

    except Exception as e:
        print(f"Auto Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
