# Baloot — Render.com Deployment

This fork is ready for **Render.com**. It exposes HTTP `GET /healthz` for health checks and binds to `PORT` on `0.0.0.0`.

## One‑Click (with render.yaml)
1. Push this repo to GitHub.
2. In Render → **New +** → **Blueprint** → point to your repo.
3. Render will detect `render.yaml` and create a **Web Service**.
4. First deploy installs `requirements.txt` and runs `python server.py`.

### Service URL
After deploy, your app lives at:
```
https://<your-service-name>.onrender.com
```
WebSocket URL (from browsers/clients):
```
wss://<your-service-name>.onrender.com
```

## Local Dev
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
# ws://127.0.0.1:8765
```

## Client Config
Set environment variable for remote testing:
```bash
# Example:
export SERVER_URL=wss://<your-service-name>.onrender.com
python client.py
```
Or edit `client.py` and set `SERVER` directly.

## Why the Extra HTTP Endpoint?
Render’s **health checks** hit an HTTP path. Since we’re a WebSocket server, we reply `200 OK` at `/healthz` (and `/`) using `process_request` in `websockets.serve`. This keeps the service marked healthy.

## Notes
- WebSockets are supported on Render **Web Services** by default.
- Keep the free plan warm by occasional traffic (free instances may spin down).
- Add auth/rate limiting before exposing publicly.
- For a custom domain, add it in Render and switch your client URL accordingly.
