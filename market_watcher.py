import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests

# --- [설정] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "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")
DATABASE_ID = "2e5653bb339a8069a3dcc3a6748a2ce3"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"

# ── KOCCA 위클리글로벌 기준 카테고리 ──
CATEGORIES = [
    "방송/영화/OTT",
    "게임/융복합",
    "애니/캐릭터",
    "만화/웹툰",
    "음악/공연",
    "패션/라이프스타일",
    "정책/규제",       # 위클리글로벌의 '통합(정책 등)'에 해당
]

# ── 소스 정의 ──
# 이미지 8번에 명시된 소스 + 공신력 있는 동남아 매체 우선
# Google News RSS로 각 사이트 최신 기사 수집
SOURCES = [
    # 방송/영화 전문
    {"name": "CNA Lifestyle",      "query": "site:cnalifestyle.channelnewsasia.com"},
    {"name": "CNA",                "query": "site:channelnewsasia.com"},
    {"name": "Variety",            "query": "site:variety.com"},
    {"name": "Malay Mail",         "query": "site:malaymail.com"},

    # 게임/테크
    {"name": "Digital News Asia",  "query": "site:digitalnewsasia.com"},
    {"name": "The Magic Rain",     "query": "site:themagicrain.com"},

    # 애니/만화/웹툰
    {"name": "The Star ASEAN",     "query": "site:thestar.com.my"},

    # 음악
    {"name": "New Straits Times",  "query": "site:nst.com.my"},
    {"name": "Straits Times",      "query": "site:straitstimes.com"},
    {"name": "Digital Music News", "query": "site:digitalmusicnews.com"},

    # 패션
    {"name": "Nabalune News",      "query": "site:nabalunews.com"},

    # 정책/통합
    {"name": "Bernama",            "query": "site:bernama.com"},
    {"name": "IMDA",               "query": "site:imda.gov.sg"},
    {"name": "AP News SEA",        "query": "site:apnews.com"},
]

# ── 동남아 키워드 (제목에 하나라도 있어야 1차 통과) ──
SEA_KEYWORDS = [
    "singapore", "싱가포르", "malaysia", "말레이시아", "thailand", "태국", "bangkok",
    "indonesia", "인도네시아", "jakarta", "vietnam", "베트남", "hanoi",
    "philippines", "필리핀", "manila", "myanmar", "cambodia", "laos",
    "southeast asia", "asean", "동남아",
    # 동남아 OTT/플랫폼 관련 키워드 추가 (지역 이름 없어도 동남아 관련)
    "viu", "vidio", "wetv", "iQIYI", "hooq", "migo",
    # K-콘텐츠 동남아 관련
    "k-content", "k-drama", "k-pop", "korean content", "kocca",
    # 주요 플랫폼의 동남아 전략
    "netflix asia", "disney+ asia", "spotify asia",
]

def is_sea_related(title: str) -> bool:
    """제목에 동남아 관련 키워드가 포함되어 있는지 확인"""
    t = title.lower()
    return any(kw.lower() in t for kw in SEA_KEYWORDS)

def load_processed_links():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: return set(f.read().splitlines())
    return set()

def save_processed_link(link):
    with open(DB_FILE, "a") as f: f.write(link + "\n")

def fetch_articles():
    all_articles = []
    processed = load_processed_links()
    seen_titles = set()

    for source in SOURCES:
        try:
            encoded_q = urllib.parse.quote(source["query"] + " when:2d")
            url = (f"https://news.google.com/rss/search"
                   f"?q={encoded_q}&hl=en-SG&gl=SG&ceid=SG:en")
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                if entry.link in processed: continue
                if entry.title in seen_titles: continue
                seen_titles.add(entry.title)

                # 1차 필터: 제목에 동남아 키워드가 없으면 스킵
                # (단, 정책/규제 소스는 동남아 필터 완화)
                if source["name"] in ("IMDA", "Bernama") or is_sea_related(entry.title):
                    img = ""
                    if hasattr(entry, 'media_thumbnail'):
                        img = entry.media_thumbnail[0]['url']
                    all_articles.append({
                        'title': entry.title,
                        'link': entry.link,
                        'image': img,
                        'source': source['name'],
                    })
        except Exception as e:
            print(f"  소스 오류 [{source['name']}]: {e}")
            continue

    return all_articles


