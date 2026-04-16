from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import httpx
import base64
import uuid
import os
import re
import asyncio
import random
import urllib.parse
import io
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== GIGACHAT КЛИЕНТ ====================
class GigaChatClient:
    def __init__(self):
        self.client_id = os.environ.get("GIGACHAT_CLIENT_ID")
        self.client_secret = os.environ.get("GIGACHAT_CLIENT_SECRET")
        self._token = None
        self._token_expires = None

    async def _get_token(self):
        if self._token and self._token_expires and self._token_expires > datetime.now():
            return self._token

        credentials = f"{self.client_id}:{self.client_secret}"
        auth_key = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={
                    "Authorization": f"Basic {auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"scope": "GIGACHAT_API_PERS"}
            )
            result = response.json()
            self._token = result["access_token"]
            self._token_expires = datetime.now() + timedelta(seconds=result.get("expires_in", 3600))
            return self._token

    async def chat(self, messages, temperature=0.8):
        token = await self._get_token()
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "GigaChat-Pro",
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 1000
                },
                timeout=30.0
            )
            return response.json()["choices"][0]["message"]["content"]

    async def generate_image(self, prompt: str) -> str:
        """Генерирует картинку через бесплатный API pollinations.ai"""
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30.0)
            if response.status_code != 200:
                raise Exception(f"Image generation failed: {response.status_code}")
            return base64.b64encode(response.content).decode('utf-8')

gigachat = GigaChatClient()

# ==================== ПРОМПТЫ ====================
SYSTEM_PROMPT = """Ты — Оракул, мистический предсказатель на картах Таро.
Твои ответы должны быть таинственными, в готическом стиле.
Никогда не пиши, что ты ИИ. Ты — Оракул, древний дух."""

def get_daily_prompt():
    return "Вытяни одну карту Таро и дай предсказание на сегодня."

def get_yesno_prompt(question):
    return f"Вопрос: '{question}'. Ответь ДА или НЕТ, затем объясни."

def get_three_prompt(question):
    return f"Сделай расклад Три карты на вопрос: '{question}'."

def get_celtic_prompt(question):
    return f"Сделай расклад Кельтский крест на вопрос: '{question}'."

# ==================== МОДЕЛИ ====================
class PredictRequest(BaseModel):
    spread_type: str
    question: Optional[str] = None
    cards: Optional[List[dict]] = None

class OracleAskRequest(BaseModel):
    question: str

# ==================== ТЕМЫ ДЛЯ ПОСТОВ ====================
MIDDAY_TOPICS = [
    "женская сила", "мистические факты", "как эзотерика помогает людям",
    "истории успеха", "эзотерические практики", "символы и знаки",
    "магия в повседневности", "интуиция", "энергии", "места силы"
]

EVENING_TOPICS = [
    "легенды и мифы", "мистические истории", "притчи и мудрость",
    "городские легенды", "лунные истории", "мифы народов мира",
    "истории о привидениях", "древние тайны", "загадки прошлого"
]

# ==================== ФУНКЦИИ ДЛЯ ПОСТОВ ====================
async def generate_post_with_image(topic: str, hour: int) -> dict:
    try:
        print(f"DEBUG: Начало генерации поста. Тема: {topic}, час: {hour}")
        
        if hour == 12:
            style_prompt = "Напиши познавательный пост для соцсетей. 5-7 предложений. Используй эмодзи, разбивку на абзацы. Загадочный, но понятный стиль."
            image_prompt = f"Мистическая иллюстрация на тему: {topic}. Готический стиль, тёмные тона, золотые акценты, магическая атмосфера. Без текста."
        else:
            style_prompt = "Напиши атмосферный, уютный пост для вечернего чтения. 5-7 предложений. Используй эмодзи, разбивку на абзацы. Как рассказчик у камина."
            image_prompt = f"Атмосферная иллюстрация к легенде или мистической истории на тему: {topic}. Стиль: тёмная фэнтези, готика, уютная магия. Без текста."
        
        print(f"DEBUG: Промпт для текста: {style_prompt[:80]}...")
        
        # Генерация текста
        text_messages = [
            {"role": "system", "content": f"Ты — Оракул, автор мистического Telegram-канала. Напиши пост.\n\n{style_prompt}\n\nЗаканчивай вопросом к читателю или призывом поделиться мнением."},
            {"role": "user", "content": f"Напиши пост на тему: {topic}"}
        ]
        post_text = await gigachat.chat(text_messages, temperature=0.8)
        print(f"DEBUG: Текст получен, длина: {len(post_text)}")
        
        # Генерация картинки
        print(f"DEBUG: Промпт для картинки: {image_prompt[:80]}...")
        image_base64 = await gigachat.generate_image(image_prompt)
        print(f"DEBUG: Картинка получена, длина base64: {len(image_base64)}")
        
        return {
            "success": True,
            "text": post_text,
            "image_base64": image_base64,
            "topic": topic
        }
    except Exception as e:
        print(f"DEBUG: ОШИБКА: {str(e)}")
        return {"success": False, "error": str(e)}

