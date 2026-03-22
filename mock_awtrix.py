from fastapi import FastAPI, Request
import uvicorn
from datetime import datetime

app = FastAPI()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str, request: Request):
    body = await request.body()
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] {request.method} /{path}")
    if body:
        print(f"  Body: {body.decode()}")
    if path == "api/stats":
        return {"uptime": 12345, "temp": 24.5, "hum": 61.0, "lux": 450, "bri": 180}
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7777)