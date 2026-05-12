
import time
import joblib
import pandas as pd
from collections import defaultdict
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from src.cassandra_client import CassandraClient

app = FastAPI()

# --- INITIALIZE BIG DATA STACK ---
print("--- [SERVING LAYER STARTUP] ---")
db = CassandraClient()
try:
    model = joblib.load("models/bot_model.pkl")
    print("Loaded ML Inference Engine.")
except:
    print("Warning: Model not found. Detection will be UA-only.")
    model = None

# Active WebSocket connections
connections = defaultdict(list)

def analyze_behavior(history):
    if len(history) < 2: return 0.0, 0.0
    intervals = [history[i] - history[i-1] for i in range(1, len(history))]
    avg_int = sum(intervals) / len(intervals)
    variance = sum((x - avg_int) ** 2 for x in intervals) / len(intervals)
    return avg_int, variance ** 0.5

@app.middleware("http")
async def protection_middleware(request: Request, call_next):
    ip = request.client.host
    ua = request.headers.get("user-agent", "")
    
    # 1. Fetch NoSQL Context
    history, _ = db.get_profile(ip)
    history.append(time.time())
    
    # 2. Extract Real-time Features
    req_count = len(history)
    avg_int, std_int = analyze_behavior(history)
    
    # 3. ML Inference
    risk_score = 0.0
    is_bot = False
    
    if model and req_count > 3:
        features = pd.DataFrame([{'req_count': req_count, 'avg_interval': avg_int, 'std_interval': std_int}])
        risk_score = float(model.predict_proba(features)[0][1])
        if risk_score > 0.65: is_bot = True
    
    # UA Fallback (Instant Block)
    if any(kw in ua.lower() for kw in ['bot', 'scraper', 'crawler']):
        risk_score = 1.0
        is_bot = True

    # 4. Update NoSQL Store
    db.save_profile(ip, history, risk_score)
    
    # 5. Live UI Update
    if ip in connections:
        for ws in connections[ip]:
            try:
                await ws.send_json({"status": "BOT" if is_bot else "HUMAN", "score": risk_score, "ip": ip})
            except: pass

    if is_bot and "/api/" in request.url.path:
        return HTMLResponse("429 Access Denied: Bot behavior detected.", status_code=429)
    
    return await call_next(request)

# --- ROUTES ---
@app.get("/")
async def index():
    with open("index.html") as f: return HTMLResponse(f.read())

@app.get("/api/data")
async def data(): return {"status": "success", "payload": "Sensitive Big Data Content"}

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    ip = websocket.client.host
    connections[ip].append(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        connections[ip].remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