async def send_post_to_channel(chat_id: str, bot_token: str, post_text: str, image_base64: str = None):
    async with httpx.AsyncClient() as client:
        if image_base64:
            print(f"DEBUG: Отправка фото в Telegram, длина caption: {len(post_text)}")
            try:
                # Декодируем base64 в байты
                image_bytes = base64.b64decode(image_base64)
                # Пробуем конвертировать в JPEG через Pillow
                img = Image.open(io.BytesIO(image_bytes))
                # Конвертируем в RGB (Telegram не любит RGBA)
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (0, 0, 0))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = rgb_img
                # Сохраняем в буфер
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=85)
                output.seek(0)
                files = {"photo": ("image.jpg", output, "image/jpeg")}
            except Exception as e:
                print(f"DEBUG: Ошибка обработки картинки: {e}, отправляем как есть")
                files = {"photo": ("image.jpg", image_bytes, "image/jpeg")}
            
            data = {"chat_id": chat_id, "caption": post_text, "parse_mode": "Markdown"}
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data=data,
                files=files
            )
            print(f"DEBUG: Ответ Telegram: {response.status_code} - {response.text[:200]}")
            print(f"DEBUG: Фото отправлено")
        else:
            print(f"DEBUG: Отправка только текста в Telegram")
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": post_text, "parse_mode": "Markdown"}
            )
            print(f"DEBUG: Текст отправлен")

async def midday_post_job():
    print("DEBUG: midday_post_job запущена")
    topic = random.choice(MIDDAY_TOPICS)
    result = await generate_post_with_image(topic, 12)
    if result["success"]:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        await send_post_to_channel(chat_id, bot_token, result["text"], result.get("image_base64"))
    else:
        print(f"Ошибка генерации дневного поста: {result.get('error')}")

async def evening_post_job():
    print("DEBUG: evening_post_job запущена")
    topic = random.choice(EVENING_TOPICS)
    result = await generate_post_with_image(topic, 17)
    if result["success"]:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        await send_post_to_channel(chat_id, bot_token, result["text"], result.get("image_base64"))
    else:
        print(f"Ошибка генерации вечернего поста: {result.get('error')}")

# ==================== ОСНОВНЫЕ ЭНДПОИНТЫ ====================
@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.post("/api/predict")
async def make_prediction(request: PredictRequest):
    try:
        if request.spread_type == "daily":
            user_prompt = get_daily_prompt()
        elif request.spread_type == "yesno":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_yesno_prompt(request.question)
        elif request.spread_type == "three":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_three_prompt(request.question)
        elif request.spread_type == "celtic":
            if not request.question:
                raise HTTPException(status_code=400, detail="Вопрос обязателен")
            user_prompt = get_celtic_prompt(request.question)
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип расклада")

        if request.cards:
            cards_info = "\n".join([f"- {card.get('name')}: {card.get('meaning')}" for card in request.cards])
            user_prompt += f"\n\nВыпавшие карты:\n{cards_info}\n\nСделай предсказание, основываясь на этих картах."

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        prediction = await gigachat.chat(messages)
        return {"success": True, "prediction": prediction}
    except Exception as e:
        return {"success": False, "error": str(e), "prediction": "Оракул временно молчит. Попробуй позже."}

