"""
LLM Gateway — OpenAI 兼容代理

把 DeepSeek 包装成标准 OpenAI API，方便：
  1. 学习 Docker 部署（Linux 容器可运行）
  2. Windows Agent 通过 HTTP 调用（可选）

Windows Agent 配置（.env）:
  DEEPSEEK_BASE_URL=http://localhost:8000
  DEEPSEEK_API_KEY=sk-xxxx   # 仍需要，网关转发时使用
"""

import os
import logging
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional
from openai import OpenAI

app = FastAPI(title="WeChat AI LLM Gateway", version="1.0.0")

UPSTREAM_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
UPSTREAM_KEY = os.getenv("DEEPSEEK_API_KEY", "")
UPSTREAM_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
GATEWAY_TOKEN = os.getenv("LLM_GATEWAY_TOKEN", "")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not UPSTREAM_KEY:
            raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY not set")
        _client = OpenAI(api_key=UPSTREAM_KEY, base_url=UPSTREAM_BASE)
    return _client


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    # 为兼容 OpenAI 请求格式保留该字段；服务端始终强制使用 UPSTREAM_MODEL。
    model: str = Field(default=UPSTREAM_MODEL, max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    max_tokens: Optional[int] = Field(default=1024, ge=1, le=2048)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)


def require_gateway_token(authorization: str | None = Header(default=None)):
    if not GATEWAY_TOKEN:
        raise HTTPException(status_code=503, detail="gateway token not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, GATEWAY_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health():
    return {"status": "ok", "auth_configured": bool(GATEWAY_TOKEN)}


@app.post("/v1/chat/completions", dependencies=[Depends(require_gateway_token)])
def chat_completions(req: ChatRequest):
    try:
        client = get_client()
        response = client.chat.completions.create(
            model=UPSTREAM_MODEL,
            messages=[m.model_dump() for m in req.messages],
            max_tokens=req.max_tokens or 1024,
            temperature=req.temperature or 0.7,
        )
        choice = response.choices[0]
        return {
            "id": response.id,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": choice.message.role,
                    "content": choice.message.content,
                },
                "finish_reason": choice.finish_reason,
            }],
            "model": response.model,
        }
    except Exception as e:
        logging.exception("upstream LLM request failed")
        raise HTTPException(status_code=502, detail="upstream request failed") from e
