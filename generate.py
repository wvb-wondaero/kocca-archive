#!/usr/bin/env python3
import re, os, sys, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

SITE_TITLE    = "KOCCA 마켓 아카이브"
SITE_SUBTITLE = "콘텐츠 산업 시장 동향 아카이브"

# market_watcher.py 카테고리와 완전히 동기화
CATEGORIES = [
    "방송/영화/OTT",
    "게임/융복합",
    "애니/캐릭터",
    "만화/웹툰",
    "음악/공연",
    "패션/라이프스타일",
    "정책/규제",
]
CATEGORY_EMOJI = {
    "방송/영화/OTT":    "🎬",
    "게임/융복합":      "🎮",
    "애니/캐릭터":      "🎨",
    "만화/웹툰":        "📚",
    "음악/공연":        "🎵",
    "패션/라이프스타일":"👗",
    "정책/규제":        "📋",
    "기타":             "📌",
}

DATE_RE = re.compile(r'##\s*.*?(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일')
ART_RE  = re.compile(r'^\s*\*\s+\*\*\[([^\]]+)\]\*\*\s+\[([^\]]+)\]\(([^)]+)\)')
SUM_RE  = re.compile(r'^\s*\*\s+💡\s*(.+)$')

def parse_markdown(text):
    articles, current_date, pending = [], None, None
    for line in text.splitlines():
        dm = DATE_RE.search(line)
        if dm:
            try: current_date = datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            except: current_date = None
            pending = None; continue
        am = ART_RE.match(line)
        if am:
            if pending: articles.append(pending)
            cat = am.group(1).strip()
            # 정의된 카테고리 외 항목은 '기타'로 통일
            if cat not in CATEGORIES: cat = "기타"
            pending = {
                "category": cat, "title": am.group(2).strip(),
                "url": am.group(3).strip(), "summary": "",
                "date": current_date,
                "date_str": current_date.strftime("%Y-%m-%d") if current_date else "",
                "emoji": CATEGORY_EMOJI.get(cat, "📌"),
            }
            continue
        sm = SUM_RE.match(line)
        if sm and pending:
            pending["summary"] = sm.group(1).strip()
            articles.append(pending); pending = None; continue
    if pending: articles.append(pending)
    return articles

def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def build_html(articles):
    # 카테고리 순서를 CATEGORIES 순서 기준으로 고정
    seen_cats = [c for c in CATEGORIES if any(a["category"]==c for a in articles)]
    if any(a["category"]=="기타" for a in articles):
        seen_cats.append("기타")

    by_date = defaultdict(list)
    no_date = []
    for a in articles:
        (by_date[a["date_str"]] if a["date_str"] else no_date).append(a)
    sorted_dates = sorted(by_date.keys(), reverse=True)

    card_parts = []
    for dk in sorted_dates + (["__none__"] if no_date else []):
        items = by_date[dk] if dk != "__none__" else no_date
        if not items: continue
        label = dk if dk != "__none__" else "날짜 미지정"
        card_parts.append(
            f'<div class="date-section">'
            f'<div class="date-header">'
            f'<span class="date-badge">{esc(label)}</span>'
            f'<span class="art-count">{len(items)}건</span>'
            f'</div><div class="card-grid">'
        )
        for a in items:
            card_parts.append(
                f'<div class="card" data-cat="{esc(a["category"])}">'
                f'<div class="card-top"><span class="cat-tag">{a["emoji"]} {esc(a["category"])}</span></div>'
                f'<a class="card-title" href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["title"])}</a>'
                f'<p class="card-summary">{esc(a["summary"])}</p>'
                f'</div>'
            )
        card_parts.append('</div></div>')

    list_parts = []
    for i, a in enumerate(articles, 1):
        ds = f'<span class="list-date">{esc(a["date_str"])}</span>' if a["date_str"] else ''
        list_parts.append(
            f'<div class="list-item" data-cat="{esc(a["category"])}">'
            f'<span class="list-num">{i}</span>'
            f'<span class="list-cat">{a["emoji"]} {esc(a["category"])}</span>'
            f'{ds}'
            f'<div class="list-body">'
            f'<a class="list-title" href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["title"])}</a>'
            f'<p class="list-summary">{esc(a["summary"])}</p>'
            f'</div></div>'
        )

    tabs = f'<button class="ctab active" data-cat="all">전체 <span class="tc">{len(articles)}</span></button>'
    for cat in seen_cats:
        cnt = sum(1 for a in articles if a["category"]==cat)
        tabs += f'<button class="ctab" data-cat="{esc(cat)}">{CATEGORY_EMOJI.get(cat,"📌")} {esc(cat)} <span class="tc">{cnt}</span></button>'

SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT).strftime("%Y-%m-%d %H:%M (SGT)")

    return f"""<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(SITE_TITLE)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap');

/* ── 다크 테마 (기본) ── */
[data-theme="dark"] {{
  --bg:    #0d0f14;
  --surf:  #161922;
  --brd:   #2a2f3d;
  --acc:   #4f8ef7;
  --acc2:  #f7a24f;
  --tx:    #e2e8f0;
  --txm:   #8892a4;
  --txd:   #4a5568;
  --card-bg: #161922;
  --shadow: none;
  --tog-bg: #1e222d;
  --tog-knob: #4f8ef7;
}}

/* ── 라이트 테마 ── */
[data-theme="light"] {{
  --bg:    #f4f6fb;
  --surf:  #ffffff;
  --brd:   #dde1ea;
  --acc:   #2563eb;
  --acc2:  #d97706;
  --tx:    #1a202c;
  --txm:   #4a5568;
  --txd:   #a0aec0;
  --card-bg: #ffffff;
  --shadow: 0 1px 4px rgba(0,0,0,.08);
  --tog-bg: #e2e8f0;
  --tog-knob: #2563eb;
}}

*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%}}
body{{background:var(--bg);color:var(--tx);font-family:'Noto Sans KR',sans-serif;font-size:14px;line-height:1.6;transition:background .2s,color .2s}}

/* ── 헤더 ── */
header{{
  background:var(--surf);border-bottom:1px solid var(--brd);
  padding:0 20px;position:sticky;top:0;z-index:100;
  display:flex;align-items:center;justify-content:space-between;height:52px;
  transition:background .2s,border-color .2s;
}}
.logo{{font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600;color:var(--acc)}}
.logo-sub{{font-size:11px;color:var(--txm);display:none;margin-left:8px}}
@media(min-width:600px){{.logo-sub{{display:inline}}}}
.hdr-r{{display:flex;align-items:center;gap:10px}}
.upd{{font-size:11px;color:var(--txd);font-family:'IBM Plex Mono',monospace}}

/* ── 뷰 토글 ── */
.vtoggle{{display:flex;background:var(--bg);border:1px solid var(--brd);border-radius:6px;overflow:hidden}}
.vbtn{{padding:5px 12px;background:none;border:none;color:var(--txm);cursor:pointer;
  font-size:12px;font-family:'Noto Sans KR',sans-serif;transition:all .15s}}
.vbtn.active{{background:var(--acc);color:#fff}}

/* ── 다크/라이트 토글 ── */
.theme-toggle{{
  position:relative;width:40px;height:22px;cursor:pointer;flex-shrink:0;
}}
.theme-toggle input{{opacity:0;width:0;height:0;position:absolute}}
.theme-track{{
  position:absolute;inset:0;background:var(--tog-bg);border-radius:11px;
  border:1px solid var(--brd);transition:background .2s;
}}
.theme-knob{{
  position:absolute;top:3px;left:3px;width:14px;height:14px;
  background:var(--tog-knob);border-radius:50%;transition:transform .2s,background .2s;
  display:flex;align-items:center;justify-content:center;font-size:8px;
}}
.theme-toggle input:checked + .theme-track .theme-knob{{transform:translateX(18px)}}
.theme-icon{{position:absolute;font-size:10px;top:50%;transform:translateY(-50%);pointer-events:none}}
.theme-icon.sun{{right:5px}}
.theme-icon.moon{{left:5px}}

/* ── 카테고리 탭 ── */
.catbar{{
  background:var(--surf);border-bottom:1px solid var(--brd);
  padding:0 20px;display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;
  transition:background .2s;
}}
.catbar::-webkit-scrollbar{{display:none}}
.ctab{{
  padding:10px 12px;background:none;border:none;border-bottom:2px solid transparent;
  color:var(--txm);cursor:pointer;font-size:12px;font-family:'Noto Sans KR',sans-serif;
  white-space:nowrap;transition:all .15s;
}}
.ctab:hover{{color:var(--tx)}}
.ctab.active{{color:var(--acc);border-bottom-color:var(--acc)}}
.tc{{font-size:10px;background:var(--brd);border-radius:10px;padding:1px 5px;margin-left:3px}}
.ctab.active .tc{{background:rgba(79,142,247,.15);color:var(--acc)}}

/* ── 메인 ── */
main{{max-width:1200px;margin:0 auto;padding:24px 16px}}
#vcard{{display:block}}#vlist{{display:none}}

/* ── 날짜 섹션 ── */
.date-section{{margin-bottom:32px}}
.date-header{{display:flex;align-items:center;gap:10px;margin-bottom:14px}}
.date-badge{{
  font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--acc2);
  background:rgba(247,162,79,.1);border:1px solid rgba(247,162,79,.3);
  border-radius:4px;padding:3px 8px;
}}
.art-count{{font-size:11px;color:var(--txd)}}

/* ── 카드 ── */
.card-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}}
.card{{
  background:var(--card-bg);border:1px solid var(--brd);border-radius:10px;
  padding:16px;transition:border-color .15s,transform .15s,box-shadow .15s;
  box-shadow:var(--shadow);
}}
.card:hover{{border-color:var(--acc);transform:translateY(-2px);box-shadow:0 4px 16px rgba(79,142,247,.12)}}
.card.hidden{{display:none}}
.card-top{{margin-bottom:10px}}
.cat-tag{{font-size:11px;color:var(--acc);background:rgba(79,142,247,.1);border-radius:4px;padding:2px 7px}}
.card-title{{display:block;font-size:13.5px;font-weight:500;color:var(--tx);text-decoration:none;line-height:1.5;margin:8px 0}}
.card-title:hover{{color:var(--acc)}}
.card-summary{{font-size:12px;color:var(--txm);line-height:1.6;border-left:2px solid var(--brd);padding-left:10px}}

/* ── 목록 ── */
.list-item{{display:flex;align-items:flex-start;gap:10px;padding:14px 0;border-bottom:1px solid var(--brd)}}
.list-item.hidden{{display:none}}
.list-num{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--txd);min-width:24px;padding-top:2px;text-align:right}}
.list-cat{{font-size:11px;color:var(--acc);white-space:nowrap;padding-top:2px;min-width:100px}}
.list-date{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--txd);white-space:nowrap;padding-top:2px;min-width:78px}}
.list-body{{flex:1;min-width:0}}
.list-title{{font-size:13.5px;color:var(--tx);text-decoration:none;font-weight:500}}
.list-title:hover{{color:var(--acc)}}
.list-summary{{font-size:12px;color:var(--txm);margin-top:4px}}

/* ── 풋터 ── */
footer{{text-align:center;padding:32px 16px;font-size:12px;color:var(--txd);border-top:1px solid var(--brd)}}
footer a{{color:var(--txm);text-decoration:none}}
footer a:hover{{color:var(--acc)}}
</style>
</head>
<body>

<header>
  <div style="display:flex;align-items:center;min-width:0">
    <span class="logo">📊 {esc(SITE_TITLE)}</span>
    <span class="logo-sub">— {esc(SITE_SUBTITLE)}</span>
  </div>
  <div class="hdr-r">
    <span class="upd">{now}</span>

    <!-- 다크/라이트 토글 -->
    <label class="theme-toggle" title="테마 전환">
      <input type="checkbox" id="theme-chk">
      <div class="theme-track">
        <div class="theme-knob"></div>
      </div>
      <span class="theme-icon moon">🌙</span>
      <span class="theme-icon sun">☀️</span>
    </label>

    <!-- 카드/목록 뷰 토글 -->
    <div class="vtoggle">
      <button class="vbtn active" id="btn-card" onclick="setView('card')">카드</button>
      <button class="vbtn" id="btn-list" onclick="setView('list')">목록</button>
    </div>
  </div>
</header>

<div class="catbar">{tabs}</div>

<main>
  <div id="vcard">{''.join(card_parts)}</div>
  <div id="vlist">{''.join(list_parts)}</div>
</main>

<footer>
  데이터: <a href="https://github.com/wvb-wondaero/kocca-archive" target="_blank">kocca-archive / MARKET_ARCHIVE.md</a>
  &nbsp;|&nbsp; 생성: {now} &nbsp;|&nbsp;
  참고: <a href="https://github.com/rainygirl/rreader" target="_blank">rreader-web</a>
</footer>

<script>
// ── 테마 ──
const html = document.documentElement;
const chk  = document.getElementById('theme-chk');

function applyTheme(theme) {{
  html.setAttribute('data-theme', theme);
  chk.checked = (theme === 'light');
  try {{ localStorage.setItem('kocca_theme', theme); }} catch(e) {{}}
}}

chk.addEventListener('change', () => applyTheme(chk.checked ? 'light' : 'dark'));

(function() {{
  try {{
    const saved = localStorage.getItem('kocca_theme');
    if (saved) applyTheme(saved);
    else if (window.matchMedia('(prefers-color-scheme: light)').matches) applyTheme('light');
  }} catch(e) {{}}
}})();

// ── 뷰 전환 ──
function setView(v) {{
  document.getElementById('vcard').style.display = v==='card' ? 'block' : 'none';
  document.getElementById('vlist').style.display = v==='list' ? 'block' : 'none';
  document.getElementById('btn-card').classList.toggle('active', v==='card');
  document.getElementById('btn-list').classList.toggle('active', v==='list');
  try {{ localStorage.setItem('kocca_view', v); }} catch(e) {{}}
}}

// ── 카테고리 필터 ──
let cc = 'all';
document.querySelectorAll('.ctab').forEach(b => b.addEventListener('click', () => {{
  cc = b.dataset.cat;
  document.querySelectorAll('.ctab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  document.querySelectorAll('.card,.list-item').forEach(el =>
    el.classList.toggle('hidden', cc !== 'all' && el.dataset.cat !== cc));
  document.querySelectorAll('.date-section').forEach(sec => {{
    const vis = [...sec.querySelectorAll('.card')].filter(c => !c.classList.contains('hidden'));
    sec.style.display = vis.length ? 'block' : 'none';
    const cnt = sec.querySelector('.art-count');
    if (cnt) cnt.textContent = vis.length + '건';
  }});
}}));

// ── 초기화 ──
try {{ const v = localStorage.getItem('kocca_view'); if (v) setView(v); }} catch(e) {{}}
</script>
</body>
</html>"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", "-i", default="MARKET_ARCHIVE.md")
    p.add_argument("--output", "-o", default="output")
    a = p.parse_args()

    print("[KOCCA Archive Generator v2]")
    if not os.path.exists(a.input):
        print(f"  ✗ 파일 없음: {a.input}"); sys.exit(1)
    with open(a.input, encoding="utf-8") as f: text = f.read()

    articles = parse_markdown(text)
    print(f"  → 파싱: {len(articles)}건")
    if not articles: print("  ✗ 파싱 결과 없음"); sys.exit(1)

    cats = defaultdict(int)
    for art in articles: cats[art["category"]] += 1
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {CATEGORY_EMOJI.get(cat,'📌')} {cat}: {cnt}건")

    html = build_html(articles)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"  ✓ 생성: {out / 'index.html'}")

if __name__ == "__main__": main()
