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
# 콘텐츠 전문 매체 + 동남아 특화 매체만. 종합지(CNA 메인, ST 메인)는 제외.
# query에 콘텐츠 관련 키워드를 명시해 수집 단계부터 범위 제한.
SOURCES = [
    # ── 방송/OTT 전문 ──
    # CNA Lifestyle은 엔터/라이프스타일 섹션만 — 종합 뉴스 아님
    {"name": "CNA Lifestyle",     "query": "site:cnalifestyle.channelnewsasia.com entertainment OR streaming OR OTT OR film"},
    # Variety는 글로벌 엔터 전문지
    {"name": "Variety",           "query": "site:variety.com southeast asia OR singapore OR malaysia OR thailand OR indonesia OR vietnam"},
    # Deadline: 글로벌 엔터 전문
    {"name": "Deadline",          "query": "site:deadline.com southeast asia OR asia content OR streaming asia"},

    # ── 게임/융복합 전문 ──
    {"name": "Digital News Asia", "query": "site:digitalnewsasia.com game OR gaming OR esports OR entertainment"},
    {"name": "The Magic Rain",    "query": "site:themagicrain.com"},  # 말레이 게임/엔터 전문
    {"name": "Niko Partners",     "query": "site:nikopartners.com southeast asia OR SEA game"},  # 아시아 게임 리서치

    # ── 애니/캐릭터/웹툰 전문 ──
    {"name": "Anime News Network","query": "site:animenewsnetwork.com southeast asia OR singapore OR malaysia OR korea"},
    {"name": "WebProNews",        "query": "site:webpronews.com anime OR webtoon OR animation OR character"},

    # ── 음악 전문 ──
    {"name": "Digital Music News","query": "site:digitalmusicnews.com asia OR southeast asia OR k-pop"},
    {"name": "Billboard Asia",    "query": "site:billboard.com asia OR southeast asia OR k-pop streaming"},

    # ── 패션/라이프스타일 전문 ──
    {"name": "Nabalune News",     "query": "site:nabalunews.com"},  # 동남아 패션 전문
    {"name": "Vogue SEA",         "query": "site:vogue.com.sg OR site:vogue.com.my"},

    # ── 정책/규제 (공공기관·전문 매체) ──
    {"name": "IMDA",              "query": "site:imda.gov.sg"},       # 싱가포르 미디어개발청
    {"name": "Bernama Policy",    "query": "site:bernama.com content OR media OR entertainment OR digital OR creative industry"},
    {"name": "KrASIA",            "query": "site:kr.asia media OR content OR entertainment OR streaming OR OTT"},  # 동남아 테크/미디어 전문
    {"name": "The Malay Mail Ent","query": "site:malaymail.com entertainment OR film OR music OR gaming OR anime"},
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
    t = title.lower()
    return any(kw.lower() in t for kw in SEA_KEYWORDS)

# 명백히 부적합한 제목 사전 차단
BLOCK_KEYWORDS = [
    # 사건·사고·범죄
    "military", "aircraft", "crashed", "crash", "war", "army", "missile", "bomb",
    "murder", "killed", "stabbed", "assault", "rape", "sex crime", "sexually assault",
    "kidnap", "abduct", "suicide", "overdose", "e-waste", "theft", "stolen", "robbery",
    "dies during", "found dead", "dies 10 minutes", "death of woman",
    "charged with causing death", "gets jail", "arrested", "detained", "sentenced",
    # 스포츠 (콘텐츠 무관)
    "world cup", "olympics", "premier league", "football match", "soccer", "rugby",
    "tennis", "badminton", "formula 1", "f1 race", "cycling race", "marathon",
    "friendly match", "cancelled due to conflict", "sports", "athlete defect",
    # 비관련 경제·인프라
    "interest rate", "mortgage", "housing price", "oil price",
    "petrol price", "fuel price", "electricity price", "airline", "flight",
    "airport", "suspension of service", "doha", "aviation",
    # 일반 지리·시사
    "google maps", "maps data", "map sharing", "middle east conflict",
    "earthquake", "flood", "typhoon", "hurricane", "wildfire",
]

def is_valid_title(title: str) -> bool:
    """URL 형태 제목 차단 + 명백히 무관 기사 1차 차단"""
    t = title.lower().strip()
    # URL이 제목으로 들어온 경우
    if t.startswith("http://") or t.startswith("https://"):
        return False
    if "sitemap" in t or "feeds.xml" in t:
        return False
    # 콘텐츠 산업 무관 키워드
    return not any(kw in t for kw in BLOCK_KEYWORDS)

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
            for entry in feed.entries[:3]:  # 소스당 최대 3건
                if entry.link in processed: continue
                if entry.title in seen_titles: continue
                seen_titles.add(entry.title)

                # 1차 필터: 제목에 동남아 키워드가 없으면 스킵
                # (단, 정책/규제 소스는 동남아 필터 완화)
                if not is_valid_title(entry.title):
                    print(f"  ✗ 제목 차단: {entry.title[:50]}")
                    continue
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

    # 총량 캡: 최대 30건 (Claude 필터 후 10-15건 목표)
    import random
    if len(all_articles) > 30:
        all_articles = random.sample(all_articles, 30)
    return all_articles


# ── Claude 분류 프롬프트 ──
SYSTEM_PROMPT = f"""당신은 KOCCA(한국콘텐츠진흥원) 해외사무소의 시장 분석 전문가입니다.
KOCCA가 매주 발행하는 '위클리글로벌' 보고서에 수록할 기사를 엄격하게 선별합니다.

[핵심 원칙]
- 이 보고서는 한국 콘텐츠 기업·공공기관의 동남아 시장 전략 수립용 정보지입니다.
- 콘텐츠 산업(OTT·게임·애니·웹툰·음악·패션·정책)과 직접 연관된 동남아 기사만 수록합니다.
- 동남아 지역에서 발생한 일이라도 콘텐츠 산업과 무관하면 NO입니다.
- 스포츠, 항공, 범죄, 사고, 지리 정보, 외교, 군사는 콘텐츠 산업이 아닙니다.

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

[무조건 제외 — 하나라도 해당하면 즉시 NO]
1. 사건·사고: 사망, 폭행, 성범죄, 의료사고, 교통사고, 재해, 군사 충돌
2. 가십·개인 신상: 연예인 개인 사생활, 연애, 건강, 단순 수상 소식
3. 소비자 정보: 티켓 예매, 식당, 관광, 쇼핑 가이드
4. 비관련 경제: 유가, 전기요금, 금리, 부동산, 환율 — 콘텐츠 산업 연관 없는 경우
5. 일반 시사: 정치, 외교, 군사, 기후, 의료, 스포츠 — 콘텐츠 연관 없는 경우
6. 단순 이벤트: 영화 개봉 공지, 시상식 수상 나열 — 시장 시사점 없는 경우
7. 비동남아 단독 기사: 미국·유럽·중국만 다루는 기사 (동남아 언급 없음)
8. 애매한 경우: 콘텐츠 산업 직접 관련성 60% 미만이면 NO

[판단 예시 — NO 케이스]
- "Chinese influencer dies during livestream" → 사망 사고, NO
- "US military aircraft crashed in Iraq" → 군사 사고, NO
- "Singapore doctor charged with causing death" → 의료사고, NO
- "Petrol prices go up in Singapore" → 비관련 경제, NO
- "Woman sent to hospital after car collision" → 교통사고, NO
- "Bridge Data Centres plans $5 billion AI investment" → 콘텐츠 무관 IT 인프라, NO

[판단 예시 — YES 케이스]
- "Netflix increases content investment in Southeast Asia" → OTT 전략, YES
- "Singapore IMDA launches fund for animation co-production" → 정책/규제, YES
- "K-drama popularity drives tourism surge in Thailand" → K-콘텐츠 동남아 반응, YES
- "Malaysia gaming industry revenue hits record high" → 게임 시장 통계, YES

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
