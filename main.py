import functions_framework
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any

app = FastAPI(title="KakaoTalk Chatbot Skill Server")


# ── 카카오톡 스킬 요청/응답 모델 ──────────────────────────────

class SkillRequest(BaseModel):
    """카카오톡 스킬 요청 페이로드 (필요한 필드만 정의)"""
    intent: dict[str, Any] = {}
    userRequest: dict[str, Any] = {}
    bot: dict[str, Any] = {}
    action: dict[str, Any] = {}


def make_text_response(text: str) -> dict:
    """simpleText 응답을 만드는 헬퍼"""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": text}}
            ]
        }
    }


def make_card_response(title: str, description: str, buttons: list[dict] | None = None) -> dict:
    """basicCard 응답을 만드는 헬퍼"""
    card: dict[str, Any] = {"title": title, "description": description}
    if buttons:
        card["buttons"] = buttons
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {"basicCard": card}
            ]
        }
    }


# ── 엔드포인트 ────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/skill/hello")
async def skill_hello(req: SkillRequest):
    """기본 인사 스킬 — 사용자 발화를 그대로 되돌려 줍니다."""
    utterance = req.userRequest.get("utterance", "")
    return JSONResponse(make_text_response(f"안녕하세요! '{utterance}' 라고 하셨군요."))


@app.post("/skill/echo")
async def skill_echo(req: SkillRequest):
    """에코 스킬 — 사용자 발화를 그대로 반환합니다."""
    utterance = req.userRequest.get("utterance", "")
    return JSONResponse(make_text_response(utterance))


@app.post("/skill/info")
async def skill_info(req: SkillRequest):
    """카드형 정보 스킬 예시"""
    return JSONResponse(
        make_card_response(
            title="챗봇 안내",
            description="이 챗봇은 FastAPI + GCF로 동작합니다.",
            buttons=[
                {"label": "자세히 보기", "action": "webLink", "webLinkUrl": "https://i.kakao.com"},
            ],
        )
    )


# ── GCF 진입점 ────────────────────────────────────────────────
# Cloud Functions Gen2는 내부적으로 Cloud Run이므로
# ASGI 앱을 직접 서빙할 수 있습니다.
# functions-framework가 이 함수를 호출하면
# FastAPI(ASGI)를 WSGI로 변환하여 요청을 처리합니다.

from mangum import Mangum  # noqa: E402 — ASGI→WSGI 어댑터 (GCF/Lambda 겸용)

_asgi_handler = Mangum(app, lifespan="off")


@functions_framework.http
def entry(request):
    """GCF HTTP 함수 진입점.

    functions-framework가 Flask request 객체를 넘겨주므로
    이를 ASGI 이벤트로 변환하여 FastAPI에 전달합니다.
    """
    from werkzeug.datastructures import Headers

    # Flask(Werkzeug) request → 최소 ASGI scope 구성
    headers = dict(request.headers)
    scope = {
        "type": "http",
        "method": request.method,
        "path": request.path,
        "query_string": (request.query_string or b""),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "body": request.get_data(),
    }

    import asyncio
    from mangum.types import Response as MangumResponse

    # Mangum을 직접 호출하는 대신, ASGI 앱을 동기적으로 실행
    loop = asyncio.new_event_loop()
    response_started = False
    status_code = 200
    response_headers: list[tuple[bytes, bytes]] = []
    body_parts: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": request.get_data()}

    async def send(message):
        nonlocal response_started, status_code, response_headers
        if message["type"] == "http.response.start":
            response_started = True
            status_code = message["status"]
            response_headers = message.get("headers", [])
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    asgi_scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": request.method,
        "path": request.path,
        "query_string": request.query_string or b"",
        "root_path": "",
        "scheme": request.scheme,
        "server": (request.host.split(":")[0], int(request.host.split(":")[1]) if ":" in request.host else 443),
        "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers],
    }

    loop.run_until_complete(app(asgi_scope, receive, send))
    loop.close()

    resp_headers = {k.decode(): v.decode() for k, v in response_headers}
    from flask import make_response as flask_make_response
    resp = flask_make_response(b"".join(body_parts), status_code)
    for k, v in resp_headers.items():
        resp.headers[k] = v
    return resp
