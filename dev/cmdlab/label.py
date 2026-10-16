"""A local page for labeling the queue (out/queue.jsonl): play each sample, click what it is. Labels go to
out/labels.json as they are clicked.  Run: python label.py [port]  then open http://127.0.0.1:<port>/"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import OUT, REC, commands  # noqa: E402

LABELS = OUT / "labels.json"

PAGE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>指令標註</title>
<style>
:root{--bg:#f6f6f4;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e2dd;--accent:#2b6cb0;--ok:#2f855a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--muted:#9a9a94;--card:#21211f;--line:#34342f;--accent:#63a4ff;--ok:#68d391}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,"Microsoft JhengHei",sans-serif;margin:0;padding:24px 16px}
main{max-width:760px;margin:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:16px}
.muted{color:var(--muted);font-size:13px}
.asr{font-size:22px;margin:8px 0}
button{font:inherit;padding:8px 14px;margin:4px 6px 4px 0;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.guess{border-color:var(--accent)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
kbd{font-size:11px;color:var(--muted);margin-left:4px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:8px 0 16px}
.bar>div{height:100%;background:var(--ok)}
select{font:inherit;padding:7px;border-radius:8px;background:var(--card);color:var(--fg);border:1px solid var(--line)}
audio{width:100%;margin:8px 0}
</style></head><body><main>
<h2>指令標註</h2>
<p class="muted">每段聽一下，選它其實是什麼。數字鍵選猜測的指令，T 一般文字、N 雜音／沒說話、S 聽不出來，空白鍵重播，← → 換段。點了就存。</p>
<div class="bar"><div id="prog"></div></div>
<div class="card" id="card"></div>
</main><script>
let Q=[],L={},C=[],i=0;
const $=s=>document.querySelector(s);
async function load(){const r=await fetch('/data');const d=await r.json();Q=d.queue;L=d.labels;C=d.commands;
 i=Q.findIndex(q=>!(q.wav in L));if(i<0)i=0;show();}
function show(){const q=Q[i];if(!q)return;const lab=L[q.wav];
 const done=Q.filter(q=>q.wav in L).length;$('#prog').style.width=(100*done/Q.length)+'%';
 let h=`<div class="muted">${i+1} / ${Q.length}　已標 ${done}　${q.era==='cont'?'連續聆聽':'按壓錄音'}　${q.dur.toFixed(1)}s</div>
 <div class="asr">${esc(q.raw1)||'（空）'}</div><div class="muted">app 當時：${esc(q.asr)||'（空）'}</div>
 <audio id="au" src="/wav/${encodeURIComponent(q.wav)}" controls autoplay></audio><div>`;
 q.guesses.forEach((g,k)=>h+=`<button class="guess ${lab===g?'on':''}" onclick="put('${g}')">${g}<kbd>${k+1}</kbd></button>`);
 h+=`</div><div><button class="${lab==='text'?'on':''}" onclick="put('text')">一般文字<kbd>T</kbd></button>
 <button class="${lab==='noise'?'on':''}" onclick="put('noise')">雜音／沒說話<kbd>N</kbd></button>
 <button class="${lab==='skip'?'on':''}" onclick="put('skip')">聽不出來<kbd>S</kbd></button>
 <select onchange="if(this.value)put(this.value)"><option value="">其他指令…</option>${C.map(c=>`<option ${lab===c?'selected':''}>${c}</option>`).join('')}</select></div>`;
 $('#card').innerHTML=h;}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function put(v){const q=Q[i];L[q.wav]=v;await fetch('/label',{method:'POST',body:JSON.stringify({wav:q.wav,label:v})});
 if(i<Q.length-1)i++;show();}
document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT')return;const q=Q[i];
 if(e.key>='1'&&e.key<='9'&&q.guesses[e.key-1])put(q.guesses[e.key-1]);
 else if(e.key==='t'||e.key==='T')put('text');else if(e.key==='n'||e.key==='N')put('noise');
 else if(e.key==='s'||e.key==='S')put('skip');
 else if(e.key===' '){e.preventDefault();const a=$('#au');a.currentTime=0;a.play();}
 else if(e.key==='ArrowRight'){if(i<Q.length-1)i++;show();}else if(e.key==='ArrowLeft'){if(i>0)i--;show();}});
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, kind: str):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/data":
            queue = [json.loads(l) for l in (OUT / "queue.jsonl").open(encoding="utf-8")]
            labels = json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {}
            self._send(json.dumps({"queue": queue, "labels": labels, "commands": list(commands())},
                                  ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path.startswith("/wav/"):
            name = unquote(self.path[5:])
            if ".." in name:
                self.send_error(404)
                return
            p = (OUT if name.startswith("pieces/") else REC) / name
            self._send(p.read_bytes(), "audio/wav")
        else:
            self.send_error(404)

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        labels = json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {}
        labels[d["wav"]] = d["label"]
        LABELS.write_text(json.dumps(labels, ensure_ascii=False, indent=0), encoding="utf-8")
        self._send(b"ok", "text/plain")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"http://127.0.0.1:{port}/")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
