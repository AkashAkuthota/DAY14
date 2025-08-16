from fastapi import FastAPI, File, UploadFile, Request, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
import logging
from services.stt_service import STTService
from services.tts_service import TTSService
from services.llm_service import LLMService

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# Config / services
MURF_API_KEY = os.getenv("MURF_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

stt_service = STTService(ASSEMBLYAI_API_KEY)
tts_service = TTSService(MURF_API_KEY)
llm_service = LLMService(GEMINI_API_KEY)

FALLBACK_TEXT = "I'm having trouble connecting right now."
CHUNK_SIZE = 3000

class ChatRequest(BaseModel):
    session_id: str

class ChatResponse(BaseModel):
    transcription: str
    llm_response: str
    audioFiles: list[str]
    chat_history: list[dict]
    error: dict | None = None

chat_sessions = {}

def try_fallback_tts():
    audio_url = tts_service.synthesize(FALLBACK_TEXT)
    return [audio_url] if audio_url else []

@app.post("/agent/chat/{session_id}", response_model=ChatResponse)
async def agent_chat(session_id: str, file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise ValueError("No audio bytes received")
    except Exception as e:
        logger.error(f"Input error: {e}")
        return ChatResponse(transcription="", llm_response=FALLBACK_TEXT, audioFiles=try_fallback_tts(), chat_history=chat_sessions.get(session_id, []), error={"stage": "input", "message": str(e)})

    user_text = stt_service.transcribe(audio_bytes)
    if not user_text.strip():
        logger.error("Empty transcription.")
        return ChatResponse(transcription="", llm_response=FALLBACK_TEXT, audioFiles=try_fallback_tts(), chat_history=chat_sessions.get(session_id, []), error={"stage": "stt", "message": "Empty transcription"})

    session = chat_sessions.setdefault(session_id, [])
    session.append({"role": "user", "content": user_text})
    dialog = "\n".join(("User: " if m["role"] == "user" else "AI: ") + m["content"] for m in session) + "\nAI:"
    llm_text = llm_service.get_response(dialog)
    if not llm_text.strip():
        session.append({"role": "assistant", "content": FALLBACK_TEXT})
        logger.error("Empty LLM output.")
        return ChatResponse(transcription=user_text, llm_response=FALLBACK_TEXT, audioFiles=try_fallback_tts(), chat_history=session, error={"stage": "llm", "message": "Empty LLM output"})

    session.append({"role": "assistant", "content": llm_text})

    # TTS
    audio_urls = []
    for i in range(0, len(llm_text), CHUNK_SIZE):
        chunk = llm_text[i:i + CHUNK_SIZE]
        audio_url = tts_service.synthesize(chunk)
        if audio_url:
            audio_urls.append(audio_url)
    if not audio_urls:
        audio_urls = try_fallback_tts()

    return ChatResponse(
        transcription=user_text,
        llm_response=llm_text,
        audioFiles=audio_urls,
        chat_history=session
    )

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
<title>🧠 Conversational Agent</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  /* Background with subtle floating particles animation */
  body {
    margin: 0;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0a0a0a; /* blackish background */
    position: relative;
    font-family: 'Segoe UI', Roboto, sans-serif;
    color: #f5f7ff;
  }
  /* Floating Bubble Particles */
  .bg-particles {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    pointer-events: none;
    z-index: 0;
  }
  .bg-particles span {
    position: absolute;
    display: block;
    width: 12px;
    height: 12px;
    background: radial-gradient(circle, #7b5ae5 40%, transparent 70%);
    border-radius: 50%;
    opacity: 0.2;
    animation: floatUp 20s linear infinite;
  }
  @keyframes floatUp {
    0% {
      transform: translateY(120vh) translateX(0) scale(1);
      opacity: 0.2;
    }
    50% {
      opacity: 0.4;
    }
    100% {
      transform: translateY(-20vh) translateX(30vw) scale(1.3);
      opacity: 0;
    }
  }

  /* Container Card */
  .glass-card {
    position: relative;
    z-index: 10;
    width: 75vw;
    max-width: 900px;
    height: 75vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 8px 32px 0 rgba(34,41,62,0.24);
    border-radius: 24px;
    background: rgba(33,35,57,0.97);
    border: 1.5px solid rgba(110,113,190,0.12);
    padding: 0;
    overflow: hidden;
  }
  .header {
    padding: 22px 24px 10px;
    background: linear-gradient(90deg, #3f68f3 40%, #632bd959 100%);
    border-radius: 24px 24px 0 0;
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .badge {
    font-size: 19px;
    font-weight: 600;
    color: #f5f7ff;
    letter-spacing: .04em;
  }
  .card-body {
    padding: 32px 38px 28px;
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    position: relative;
    padding-bottom: 100px; /* space for sticky controls */
  }
  .section-title {
    font-size: 13px;
    letter-spacing: .06em;
    color: #d2e0ff;
    margin-bottom: 12px;
  }
  #chat {
    height: 42vh;            /* fixed, never expands past this */
    min-height: 220px;       /* ensures small screens aren't too tight */
    background: rgba(20,24,46,0.92);
    border-radius: 15px;
    border: 1px solid #192153;
    padding: 16px;
    overflow-y: auto;
    margin-bottom: 20px;
    font-size: 16px;
  }
  .msg {
    display: flex;
    gap: 12px;
    margin-bottom: 9px;
  }
  .msg .avatar {
    width: 38px;
    height: 38px;
    border-radius: 16px;
    background-size: cover;
    background-position: center;
    flex: 0 0 38px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  }
  .msg.ai .avatar {
    background-image: url('https://cdn-icons-png.flaticon.com/512/4712/4712023.png');
  }
  .msg.user .avatar {
    background-image: url('https://cdn-icons-png.flaticon.com/512/147/147144.png');
  }
  .bubble {
    max-width: 70%;
    padding: 14px 18px;
    background: linear-gradient(120deg,#262e54 70%,#32395a 110%);
    color: #e5ebff;
    border-radius: 18px;
    border: 1px solid #3c436d;
    font-size: 16px;
    transition: .18s;
  }
  .msg.user .bubble {
    background: linear-gradient(120deg,#415de6 62%,#7b5ae5 100%);
    color: #fff;
    border-radius: 18px 18px 6px 20px;
  }
  .msg.ai .bubble {
    background: linear-gradient(120deg,#232753 70%,#423497 140%);
    color: #e5eaff;
    border-radius: 18px 18px 20px 6px;
  }
  .status {
    position: fixed;
    bottom: 150px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(33,35,57,0.97);
    width: 90vw;
    max-width: 900px;
    padding: 10px 38px;
    box-sizing: border-box;
    z-index: 20;
    backdrop-filter: blur(8px);
    border-top: 1px solid rgba(110,113,190,0.12);
    font-size: 16px;
    min-height: 24px;
    color: #63ffde;
    transition: color 0.5s ease, opacity 0.5s ease;
  }
  .status.ready {
    animation: pulseReady 3s ease infinite;
  }
  .status.processing {
    color: #ffab40;
    animation: pulseProcessing 1.5s ease infinite;
  }
  .status.replying {
    color: #7b5ae5;
    animation: pulseReply 2s ease infinite;
  }
  @keyframes pulseReady {
    0%, 100% {opacity: 1;}
    50% {opacity: 0.6;}
  }
  @keyframes pulseProcessing {
    0%, 100% {opacity: 1;}
    50% {opacity: 0.3;}
  }
  @keyframes pulseReply {
    0%, 100% {opacity: 1;}
    50% {opacity: 0.5;}
  }
  .controls {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(33,35,57,0.97);
    width: 90vw;
    max-width: 900px;
    padding: 10px 38px;
    box-sizing: border-box;
    z-index: 20;
    backdrop-filter: blur(8px);
    border-top: 1px solid rgba(110,113,190,0.12);
    display: flex;
    justify-content: center;
    margin-bottom: 0;
  }
  #recordBtn {
    font-size: 20px;
    font-weight: 700;
    padding: 20px 64px;
    border-radius: 22px;
    border: none;
    outline: none;
    cursor: pointer;
    background: linear-gradient(90deg,#5b88fe 80%,#7b5ae5);
    color: #fff;
    box-shadow: 0 2px 16px rgba(50,64,227,0.13), 0 0 60px 2px #819cff44;
    transition: .22s cubic-bezier(.5,2,.5,.6);
  }
  #recordBtn.recording {
    background: linear-gradient(90deg,#7b5ae5 14%,#e34f7a);
    animation: glowpulse 1.18s infinite;
    box-shadow: 0 0 42px 12px #7b5ae563, 0 0 4px 0 #d34f9b66;
  }
  @keyframes glowpulse {
    0% { box-shadow: 0 0 15px 6px #e34f7a99; }
    50% { box-shadow: 0 0 30px 16px #7b5ae5ff; }
    100% { box-shadow: 0 0 15px 6px #e34f7a99; }
  }
  .hint {
    font-size: 13px;
    color: #aad3e3;
    text-align: center;
    margin-top: 8px;
  }

  @media (max-width: 768px) {
    .glass-card {
      max-width: 100vw;
      height: 90vh;
    }
    .controls, .status {
      width: 95vw;
    }
    #recordBtn {
      padding: 15px 40px;
      font-size: 18px;
    }
  }
</style>
</head>
<body>
  <div class="bg-particles" aria-hidden="true"></div>
  <div class="glass-card" role="main" aria-label="Conversational agent UI">
    <div class="header">
      <div class="badge">Conversational Agent 🤖</div>
    </div>
    <div class="card-body">
      <div class="section-title">Conversation</div>
      <div id="chat" role="log" aria-live="polite" aria-atomic="false"></div>
      <div id="status" class="status ready" aria-live="polite">Ready to record</div>
      <div class="controls">
        <button id="recordBtn" aria-pressed="false" aria-label="Start recording"><span id="micIcon">🎙</span> Start Recording</button>
      </div>
      <div class="hint">Tap to record your message, then listen to the AI reply.</div>
      <audio id="playback" style="display:none"></audio>
    </div>
  </div>
<script>
  const particleContainer = document.querySelector('.bg-particles');
  const particleCount = 30; // Number of floating particles
  
  for (let i = 0; i < particleCount; i++) {
    const particle = document.createElement('span');
    particle.style.left = Math.random() * 100 + 'vw';
    particle.style.top = Math.random() * 120 + 'vh';
    particle.style.width = particle.style.height = (6 + Math.random() * 10) + 'px';
    particle.style.animationDuration = (15 + Math.random() * 10) + 's';
    particle.style.animationDelay = (Math.random() * -20) + 's';
    particleContainer.appendChild(particle);
  }
  
  let recorder, chunks = [], isRecording = false,
      audioContext, analyser, dataArray, rafId, source;

  const chat = document.getElementById("chat");
  const statusEl = document.getElementById("status");
  const recordBtn = document.getElementById("recordBtn");
  const micIcon = document.getElementById("micIcon");
  const playback = document.getElementById("playback");

  function addMessage(role, txt) {
    const w = document.createElement("div");
    w.className = "msg " + (role === "user" ? "user" : "ai");
    const av = document.createElement("div");
    av.className = "avatar";
    const bub = document.createElement("div");
    bub.className = "bubble";
    bub.innerText = txt;
    if (role === "user") {
      w.appendChild(bub);
      w.appendChild(av);
    } else {
      w.appendChild(av);
      w.appendChild(bub);
    }
    chat.appendChild(w);
    chat.scrollTop = chat.scrollHeight;
  }

  function setStatus(txt, emoji = "") {
    statusEl.textContent = (emoji ? emoji + " " : "") + txt;
    statusEl.classList.remove("ready", "processing", "replying");
    if (txt.toLowerCase().includes("ready")) {
      statusEl.classList.add("ready");
    } else if (txt.toLowerCase().includes("processing") || txt.toLowerCase().includes("denied")) {
      statusEl.classList.add("processing");
    } else if (txt.toLowerCase().includes("playing") || txt.toLowerCase().includes("reply")) {
      statusEl.classList.add("replying");
    }
  }

  recordBtn.addEventListener("click", () => {
    if (!isRecording) startRecording();
    else stopRecording();
  });

  function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = e => {
        if (e.data?.size) chunks.push(e.data);
      };
      recorder.onstop = onStop;
      recorder.start();

      audioContext = new AudioContext();
      analyser = audioContext.createAnalyser();
      source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);
      analyser.fftSize = 512;
      dataArray = new Uint8Array(analyser.frequencyBinCount);
      animateMicGlow();

      isRecording = true;
      recordBtn.classList.add("recording");
      recordBtn.setAttribute("aria-pressed", "true");
      micIcon.textContent = "⏹";
      recordBtn.textContent = " Stop Recording";
      recordBtn.prepend(micIcon);
      setStatus("Recording…", "🎙");
    }).catch(() => setStatus("Microphone denied", "❌"));
  }

  function stopRecording() {
    if (recorder) recorder.stop();
    isRecording = false;
    recordBtn.classList.remove("recording");
    recordBtn.setAttribute("aria-pressed", "false");
    micIcon.textContent = "🎙";
    recordBtn.textContent = " Start Recording";
    recordBtn.prepend(micIcon);
    cancelAnimationFrame(rafId);
    if (audioContext) audioContext.close();
    setStatus("Processing…", "⏳");
  }

  function animateMicGlow() {
    analyser.getByteFrequencyData(dataArray);
    let volume = dataArray.reduce((a, b) => a + b) / dataArray.length;
    let intensity = Math.min(volume / 255, 1);
    recordBtn.style.boxShadow = `0 0 ${10 + intensity * 34}px ${
      4 + intensity * 8
    }px rgba(123,90,229,${0.29 + intensity / 1.8})`;
    rafId = requestAnimationFrame(animateMicGlow);
  }

  async function onStop() {
    const blob = new Blob(chunks, { type: "audio/webm;codecs=opus" });
    const form = new FormData();
    form.append("file", blob, "query.webm");
    try {
      const res = await fetch("/agent/chat/session1", { method: "POST", body: form });
      const data = await res.json();

      if (data?.transcription) addMessage("user", data.transcription);
      if (data?.llm_response) addMessage("ai", data.llm_response);

      if (Array.isArray(data?.audioFiles) && data.audioFiles.length) {
        playback.src = data.audioFiles[0];
        playback.play();
        setStatus("Audio reply playing…", "✅");
      } else {
        setStatus("No audio returned", "⚠️");
      }
      if (data?.error?.stage) {
        setStatus(`Error: ${data.error.stage}`, "⚠️");
      }
    } catch (error) {
      setStatus("Server error: " + error.message, "❌");
    } finally {
      chunks = [];
    }
  }

  playback.addEventListener("ended", () => {
    setStatus("Ready to record", "🎙");
  });
</script>
</body>
</html>
""")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Echo: {data}")