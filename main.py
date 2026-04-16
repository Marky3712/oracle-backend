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

# ==================== ГОРОСКОП ПО ЗНАКАМ ЗОДИАКА ====================
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

    # ==================== НАВИГАЦИОННОЕ СООБЩЕНИЕ С ССЫЛКАМИ ====================
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

# ==================== ПЛАНИРОВЩИК ЕЖЕДНЕВНОЙ РАССЫЛКИ ====================
scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

async def daily_horoscope_job():
    async with httpx.AsyncClient() as client:
        await client.post(f"{os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:10000')}/api/send-daily-horoscope")

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(daily_horoscope_job, "cron", hour=8, minute=0)
    scheduler.start()

@app.post("/api/test-horoscope")
async def test_horoscope():
    test_result = await generate_daily_horoscope("Козерог")
    return test_result

# ==================== ТЕСТОВЫЙ ЭНДПОИНТ ====================
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

# ==================== ДЕБАГ-ЭНДПОИНТ ====================
@app.post("/api/oracle/debug")
async def oracle_debug(request: OracleAskRequest):
    import traceback
    try:
        messages = [
            {"role": "system", "content": "Ты — Оракул. Отвечай кратко, максимум 2 предложения."},
            {"role": "user", "content": request.question}
        ]
        answer = await gigachat.chat(messages, temperature=0.8)
        return {"success": True, "answer": answer}
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
