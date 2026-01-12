import discord
from discord.ext import commands
import os
import re
import aiohttp
import io
# Thêm ImageDraw để dùng tính năng tô màu (floodfill)
from PIL import Image, ImageOps, ImageChops, ImageFilter, ImageDraw 
from dotenv import load_dotenv
import threading
from flask import Flask
import pytesseract
import asyncio
import functools
from collections import deque

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot OCR Edge Clean Mode."
def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIG ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
KARUTA_ID = 646937666251915264 
processed_cache = deque(maxlen=50)

def solve_ocr_fast(image_bytes, return_image=False):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w_img, h_img = img.size
        
        card_w = w_img / 3
        
        # Tọa độ cắt
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
            # Resize x5 (High Res)
            crop = crop.resize((crop.width * 5, crop.height * 5), Image.Resampling.LANCZOS)
            
            # Channel Subtraction (Tách nền)
            if crop.mode != 'RGB': crop = crop.convert('RGB')
            r, g, b = crop.split()
            processed = ImageChops.subtract(r, b)
            
            # Threshold
            processed = processed.point(lambda p: 255 if p > 50 else 0)
            processed = ImageOps.invert(processed)
            
            # MinFilter (Làm đậm nét)
            processed = processed.filter(ImageFilter.MinFilter(3))

            # --- BƯỚC MỚI: XÓA RÁC DÍNH VIỀN (FLOOD FILL) ---
            # Số màu ĐEN (0), Nền màu TRẮNG (255)
            # Ta quét dọc mép trái và mép phải. 
            # Nếu thấy màu đen dính mép -> Tô trắng nó đi.
            
            ImageDraw.floodfill(processed, (0, 0), 255) # Fix nhẹ góc trên trái
            
            # 1. Quét mép trái (Xử lý cái vệt đen bạn gặp)
            for y in range(processed.height):
                # Nếu pixel tại (0, y) là màu đen (0)
                if processed.getpixel((0, y)) == 0:
                    # Tô trắng toàn bộ vùng đen dính với nó
                    ImageDraw.floodfill(processed, (0, y), 255)

            # 2. Quét mép phải (Đề phòng khung bên phải lấn qua)
            w_p = processed.width
            for y in range(processed.height):
                if processed.getpixel((w_p - 1, y)) == 0:
                    ImageDraw.floodfill(processed, (w_p - 1, y), 255)

            # Thêm viền trắng an toàn sau khi đã làm sạch
            processed = ImageOps.expand(processed, border=50, fill='white')
            
            crops.append(processed)

        # 3. GỘP DỌC
        w_c, h_c = crops[0].size
        total_h = (h_c * 3) + 50
        
        final_img = Image.new('L', (w_c, total_h), color=255)
        
        final_img.paste(crops[0], (0, 0))
        final_img.paste(crops[1], (0, h_c + 20))
        final_img.paste(crops[2], (0, (h_c * 2) + 40))

        if return_image:
            return final_img

        # 4. OCR
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

# --- BOT COMMANDS ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'✨ BOT EDGE CLEANER READY: {bot.user}')

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
                    content="**Ảnh đã xóa vệt đen dính mép:**",
                    file=discord.File(fp=image_binary, filename='clean_edge.png')
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
            embed.set_footer(text="⚡ Clean Edge Mode") 
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
