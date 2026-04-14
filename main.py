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
from datetime import datetime, timedelta

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
        if self._token and self._token_expires > datetime.now():
            return self._token
        
        # Формируем Basic Auth ключ
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
            self._token_expires = datetime.now() + timedelta(seconds=result["expires_in"])
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

# ==================== ЭНДПОИНТЫ ====================
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
    """Всевидящий Оракул — отвечает на любые вопросы"""
    try:
        messages = [
            {"role": "system", "content": """Ты — Всевидящий Оракул, древний дух, хранитель тайн и судеб.
Твои ответы должны быть:
1. Таинственными и мудрыми, в готическом стиле
2. Давать глубокий, философский ответ
3. Использовать метафоры (звёзды, тени, пламя, судьба, туман)
4. Заканчиваться напутствием или загадкой
5. Отвечать на русском языке

Никогда не пиши, что ты ИИ. Ты — Оракул."""},
            {"role": "user", "content": request.question}
        ]
        answer = await gigachat.chat(messages, temperature=0.8)
        return {"success": True, "answer": answer}
    except Exception as e:
        return {"success": False, "error": str(e), "answer": "Оракул временно молчит. Попробуй позже."}

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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
