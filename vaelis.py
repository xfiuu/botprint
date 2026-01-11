import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
# Thêm ImageFilter để làm đậm chữ
from PIL import Image, ImageOps, ImageChops, ImageFilter 
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
def home(): return "Bot OCR Bold Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CẤU HÌNH ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264 

processed_cache = deque(maxlen=50)

def solve_ocr_fast(image_bytes, return_image=False):
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

            # 2. XỬ LÝ
            # Resize TO HƠN NỮA để khi làm đậm không bị dính nét
            crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.BILINEAR)
            
            # --- CHANNEL SUBTRACTION (Tách nền) ---
            if crop.mode != 'RGB': crop = crop.convert('RGB')
            r, g, b = crop.split()
            processed = ImageChops.subtract(r, b)
            processed = processed.point(lambda p: 255 if p > 50 else 0)
            processed = ImageOps.invert(processed)
            
            # --- BƯỚC MỚI: LÀM ĐẬM CHỮ (THICKEN) ---
            # MinFilter(3) sẽ tìm điểm đen nhất trong ô 3x3 và lan rộng nó ra
            # Giúp nối lại các nét đứt và làm số dày lên
            processed = processed.filter(ImageFilter.MinFilter(3))

            # Thêm viền trắng
            processed = ImageOps.expand(processed, border=30, fill='white')
            
            crops.append(processed)

        # 3. GỘP DỌC
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 30
        
        final_img = Image.new('L', (w_c, total_h), color=255)
        
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 15))
        final_img.paste(crops[2], (0, (h_c * 2) + 30))

        if return_image:
            return final_img

        # 4. OCR
        # Thêm --psm 6 để ép đọc thành 1 khối
        custom_config = r"--psm 6 -c tessedit_char_whitelist=0123456789-·."
        text = pytesseract.image_to_string(final_img, config=custom_config)
        
        # Debug: In ra xem Tesseract thực sự nhìn thấy gì
        print(f"OCR Raw Output: {text.strip()}")

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

# --- BOT COMMANDS (GIỮ NGUYÊN) ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT BOLD TEXT READY: {bot.user}')

@bot.command()
async def ocr(ctx):
    target_url = None
    if ctx.message.attachments:
        target_url = ctx.message.attachments[0].url
    elif ctx.message.reference:
        original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if original_msg.attachments:
            target_url = original_msg.attachments[0].url

    if not target_url:
        await ctx.send("❌ Vui lòng gửi/reply ảnh.")
        return

    async with ctx.typing():
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url) as resp:
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        processed_img = await loop.run_in_executor(
            None, 
            functools.partial(solve_ocr_fast, image_bytes, return_image=True)
        )

        if processed_img:
            with io.BytesIO() as image_binary:
                processed_img.save(image_binary, 'PNG')
                image_binary.seek(0)
                await ctx.send(
                    content="**Ảnh đã làm đậm (Thicken):**",
                    file=discord.File(fp=image_binary, filename='bold_ocr.png')
                )

@bot.event
async def on_message(message):
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
                image_bytes = await resp.read()

        loop = asyncio.get_running_loop()
        numbers = await loop.run_in_executor(None, functools.partial(solve_ocr_fast, image_bytes))

        if numbers:
            embed = discord.Embed(color=0x36393f, timestamp=message.created_at)
            embed.set_footer(text="⚡ Clean & Bold") 
            description = ""
            emojis = ["1️⃣", "2️⃣", "3️⃣"]
            for i, num in enumerate(numbers):
                status = f"**#{num}**" if num not in ["???", "Err"] else "⚠️ **Unknown**"
                description += f"▪️ {emojis[i]} | {status}\n"
            
            embed.description = description
            await message.reply(embed=embed, mention_author=False)
    except: pass

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=bot.run, args=(TOKEN,)).start()
        run_web_server()