# ── Claude 분류 프롬프트 ──
SYSTEM_PROMPT = f"""당신은 KOCCA(한국콘텐츠진흥원) 해외사무소의 시장 분석 전문가입니다.
KOCCA가 매주 발행하는 '위클리글로벌' 보고서에 수록할 기사를 엄격하게 선별합니다.

[위클리글로벌 수록 기준 — 다음 조건을 모두 충족해야 YES]
1. 동남아시아(싱가포르·말레이시아·태국·인도네시아·베트남·필리핀 등) 또는 아세안 지역 관련 기사
2. 아래 분야 중 하나에 명확히 해당:
   - OTT·스트리밍 플랫폼의 콘텐츠 투자·현지화 전략·구독 정책
   - 게임·e스포츠 시장 통계·규제·주요 기업 동향
   - 애니메이션·캐릭터 IP 비즈니스·공동제작
   - 웹툰·만화·스토리 IP의 시장 진출·현지화
   - 음악 스트리밍·공연 시장·K-팝 현지 반응
   - 패션·라이프스타일 산업의 디지털화·콘텐츠 연계 동향
   - 콘텐츠 산업 관련 정부 정책·규제·지원 사업·한-현지 협력 MOU
3. 한국 콘텐츠 기업 또는 공공기관이 시장 전략 수립에 활용 가능한 정보

[무조건 제외 — 하나라도 해당하면 NO]
1. 사건·사고·가십: 개인 범죄, 사망, 폭행, 개인 신상, 연예인 연애
2. 소비자 정보: 티켓 예매, 식당 추천, 관광, 쇼핑 가이드
3. 비관련 경제: 유가, 금리, 부동산, 환율, 주식 (콘텐츠 산업 직접 연관 없는 경우)
4. 일반 시사: 정치, 외교, 군사, 기후, 스포츠 (콘텐츠 연관 없는 경우)
5. 단순 이벤트: 영화 개봉일 공지, 단순 시상식 수상 나열 (시장 시사점 없는 경우)
6. 지역 범위 초과: 동남아 외 지역만 다루는 기사 (미국, 유럽, 중국 단독 기사)
7. 확실하지 않은 경우: 관련성이 50% 미만이면 NO 우선

카테고리 (반드시 아래 중 하나만 선택):
{chr(10).join(f'  - {c}' for c in CATEGORIES)}

응답 형식 (이 형식 외 다른 텍스트 절대 금지):
CATEGORY: <카테고리>
AI_SUMMARY: <한 줄 요약, 40자 이내, 한국어>
SUITABLE: YES 또는 NO
"""

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"소스: {article['source']}\n제목: {article['title']}\n링크: {article['link']}"
    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=200,
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
    except Exception as e:
        print(f"  Claude API 오류: {e}")
        return None

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
    if response.status_code == 200:
        print(f"  ✅ Notion: {article['title'][:35]}...")
    else:
        print(f"  ❌ Notion 실패: {response.status_code}")

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
    print(f"\n총 {len(articles)}건 수집 (동남아 1차 필터 적용 후)")
    print("─" * 50)

    combined_list = []
    accepted = rejected = 0

    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res['ok']:
            send_to_notion(art, ai_res)
            save_processed_link(art['link'])
            combined_list.append({**art, **ai_res})
            print(f"  ✅ [{ai_res['cat']}] {art['title'][:40]}...")
            accepted += 1
        else:
            print(f"  ✗ SKIP: {art['title'][:40]}...")
            rejected += 1
        time.sleep(0.3)

    print("─" * 50)
    print(f"선정: {accepted}건 / 제외: {rejected}건")
    update_github_markdown(combined_list)
    print("✓ MARKET_ARCHIVE.md 업데이트 완료")

if __name__ == "__main__":
    main()