@app.post("/api/oracle/ask")
async def oracle_ask(request: OracleAskRequest):
    try:
        messages = [
            {"role": "system", "content": "Ты — Всевидящий Оракул, древний дух. Отвечай кратко, мудро и загадочно, в готическом стиле. Никогда не пиши, что ты ИИ."},
            {"role": "user", "content": request.question}
        ]
        answer = await gigachat.chat(messages, temperature=0.8)
        return {"success": True, "answer": answer}
    except Exception as e:
        return {"success": False, "error": str(e), "answer": "Оракул временно молчит. Попробуй позже."}

# ==================== ТЕСТОВЫЕ ЭНДПОИНТЫ ====================
@app.get("/api/test-gigachat")
async def test_gigachat():
    result = {
        "has_client_id": bool(os.environ.get("GIGACHAT_CLIENT_ID")),
        "has_client_secret": bool(os.environ.get("GIGACHAT_CLIENT_SECRET")),
        "token_response": None,
        "error": None
    }
    try:
        credentials = f"{os.environ.get('GIGACHAT_CLIENT_ID')}:{os.environ.get('GIGACHAT_CLIENT_SECRET')}"
        auth_key = base64.b64encode(credentials.encode()).decode()
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={
                    "Authorization": f"Basic {auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"scope": "GIGACHAT_API_PERS"}
            )
            result["token_response"] = response.status_code
            if response.status_code == 200:
                data = response.json()
                result["has_access_token"] = bool(data.get("access_token"))
            else:
                result["error"] = response.text
    except Exception as e:
        result["error"] = str(e)
    return result

@app.get("/api/test-midday")
async def test_midday():
    print("DEBUG: /api/test-midday вызван")
    await midday_post_job()
    return {"status": "ok"}

@app.get("/api/test-evening")
async def test_evening():
    print("DEBUG: /api/test-evening вызван")
    await evening_post_job()
    return {"status": "ok"}

# ==================== ВРЕМЕННЫЙ ЭНДПОИНТ ДЛЯ ТЕСТА ФОТО ====================
@app.get("/test-photo")
async def test_photo():
    """Временный эндпоинт для проверки отправки фото"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        return {"error": "Не настроены TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID"}
    
    image_url = "https://image.pollinations.ai/prompt/тестовое%20фото%20готический%20стиль?width=512&height=512"
    
    async with httpx.AsyncClient() as client:
        # Скачиваем картинку
        img_response = await client.get(image_url)
        if img_response.status_code != 200:
            return {"error": f"Не удалось скачать картинку: {img_response.status_code}"}
        
        image_base64 = base64.b64encode(img_response.content).decode('utf-8')
        
        # Обрабатываем картинку
        try:
            image_bytes = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (0, 0, 0))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85)
            output.seek(0)
            files = {"photo": ("test.jpg", output, "image/jpeg")}
        except Exception as e:
            files = {"photo": ("test.jpg", image_bytes, "image/jpeg")}
        
        data = {"chat_id": chat_id, "caption": "🧙 *Тестовое фото от Оракула*", "parse_mode": "Markdown"}
        response = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data=data,
            files=files
        )
        
        return response.json()

# ==================== ГОРОСКОП ====================
ZODIAC_SIGNS = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"
]

ZODIAC_EMOJIS = {
    "Овен": "♈️", "Телец": "♉️", "Близнецы": "♊️", "Рак": "♋️",
    "Лев": "♌️", "Дева": "♍️", "Весы": "♎️", "Скорпион": "♏️",
    "Стрелец": "♐️", "Козерог": "♑️", "Водолей": "♒️", "Рыбы": "♓️"
}

async def generate_daily_horoscope(sign: str) -> dict:
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        messages = [
            {"role": "system", "content": f"""Ты — Оракул. Напиши предсказание для знака {sign} на сегодня.
Формат ответа (строго):
ГОРОСКОП: 3-4 предложения, таинственно, но с добрым посылом.
КАРТА ДНЯ: название карты Таро (из старших арканов).
ОПИСАНИЕ КАРТЫ: 1 предложение, что эта карта значит для {sign} сегодня.
СОВЕТ ДНЯ: 1 короткое предложение, персональный совет для {sign}.

