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
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
            # Добавим базовую обработку ошибок
            if "choices" not in response.json():
                raise Exception(f"Неожиданный ответ от GigaChat: {response.text}")
            return response.json()["choices"][0]["message"]["content"]

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
        if hour == 12:
            style_prompt = "Напиши познавательный пост для соцсетей. 5-7 предложений. Используй эмодзи, разбивку на абзацы. Загадочный, но понятный стиль."
        else:
            style_prompt = "Напиши атмосферный, уютный пост для вечернего чтения. 5-7 предложений. Используй эмодзи, разбивку на абзацы. Как рассказчик у камина."
        
        text_messages = [
            {"role": "system", "content": f"Ты — Оракул, автор мистического Telegram-канала. Напиши пост.\n\n{style_prompt}\n\nЗаканчивай вопросом к читателю или призывом поделиться мнением."},
            {"role": "user", "content": f"Напиши пост на тему: {topic}"}
        ]
        post_text = await gigachat.chat(text_messages, temperature=0.8)
        
        # Генерация картинки временно отключена
        # image_base64 = await gigachat.generate_image(image_prompt)
        image_base64 = None
        
        return {
            "success": True,
            "text": post_text,
            "image_base64": image_base64,
            "topic": topic
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def send_post_to_channel(chat_id: str, bot_token: str, post_text: str, image_base64: str = None):
    async with httpx.AsyncClient() as client:
        if image_base64:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data={"chat_id": chat_id, "caption": post_text, "parse_mode": "Markdown"},
                files={"photo": image_base64}
            )
        else:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": post_text, "parse_mode": "Markdown"}
            )

async def midday_post_job():
    topic = random.choice(MIDDAY_TOPICS)
    result = await generate_post_with_image(topic, 12)
    if result["success"]:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        await send_post_to_channel(chat_id, bot_token, result["text"], result.get("image_base64"))
    else:
        print(f"Ошибка генерации дневного поста: {result.get('error')}")

async def evening_post_job():
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
    # ... (ваша существующая логика предсказаний)
    # Оставьте её без изменений
    return {"success": True, "prediction": "Тест"}

@app.post("/api/oracle/ask")
async def oracle_ask(request: OracleAskRequest):
    # ... (ваша существующая логика чата)
    return {"success": True, "answer": "Тест"}

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
    await midday_post_job()
    return {"status": "ok"}

@app.get("/api/test-evening")
async def test_evening():
    await evening_post_job()
    return {"status": "ok"}

# ==================== ПЛАНИРОВЩИК ====================
scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

async def daily_horoscope_job():
    # Заглушка, чтобы не сломать планировщик. Нужно будет добавить логику гороскопа.
    print("daily_horoscope_job executed")
    pass

scheduler.add_job(daily_horoscope_job, "cron", hour=8, minute=0)
scheduler.add_job(midday_post_job, "cron", hour=12, minute=0)
scheduler.add_job(evening_post_job, "cron", hour=17, minute=0)

@app.on_event("startup")
async def start_scheduler():
    scheduler.start()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
