import io
import os
import re

import edge_tts
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

# Sadece Türkçe sesler
VOICES = {
    "ahmet": "tr-TR-AhmetNeural",  # erkek
    "emel": "tr-TR-EmelNeural",    # kadın
}

API_KEY = os.environ.get("API_KEY")  # boşsa anahtar kontrolü yapılmaz
MAX_CHARS = 3000

RATE_RE = re.compile(r"^[+-]\d{1,3}%$")
VOLUME_RE = re.compile(r"^[+-]\d{1,3}%$")
PITCH_RE = re.compile(r"^[+-]\d{1,3}Hz$")

app = FastAPI(title="Türkçe TTS API")

# Tarayıcıdaki araçların (başka bir adresten) bu API'yi çağırabilmesi için.
# allow_headers=["*"] -> x-api-key başlığına izin verir (preflight isteği için şart).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHARS)
    voice: str = "ahmet"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"


def check_key(x_api_key):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Geçersiz API anahtarı")


async def synthesize(req: TTSRequest) -> bytes:
    voice = VOICES.get(req.voice.lower())
    if not voice:
        raise HTTPException(status_code=400, detail=f"voice şunlardan biri olmalı: {list(VOICES)}")
    if not RATE_RE.match(req.rate):
        raise HTTPException(status_code=400, detail="rate biçimi: +10% veya -10%")
    if not VOLUME_RE.match(req.volume):
        raise HTTPException(status_code=400, detail="volume biçimi: +10% veya -10%")
    if not PITCH_RE.match(req.pitch):
        raise HTTPException(status_code=400, detail="pitch biçimi: +5Hz veya -5Hz")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text boş olamaz")

    buf = io.BytesIO()
    try:
        comm = edge_tts.Communicate(
            req.text, voice, rate=req.rate, volume=req.volume, pitch=req.pitch
        )
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ses servisi hatası: {e}")
    data = buf.getvalue()
    if not data:
        raise HTTPException(status_code=502, detail="Ses servisi boş yanıt döndürdü")
    return data


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/voices")
def voices():
    return {k: v for k, v in VOICES.items()}


@app.get("/tts")
async def tts_get(
    text: str,
    voice: str = "ahmet",
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
    x_api_key: str = Header(default=None),
):
    check_key(x_api_key)
    req = TTSRequest(text=text, voice=voice, rate=rate, volume=volume, pitch=pitch)
    data = await synthesize(req)
    return StreamingResponse(io.BytesIO(data), media_type="audio/mpeg")


@app.post("/tts")
async def tts_post(req: TTSRequest, x_api_key: str = Header(default=None)):
    check_key(x_api_key)
    data = await synthesize(req)
    return StreamingResponse(io.BytesIO(data), media_type="audio/mpeg")


PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Türkçe TTS</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem}
  textarea,select,input,button{font:inherit;width:100%;box-sizing:border-box;margin:.35rem 0;padding:.6rem}
  textarea{min-height:140px}
  .row{display:flex;gap:.5rem}
  button{cursor:pointer}
  #msg{color:#b00020;min-height:1.4em}
</style></head><body>
<h2>Türkçe TTS</h2>
<textarea id="text" placeholder="Metni yazın...">Merhaba, bu bir ses denemesidir.</textarea>
<div class="row">
  <select id="voice"><option value="ahmet">Ahmet (erkek)</option><option value="emel">Emel (kadın)</option></select>
  <input id="rate" value="+0%" title="Hız (ör. +10% / -10%)">
  <input id="pitch" value="+0Hz" title="Perde (ör. -5Hz)">
</div>
<input id="key" type="password" placeholder="API anahtarı (varsa)">
<button id="go">Seslendir</button>
<p id="msg"></p>
<audio id="player" controls style="width:100%"></audio>
<script>
document.getElementById('go').onclick = async () => {
  const msg = document.getElementById('msg'); msg.textContent = '';
  const headers = {'Content-Type':'application/json'};
  const k = document.getElementById('key').value; if (k) headers['x-api-key'] = k;
  try {
    const r = await fetch('/tts', {method:'POST', headers, body: JSON.stringify({
      text: document.getElementById('text').value,
      voice: document.getElementById('voice').value,
      rate: document.getElementById('rate').value,
      pitch: document.getElementById('pitch').value
    })});
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || r.status); }
    const url = URL.createObjectURL(await r.blob());
    const p = document.getElementById('player'); p.src = url; p.play();
  } catch (e) { msg.textContent = 'Hata: ' + e.message; }
};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
