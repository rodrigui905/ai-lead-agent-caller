"""
AI Lead Agent — a 24/7 website assistant for local businesses.

Answers customer questions from a config, and captures every lead
(name + phone/email + what they need). One reusable template: to sell it
to a new client you ONLY edit config.json. Deploys to Railway in minutes.

Run locally:  uvicorn app:app --reload
"""

import json
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

# ---- config -------------------------------------------------------------
CONFIG = json.loads(Path("config.json").read_text(encoding="utf-8"))
LEADS_FILE = Path("leads.jsonl")
ADMIN_KEY = os.getenv("ADMIN_KEY", "changeme")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

app = FastAPI()

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def system_prompt() -> str:
    c = CONFIG
    faqs = "\n".join(f"- Q: {f['q']}\n  A: {f['a']}" for f in c.get("faqs", []))
    return f"""You are the friendly 24/7 virtual assistant for {c['business_name']}, a {c['business_type']} in {c.get('city','')}.

Your job:
1. Answer the visitor's questions warmly and briefly, using ONLY the info below.
2. Naturally collect their NAME, their PHONE or EMAIL, and WHAT they need, so the team can follow up. Ask for it once it feels natural — don't interrogate.
3. If you don't know something, say the team will follow up, and get their contact.
4. Keep replies short (1-3 sentences), human, no corporate fluff.

BUSINESS INFO:
- Services: {c.get('services','')}
- Pricing: {c.get('pricing','')}
- Hours: {c.get('hours','')}
- Service area: {c.get('service_area','')}
- Booking: {c.get('booking','')}

FAQs:
{faqs}

Tone: {c.get('tone','warm, helpful, local')}.
Always try to end by getting their name + best contact number."""


def save_lead(session_id: str, messages: list):
    """Save/update a lead if the conversation contains a phone or email."""
    text = " ".join(m["content"] for m in messages if m["role"] == "user")
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    if not (email or phone):
        return
    lead = {
        "session": session_id,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "email": email.group(0) if email else "",
        "phone": phone.group(0) if phone else "",
        "transcript": messages,
    }
    # append (simple; review in /admin)
    with LEADS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(lead, ensure_ascii=False) + "\n")


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE.replace("{{BIZ}}", CONFIG["business_name"]).replace(
        "{{GREETING}}", CONFIG.get("greeting", "Hi! How can I help you today?")
    )


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    history = body.get("messages", [])
    session_id = body.get("session", "anon")

    msgs = [{"role": "system", "content": system_prompt()}] + history
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=msgs, temperature=0.5, max_tokens=300
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        reply = "Sorry, I'm having a hiccup — leave your name and number and the team will reach out!"
        print("[chat error]", e)

    full = history + [{"role": "assistant", "content": reply}]
    save_lead(session_id, full)
    return JSONResponse({"reply": reply})


@app.get("/admin", response_class=HTMLResponse)
def admin(key: str = ""):
    if key != ADMIN_KEY:
        return HTMLResponse("<h3>Unauthorized — add ?key=YOUR_ADMIN_KEY</h3>", status_code=401)
    rows = ""
    if LEADS_FILE.exists():
        for line in LEADS_FILE.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            rows += f"<tr><td>{d['time']}</td><td>{d['phone']}</td><td>{d['email']}</td></tr>"
    return f"<h2>Leads — {CONFIG['business_name']}</h2><table border=1 cellpadding=8><tr><th>Time</th><th>Phone</th><th>Email</th></tr>{rows}</table>"


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{BIZ}} — Assistant</title><style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6f8;display:flex;flex-direction:column;height:100vh}
header{background:#111;color:#fff;padding:16px 20px;font-weight:600}
#chat{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:80%;padding:10px 14px;border-radius:14px;line-height:1.4;font-size:15px}
.bot{background:#fff;align-self:flex-start;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.user{background:#111;color:#fff;align-self:flex-end}
form{display:flex;gap:8px;padding:14px;background:#fff;border-top:1px solid #e3e7eb}
input{flex:1;padding:12px 14px;border:1px solid #d0d7de;border-radius:10px;font-size:15px}
button{background:#111;color:#fff;border:0;border-radius:10px;padding:0 18px;font-weight:600;cursor:pointer}
</style></head><body>
<header>{{BIZ}}</header>
<div id="chat"></div>
<form id="f"><input id="i" placeholder="Type your message..." autocomplete="off"><button>Send</button></form>
<script>
const chat=document.getElementById('chat'),inp=document.getElementById('i');
const session='s'+Date.now(); let history=[];
function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;chat.appendChild(d);chat.scrollTop=chat.scrollHeight}
add("{{GREETING}}",'bot');history.push({role:'assistant',content:"{{GREETING}}"});
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const t=inp.value.trim();if(!t)return;inp.value='';
 add(t,'user');history.push({role:'user',content:t});
 const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:history,session})});
 const d=await r.json();add(d.reply,'bot');history.push({role:'assistant',content:d.reply})};
</script></body></html>"""