Никаких лишних слов, только факты."""},
            {"role": "user", "content": f"Сделай предсказание для {sign} на {today}"}
        ]
        response = await gigachat.chat(messages, temperature=0.8)

        horoscope_match = re.search(r"ГОРОСКОП:\s*(.+?)(?=КАРТА ДНЯ:|$)", response, re.DOTALL)
        card_match = re.search(r"КАРТА ДНЯ:\s*(.+)", response)
        desc_match = re.search(r"ОПИСАНИЕ КАРТЫ:\s*(.+)", response)
        advice_match = re.search(r"СОВЕТ ДНЯ:\s*(.+)", response)

        return {
            "success": True,
            "horoscope": horoscope_match.group(1).strip() if horoscope_match else "Туман будущего неясен...",
            "card": card_match.group(1).strip() if card_match else "Шут",
            "card_desc": desc_match.group(1).strip() if desc_match else "Новое начало",
            "advice": advice_match.group(1).strip() if advice_match else "Доверься своей интуиции."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/send-daily-horoscope")
async def send_daily_horoscope():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    channel_username = os.environ.get("TELEGRAM_CHANNEL_USERNAME")

    if not bot_token or not chat_id:
        return {"success": False, "error": "Не настроены TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID"}

    today = datetime.now().strftime("%d.%m.%Y")
    results = []
    sent_messages = []

    for sign in ZODIAC_SIGNS:
        horo_data = await generate_daily_horoscope(sign)
        if not horo_data["success"]:
            results.append({"sign": sign, "success": False, "error": horo_data.get("error")})
            continue

        emoji = ZODIAC_EMOJIS.get(sign, "🔮")
        message = f"""{emoji} *{sign}* {emoji}

📜 *Гороскоп на {today}:*
{horo_data['horoscope']}

🃏 *Карта дня:* {horo_data['card']}
{horo_data['card_desc']}

✨ *Совет дня:* {horo_data['advice']}

🔔 *Подпишись на ежедневные гороскопы — нажми 🔔 вверху чата!*

#{sign.lower()} #оракул #гороскоп #картадня"""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
            )
            result_data = response.json()
            if response.status_code == 200:
                message_id = result_data.get("result", {}).get("message_id")
                sent_messages.append({"sign": sign, "message_id": message_id})
            results.append({"sign": sign, "success": response.status_code == 200})
        await asyncio.sleep(0.5)

    if channel_username:
        navigation_message = f"""🔮 *Оракул — навигация по гороскопу* 🔮

📅 *Гороскоп на {today}*

Кликни на свой знак — перейдёшь к предсказанию:

"""
        for item in sent_messages:
            sign = item["sign"]
            emoji = ZODIAC_EMOJIS.get(sign, "🔮")
            link = f"https://t.me/{channel_username}/{item['message_id']}"
            navigation_message += f"• {emoji} [{sign}]({link})\n"

        navigation_message += """
📌 *Как пользоваться:*
1️⃣ Нажми на свой знак
2️⃣ Перейдёшь к свежему гороскопу
3️⃣ Сохрани ссылку, чтобы вернуться позже

✨ *Каждый день в 8:00 — свежий гороскоп от Оракула!*

#оракул #навигация #гороскоп2026

━━━━━━━━━━━━━━━━━━━━━
🧙 *Хочешь узнать больше?*

🎴 Гадание на картах Таро
❓ Магический шар (Да/Нет)
🧠 Чат с духом Оракула — ответы на любые вопросы

👉 *Открыть бота:* @MudroeTaroBot
━━━━━━━━━━━━━━━━━━━━━"""

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": navigation_message,
                    "parse_mode": "Markdown"
                }
            )

    return {"success": True, "results": results}

# ==================== ПЛАНИРОВЩИК ====================
scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

async def daily_horoscope_job():
    async with httpx.AsyncClient() as client:
        await client.post(f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:10000')}/api/send-daily-horoscope")

scheduler.add_job(daily_horoscope_job, "cron", hour=8, minute=0)
scheduler.add_job(midday_post_job, "cron", hour=12, minute=0)
scheduler.add_job(evening_post_job, "cron", hour=17, minute=0)

@app.on_event("startup")
async def start_scheduler():
    scheduler.start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
