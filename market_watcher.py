import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests

# --- [설정 및 비밀키] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "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")
DATABASE_ID = "2e5653bb339a8069a3dcc3a6748a2ce3"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"

# market_watcher.py 원본 카테고리 그대로 유지
CATEGORIES = [
    "방송/영화/OTT",
    "게임/융복합",
    "애니/캐릭터",
    "만화/웹툰",
    "음악/공연",
    "패션/라이프스타일",
]

SOURCES = [
    {"name": "Mothership.SG", "query": "site:mothership.sg", "type": "search"},
    {"name": "CNA",           "query": "site:channelnewsasia.com", "type": "search"},
    {"name": "Straits Times", "query": "site:straitstimes.com", "type": "search"},
    {"name": "Today Online",  "query": "site:todayonline.com", "type": "search"},
    {"name": "IMDA",          "query": "site:imda.gov.sg", "type": "search"},
]

# ──────────────────────────────────────────────
# 필터 개선: 더 엄격한 선정 기준
# ──────────────────────────────────────────────
SYSTEM_PROMPT = f"""당신은 KOCCA(한국콘텐츠진흥원) 싱가포르 사무소의 시장 분석 전문가입니다.
아래 기사가 한국 콘텐츠 기업의 동남아 전략 수립에 직접적으로 활용 가능한 정보인지 엄격하게 판단하십시오.

[선정 기준 — 아래 항목 중 하나에 명확히 해당해야 YES]
1. 플랫폼 전략 변화: OTT·스트리밍 서비스의 동남아 현지화 투자, 콘텐츠 수급 전략, 구독 정책 변경.
2. 규제·정책: 저작권법, 콘텐츠 등급 제도, 디지털세, 플랫폼 규제 등 한국 기업에 직접 영향을 주는 법·제도 변화.
3. K-콘텐츠 직접 관련: K-드라마·K-팝·웹툰·게임의 현지 흥행, 라이선싱 계약, IP 확장 사례.
4. 시장 구조 변화: M&A, 대형 투자 유치, 경쟁 플랫폼 간 합종연횡 등 산업 지형 변화.

[배제 기준 — 하나라도 해당하면 NO]
1. 가십·사건사고: 연예인 개인 신상, 범죄, 사고, 단순 시상식 수상 소식.
2. 콘텐츠 소비 정보: 티켓 예매, 공연 일정, 음식점·여행 추천 등 소비자 대상 정보.
3. 비관련 기술·경제 뉴스: 반도체, 부동산, 금융, 물가, 교통 등 콘텐츠 산업과 무관한 뉴스.
4. 단신·일회성: 행사 개최 공지, 단순 신제품 출시 보도 (산업적 시사점 없음).
5. 애매한 경우: 확실히 관련성이 높지 않으면 NO로 판단. 관련성이 의심스러운 경우 NO 우선.

카테고리는 반드시 다음 중 하나만 선택: {', '.join(CATEGORIES)}

응답 형식 (이 형식 외 다른 텍스트 금지):
CATEGORY: <카테고리>
AI_SUMMARY: <핵심 내용 한 줄, 30자 이내>
SUITABLE: YES 또는 NO
"""

# ──────────────────────────────────────────────
# 기존 함수들 (변경 없음)
# ──────────────────────────────────────────────

def load_processed_links():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: return set(f.read().splitlines())
    return set()

def save_processed_link(link):
    with open(DB_FILE, "a") as f: f.write(link + "\n")

def fetch_articles():
    all_articles = []
    processed = load_processed_links()
    for source in SOURCES:
        try:
            encoded_q = urllib.parse.quote(source["query"])
            url = f"https://news.google.com/rss/search?q={encoded_q}+when:1d&hl=en-SG&gl=SG&ceid=SG:en"
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                if entry.link not in processed:
                    img = ""
                    if hasattr(entry, 'media_thumbnail'): img = entry.media_thumbnail[0]['url']
                    all_articles.append({'title': entry.title, 'link': entry.link, 'image': img})
        except: continue
    return all_articles

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"제목: {article['title']}\n링크: {article['link']}"
    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        res = msg.content[0].text
        data = {'cat': '기타', 'ai': '', 'ok': False}
        for line in res.split('\n'):
            if line.startswith("CATEGORY:"):
                cat = line.split(":", 1)[1].strip()
                data['cat'] = cat if cat in CATEGORIES else '기타'
            elif line.startswith("AI_SUMMARY:"):
                data['ai'] = line.split(":", 1)[1].strip()
            elif "SUITABLE: YES" in line.upper():
                data['ok'] = True
        return data
    except: return None

def send_to_notion(article, ai_data):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    img_url = article['image'] if article['image'] else "https://www.notion.so/icons/news_gray.svg"
    today_date = datetime.datetime.now().strftime('%Y-%m-%d')
    properties = {
        "제목": {"title": [{"text": {"content": article['title']}}]},
        "태그": {"multi_select": [{"name": "News"}, {"name": ai_data['cat']}]},
        "URL": {"url": article['link']},
        "Summary": {"rich_text": [{"text": {"content": ai_data['ai']}}]},
        "생성일자": {"date": {"start": today_date}},
        "이미지": {"files": [{"name": "Thumbnail", "external": {"url": img_url}}]},
    }
    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200: print(f"✅ Notion: {article['title'][:30]}...")
    else: print(f"❌ Notion 실패: {response.text}")

def update_github_markdown(results):
    today = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 KOCCA 글로벌 콘텐츠 산업 동향 아카이브 (엄선본)\n\n"
    new_entry = f"## 📅 {today} 업데이트\n\n"
    if not results:
        new_entry += "> 📭 **KOCCA 선정 기준에 부합하는 새로운 콘텐츠가 없습니다.**\n\n"
    else:
        for item in results:
            new_entry += f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n  * 💡 {item['ai']}\n"
    existing = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + new_entry + "\n---\n" + existing)

def main():
    articles = fetch_articles()
    print(f"{len(articles)}개 뉴스 분석 시작 (엄격 필터 적용)...")
    combined_list = []
    accepted = 0
    rejected = 0
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res['ok']:
            send_to_notion(art, ai_res)
            save_processed_link(art['link'])
            combined_list.append({**art, **ai_res})
            accepted += 1
        else:
            rejected += 1
        time.sleep(0.3)
    print(f"✅ 선정: {accepted}건 / ❌ 제외: {rejected}건")
    update_github_markdown(combined_list)

if __name__ == "__main__":
    main()
