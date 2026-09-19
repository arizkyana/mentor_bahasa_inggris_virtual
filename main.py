from loguru import logger
from fastapi import FastAPI, Request, Response, status

app = FastAPI()


# 1. contoh endpoint
@app.get("/")
async def root():
    return {
        "status": "ok",
    }  # json


# 2. HTTP Method Post dan Get
@app.get("/get")
async def endpoint_get():
    return {"http_method": "get"}


# test pake terminal aja
# curl -X localhost:port/post
@app.post("/post")
async def endpoint_post():
    return {"http_method": "post"}


# 3. membuat endpoint health-check dan webhook
@app.get("/health-check")
async def health_check():
    return {"status": "ok", "message": "telegram bot is active"}


# 4. bahasa dulu gambaran teknis nya di excalidraw
@app.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request):
    req_body = await request.json()
    logger.debug(req_body)
    return Response(status_code=status.HTTP_200_OK)
