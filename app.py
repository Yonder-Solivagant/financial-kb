"""
财报知识库问答页面（作业3 方向 A 的交付物之一：带出处的问答页）。

运行：uvicorn app:app --host 127.0.0.1 --port 8010
设计令牌见项目 .context/DESIGN.md（Google Labs 体系）。
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from config import INDEX_FILE
from qa import ask

app = FastAPI(title="财报知识库")

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>白酒行业财报知识库 · 问答</title>
<style>
  :root{
    --bg:#FAFAF8; --ink:#1A1A1A; --accent:#1A73E8; --green:#188038; --amber:#F9AB00;
    --muted:#5F6368; --line:#E8EAED; --card:#FFFFFF;
    --sp1:4px; --sp2:8px; --sp3:16px; --sp4:24px; --sp5:40px;
    --radius:8px; --shadow:0 1px 3px rgba(0,0,0,.1);
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.7 "Noto Sans SC","Source Han Sans SC","Microsoft YaHei",Roboto,Arial,sans-serif;}
  .wrap{max-width:1080px;margin:0 auto;padding:var(--sp5) var(--sp4) var(--sp5)}
  header{display:flex;align-items:baseline;gap:var(--sp3);flex-wrap:wrap;margin-bottom:var(--sp2)}
  h1{font-size:28px;margin:0;letter-spacing:.2px}
  .sub{color:var(--muted);font-size:14px}
  .stats{display:flex;gap:var(--sp4);margin:var(--sp3) 0 var(--sp4);flex-wrap:wrap}
  .stat{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:var(--sp2) var(--sp3)}
  .stat b{font-size:20px;display:block;line-height:1.3}
  .stat span{color:var(--muted);font-size:12px}
  .card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:var(--sp4);margin-bottom:var(--sp4)}
  textarea{width:100%;min-height:76px;padding:var(--sp3);border:1px solid var(--line);border-radius:var(--radius);
           font:14px/1.7 inherit;resize:vertical;background:#fff;color:var(--ink)}
  textarea:focus{outline:2px solid rgba(26,115,232,.35);outline-offset:1px}
  .row{display:flex;gap:var(--sp2);align-items:center;margin-top:var(--sp3);flex-wrap:wrap}
  button{background:var(--accent);color:#fff;border:0;border-radius:var(--radius);padding:10px 20px;
         font:14px inherit;cursor:pointer}
  button:hover{background:#1765cc}
  button.ghost{background:#F1F3F4;color:var(--ink)}
  button.ghost:hover{background:#E8EAED}
  .chips{display:flex;gap:var(--sp2);flex-wrap:wrap;margin-top:var(--sp3)}
  .chip{border:1px solid var(--line);background:#F8F9FA;border-radius:16px;padding:6px 14px;font-size:13px;
        cursor:pointer;color:#3C4043}
  .chip:hover{background:#F1F3F4;border-color:#DADCE0}
  .chip.cross{border-color:rgba(24,128,56,.35);background:#F2F8F4;color:var(--green)}
  h2{font-size:16px;margin:0 0 var(--sp2)}
  .ans{white-space:pre-wrap;line-height:1.9;font-size:14px}
  .cite{display:inline-block;background:#E8F0FE;color:var(--accent);border-radius:4px;
        padding:0 6px;font-size:12px;margin:0 2px}
  .src{border-top:1px solid var(--line);margin-top:var(--sp3);padding-top:var(--sp3)}
  .src .one{padding:var(--sp2) 0;border-bottom:1px dashed var(--line)}
  .src .one:last-child{border-bottom:0}
  .src .meta{font-size:12px;color:var(--muted);margin-bottom:2px}
  .src .meta b{color:var(--ink);font-weight:600}
  .src pre{white-space:pre-wrap;word-break:break-all;font:12px/1.6 "Roboto Mono",Consolas,monospace;
           color:#3C4043;margin:0;max-height:160px;overflow:auto}
  .tag{display:inline-block;font-size:11px;border-radius:4px;padding:1px 6px;margin-left:6px}
  .tag.tbl{background:#FEF7E0;color:#B06000}
  .tag.txt{background:#F1F3F4;color:#5F6368}
  .hint{color:var(--muted);font-size:12px;margin-top:var(--sp2)}
  .loading{color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>白酒行业财报知识库</h1>
    <span class="sub">10 家公司 · 2024/2025 年报 · BM25 + 向量双索引 · 答案带出处可回原 PDF 核对</span>
  </header>
  <div class="stats">
    <div class="stat"><b id="s-company">10</b><span>公司</span></div>
    <div class="stat"><b id="s-report">20</b><span>份年报 PDF</span></div>
    <div class="stat"><b id="s-page">—</b><span>总页数</span></div>
    <div class="stat"><b id="s-chunk">—</b><span>知识块（切块）</span></div>
    <div class="stat"><b>BM25 + 向量</b><span>RRF 融合召回</span></div>
  </div>

  <div class="card">
    <h2>提问</h2>
    <textarea id="q" placeholder="例如：贵州茅台 2025 年营业收入是多少？"></textarea>
    <div class="row">
      <button onclick="go()">提问</button>
      <button class="ghost" onclick="document.getElementById('q').value='';document.getElementById('ans').innerHTML='—'">清空</button>
      <span class="hint">绿色标签为跨公司题：会自动按公司分层召回，避免「只召回到一家」</span>
    </div>
    <div class="chips" id="samples"></div>
  </div>

  <div class="card">
    <h2>回答</h2>
    <div id="ans" class="ans">—</div>
    <div id="srcbox" class="src"></div>
  </div>
</div>
<script>
const SAMPLES = __SAMPLES__;

function renderSamples(){
  const box = document.getElementById('samples');
  box.innerHTML = '';
  SAMPLES.forEach(s => {
    const b = document.createElement('span');
    b.className = 'chip' + (s.cross ? ' cross' : '');
    b.textContent = s.q;
    b.onclick = () => { document.getElementById('q').value = s.q; go(); };
    box.appendChild(b);
  });
}

function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function go(){
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  const ans = document.getElementById('ans');
  ans.innerHTML = '<span class="loading">检索中…（BM25 + 向量双路召回 → RRF 融合 → 大模型作答）</span>';
  document.getElementById('srcbox').innerHTML = '';
  const r = await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'},
                                      body: JSON.stringify({question:q})});
  const d = await r.json();
  ans.innerHTML = esc(d.answer).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\\[([^\\]]+#[^\\]]+)\\]/g, (m,id)=>'<span class="cite">['+id+']</span>');
  let html = '<h2>出处（可回原 PDF 核对）</h2>';
  (d.hits||[]).forEach(h => {
    html += '<div class="one"><div class="meta"><b>'+esc(h.company)+'</b> · '+esc(h.year)+' 年报 · 第 '+h.page+' 页 · '+esc(h.section||'—')
         + '<span class="tag '+(h.kind==='table'?'tbl':'txt')+'">'+(h.kind==='table'?'表格块':'正文块')+'</span></div>'
         + '<pre>'+esc(h.text.slice(0,600))+'</pre></div>';
  });
  document.getElementById('srcbox').innerHTML = html;
}

fetch('/api/stats').then(r=>r.json()).then(s=>{
  document.getElementById('s-company').textContent = s.companies;
  document.getElementById('s-report').textContent = s.reports;
  document.getElementById('s-page').textContent = s.pages;
  document.getElementById('s-chunk').textContent = s.chunks;
});
renderSamples();

// 支持 /?q=问题 直接带上答案打开（方便分享与截图）
(function(){
  const q = new URLSearchParams(location.search).get('q');
  if (!q) return;
  document.getElementById('q').value = q;
  go();
})();
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def page():
    from questions import QUESTIONS
    samples = [{"q": q["q"], "cross": q.get("cross", False)} for q in QUESTIONS]
    stats = _stats()
    html = PAGE.replace("__SAMPLES__", _json(samples)).replace("__STATS__", _json(stats))
    # 服务端把统计直接填好（截图/无 JS 环境下也看得到）
    html = html.replace('<b id="s-company">10</b>', f'<b id="s-company">{stats["companies"]}</b>')
    html = html.replace('<b id="s-report">20</b>', f'<b id="s-report">{stats["reports"]}</b>')
    html = html.replace('<b id="s-page">—</b>', f'<b id="s-page">{stats["pages"]}</b>')
    html = html.replace('<b id="s-chunk">—</b>', f'<b id="s-chunk">{stats["chunks"]}</b>')
    return HTMLResponse(html)


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


def _stats():
    import json
    d = json.load(open(INDEX_FILE, encoding="utf-8"))
    chunks = d["chunks"]
    return {
        "companies": len(set(c["company"] for c in chunks)),
        "reports": len(set((c["company"], c["year"]) for c in chunks)),
        "pages": len(set((c["company"], c["year"], c["page"]) for c in chunks)),
        "chunks": len(chunks),
        "built_at": d.get("built_at"),
    }


@app.get("/ask", response_class=HTMLResponse)
def ask_page(q: str = ""):
    """服务端渲染的问答页：/ask?q=问题 —— 不用 JS 也能看完整答案与出处（方便分享与截图）"""
    import html as htmllib
    from questions import QUESTIONS
    if not q.strip():
        return page()
    res = ask(q)
    answer = htmllib.escape(res["answer"])
    import re
    answer = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", answer)
    answer = re.sub(r"\[([^\]]+#[^\]]+)\]", r'<span class="cite">[\1]</span>', answer)
    src = []
    for h in res.get("hits", []):
        src.append(
            '<div class="one"><div class="meta"><b>' + htmllib.escape(h["company"]) + "</b> · "
            + htmllib.escape(h["year"]) + " 年报 · 第 " + str(h["page"]) + " 页 · "
            + htmllib.escape(h.get("section") or "—")
            + '<span class="tag ' + ("tbl" if h.get("kind") == "table" else "txt") + '">'
            + ("表格块" if h.get("kind") == "table" else "正文块") + "</span></div><pre>"
            + htmllib.escape(h["text"][:600]) + "</pre></div>")
    samples = [{"q": x["q"], "cross": x.get("cross", False)} for x in QUESTIONS]
    stats = _stats()
    html = PAGE.replace("__SAMPLES__", _json(samples)).replace("__STATS__", _json(stats))
    html = html.replace('<b id="s-company">10</b>', f'<b id="s-company">{stats["companies"]}</b>')
    html = html.replace('<b id="s-report">20</b>', f'<b id="s-report">{stats["reports"]}</b>')
    html = html.replace('<b id="s-page">—</b>', f'<b id="s-page">{stats["pages"]}</b>')
    html = html.replace('<b id="s-chunk">—</b>', f'<b id="s-chunk">{stats["chunks"]}</b>')
    html = html.replace('<div id="ans" class="ans">—</div>',
                        '<div id="ans" class="ans">' + answer + "</div>")
    html = html.replace('<div id="srcbox" class="src"></div>',
                        '<div id="srcbox" class="src"><h2>出处（可回原 PDF 核对）</h2>' + "".join(src) + "</div>")
    html = html.replace('<textarea id="q" placeholder="例如：贵州茅台 2025 年营业收入是多少？"></textarea>',
                        '<textarea id="q">' + htmllib.escape(q) + "</textarea>")
    return HTMLResponse(html)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def stats():
    return _stats()


@app.post("/api/ask")
async def api_ask(req: Request):
    body = await req.json()
    return ask(body.get("question", ""))
