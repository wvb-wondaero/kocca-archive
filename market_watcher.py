import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests
import json
import re

# --- [설정 및 비밀키] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NOTION_TOKEN = "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"
DATABASE_ID = "2e5653bb339a8069a3dcc3a6748a2ce3"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"

CATEGORIES = [
    "방송/영화/OTT",
    "게임/융복합",
    "애니/캐릭터",
    "만화/웹툰",
    "음악/공연",
    "패션/라이프스타일",
    "정책/규제"
]

# ============================================================
# [1단계] 소스 전면 교체 — 동남아 콘텐츠 전문 매체 + 키워드 쿼리
#
# 설계 원칙:
#   - 종합 뉴스 매체(CNA 메인, ST 메인 등) 제거 → 무관 기사 대량 유입 원인
#   - 각 소스는 "사이트 지정 + 콘텐츠 키워드"를 함께 사용
#   - 동남아 지역어 및 국가명을 쿼리에 명시
#   - 소스당 수집 상한: 3건 (Claude 호출 전 총량 통제)
#   - 전체 수집 상한: 35건
# ============================================================

SOURCES = [
    # --- 방송 / OTT ---
    {
        "name": "CNA Lifestyle",
        "query": "site:channelnewsasia.com/entertainment streaming OR OTT OR drama OR film",
        "cap": 3
    },
    {
        "name": "Variety Asia",
        "query": "site:variety.com Asia OR Singapore OR Malaysia OR Thailand OR Indonesia OR Vietnam OR Philippines streaming OR OTT OR film",
        "cap": 3
    },
    {
        "name": "Deadline Asia",
        "query": "site:deadline.com Asia OR Southeast Asia film OR streaming OR OTT OR drama",
        "cap": 3
    },
    {
        "name": "Screen Daily SEA",
        "query": "site:screendaily.com Southeast Asia OR Singapore OR Malaysia OR Thailand OR Indonesia",
        "cap": 3
    },

    # --- 게임 ---
    {
        "name": "Digital News Asia Game",
        "query": "site:digitalnewsasia.com game OR gaming OR esports",
        "cap": 3
    },
    {
        "name": "Niko Partners",
        "query": "site:nikopartners.com Southeast Asia OR SEA game OR gaming OR esports",
        "cap": 3
    },
    {
        "name": "The Magic Rain",
        "query": "site:themagicrain.com game OR gaming OR anime OR webtoon OR K-pop",
        "cap": 3
    },

    # --- 애니 / 캐릭터 ---
    {
        "name": "Anime News Network SEA",
        "query": "site:animenewsnetwork.com Singapore OR Malaysia OR Thailand OR Indonesia OR Vietnam OR Philippines",
        "cap": 3
    },

    # --- 만화 / 웹툰 ---
    {
        "name": "KrASIA Webtoon",
        "query": "site:kr.asia webtoon OR manhwa OR comic OR content",
        "cap": 3
    },

    # --- 음악 ---
    {
        "name": "Digital Music News SEA",
        "query": "site:digitalmusicnews.com Southeast Asia OR Singapore OR Malaysia OR Thailand K-pop OR streaming OR music market",
        "cap": 3
    },
    {
        "name": "Billboard Asia",
        "query": "site:billboard.com/music Southeast Asia OR Singapore OR Malaysia OR Thailand OR Indonesia OR Vietnam",
        "cap": 3
    },

    # --- 패션 / 라이프스타일 ---
    {
        "name": "Vogue SEA",
        "query": "site:vogue.com Singapore OR Malaysia OR Thailand OR Indonesia OR Philippines fashion OR lifestyle OR K-beauty",
        "cap": 3
    },

    # --- 정책 / 규제 ---
    {
        "name": "IMDA",
        "query": "site:imda.gov.sg content OR media OR digital OR streaming OR animation OR game",
        "cap": 3
    },
    {
        "name": "Bernama Content",
        "query": "site:bernama.com entertainment OR content OR film OR streaming OR music OR game",
        "cap": 3
    },
    {
        "name": "KrASIA Policy",
        "query": "site:kr.asia regulation OR policy OR law content OR media OR streaming OR entertainment",
        "cap": 3
    },
    {
        "name": "Malay Mail Entertainment",
        "query": "site:malaymail.com entertainment OR film OR music OR streaming OR K-drama OR K-pop",
        "cap": 3
    },
]

# ============================================================
# [2단계] 제목 기반 즉시 차단 — Claude 호출 전 사전 필터
#
# 설계 원칙:
#   - 블랙리스트 방식 대신 "콘텐츠 산업 무관" 패턴 차단
#   - URL 형태 제목, 사건/사고/범죄, 스포츠, 항공, 비관련 경제 차단
#   - 동남아 관련성 화이트리스트로 1차 확인
# ============================================================

# 동남아 국가 및 주요 도시 키워드 (하나라도 포함 시 통과)
SEA_KEYWORDS = [
    "singapore", "malaysia", "thailand", "indonesia", "vietnam", "philippines",
    "myanmar", "cambodia", "laos", "brunei", "east timor", "timor-leste",
    "bangkok", "jakarta", "kuala lumpur", "manila", "ho chi minh", "hanoi",
    "yangon", "phnom penh", "southeast asia", "sea region", "asean",
    "싱가포르", "말레이시아", "태국", "인도네시아", "베트남", "필리핀",
    "동남아", "아세안"
]

# 즉시 차단 패턴 (대소문자 무시)
BLOCK_PATTERNS = [
    # URL / 시스템 노이즈
    r"https?://", r"sitemap", r"feeds?\.", r"\.xml", r"rss",

    # 사건 / 사고 / 범죄
    r"\bmilitary\b", r"\bcrash(ed)?\b", r"\bmurder(ed)?\b", r"\bassault\b",
    r"\barrested?\b", r"\bconvicted?\b", r"\bsentenced?\b", r"\baccident\b",
    r"\be-waste\b", r"\btheft\b", r"\bscam\b", r"\bfraud\b",
    r"\bdied?\b", r"\bdeath\b", r"\bkilled?\b", r"\binjured?\b",
    r"\bexplosion\b", r"\bfire\b", r"\bflood\b", r"\bearthquake\b",

    # 스포츠
    r"\bworld cup\b", r"\bolympics?\b", r"\bfootball match\b",
    r"\bfriendly match\b", r"\bfifa\b", r"\bsoccer\b", r"\bbasketball\b",
    r"\btennis\b", r"\bgolf\b", r"\bformula\s*1\b", r"\bf1\b",
    r"\bmarathon\b", r"\bathletics\b",

    # 항공 / 교통 / 인프라
    r"\bairline\b", r"\bflight\b", r"\bairport\b", r"\bdoha\b",
    r"\bsuspension of service\b", r"\btrain derail\b", r"\bbus crash\b",

    # 비관련 경제 / 금융
    r"\bpetrol price\b", r"\belectricity (price|tariff)\b",
    r"\binterest rate\b", r"\bstock market\b", r"\bcurrency\b",
    r"\bexchange rate\b", r"\binflation\b", r"\bgdp\b",
    r"\bcentral bank\b", r"\bmonetary policy\b",

    # 지리정보 / 외교 / 군사
    r"\bgoogle maps?\b", r"\bmiddle east\b", r"\birak\b", r"\biraq\b",
    r"\bukraine\b", r"\bpalestine\b", r"\bwar\b", r"\bmissile\b",
    r"\bnuclear\b", r"\bsanctions?\b",

    # 의료 / 보건 (콘텐츠 무관)
    r"\bhospital\b", r"\bdoctor\b", r"\bmedical (error|malpractice)\b",
    r"\bvaccine\b", r"\bpandemic\b", r"\bepidemic\b",

    # 부동산 / 건설
    r"\bproperty (price|market)\b", r"\breal estate\b", r"\bconstruction\b",
    r"\bhousing (price|market)\b",
]

COMPILED_BLOCK = [re.compile(p, re.IGNORECASE) for p in BLOCK_PATTERNS]


def is_valid_title(title: str) -> bool:
    """
    제목 기반 즉시 차단 필터.
    차단 패턴에 하나라도 해당되면 False 반환.
    """
    if not title or len(title.strip()) < 10:
        return False
    for pattern in COMPILED_BLOCK:
        if pattern.search(title):
            return False
    return True


def is_sea_related(title: str) -> bool:
    """
    동남아 관련성 확인.
    SEA 키워드가 하나라도 포함되면 True.
    소스 자체가 동남아 전문 매체인 경우 True 반환 허용 (호출부에서 override 가능).
    """
    title_lower = title.lower()
    return any(kw in title_lower for kw in SEA_KEYWORDS)


def load_processed_links():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()


def save_processed_link(link):
    with open(DB_FILE, "a") as f:
        f.write(link + "\n")


def fetch_articles():
    """
    소스별 RSS 수집 → is_valid_title() → is_sea_related() → 최대 35건 반환.

    동남아 전문 매체(IMDA, Bernama, Digital News Asia 등)는
    is_sea_related() 체크를 면제 (소스 자체가 이미 동남아 한정).
    """
    SEA_NATIVE_SOURCES = {
        "IMDA", "Bernama Content", "Digital News Asia Game",
        "The Magic Rain", "Malay Mail Entertainment", "KrASIA Webtoon", "KrASIA Policy"
    }
    TOTAL_CAP = 35

    all_articles = []
    processed = load_processed_links()

    for source in SOURCES:
        if len(all_articles) >= TOTAL_CAP:
            break
        try:
            encoded_q = urllib.parse.quote(source["query"])
            url = (
                f"https://news.google.com/rss/search?"
                f"q={encoded_q}+when:1d&hl=en-SG&gl=SG&ceid=SG:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= source["cap"]:
                    break
                if len(all_articles) >= TOTAL_CAP:
                    break

                title = entry.get("title", "").strip()
                link = entry.get("link", "")

                # 중복 제거
                if link in processed:
                    continue

                # 2단계 사전 필터
                if not is_valid_title(title):
                    print(f"  [BLOCK-TITLE] {title[:60]}")
                    continue

                # 동남아 관련성 필터 (전문 매체는 면제)
                if source["name"] not in SEA_NATIVE_SOURCES:
                    if not is_sea_related(title):
                        print(f"  [BLOCK-SEA]   {title[:60]}")
                        continue

                img = ""
                if hasattr(entry, "media_thumbnail"):
                    img = entry.media_thumbnail[0]["url"]

                all_articles.append({
                    "title": title,
                    "link": link,
                    "image": img,
                    "source": source["name"]
                })
                count += 1

        except Exception as e:
            print(f"  [ERROR] {source['name']}: {e}")
            continue

    print(f"\n📥 사전 필터 통과: {len(all_articles)}건 → Claude 분석 시작\n")
    return all_articles


# ============================================================
# [3단계] Claude 프롬프트 — YES/NO 판단과 분류를 명확히 분리
#
# 설계 원칙:
#   - SUITABLE 판단을 최우선으로 배치 (분류보다 먼저 판단)
#   - "동남아 + 콘텐츠 산업" 두 조건 모두 충족해야 YES
#   - 관련성 60% 미만이면 NO 우선
#   - 구체적 YES/NO 예시 포함으로 모델 편향 교정
# ============================================================

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY:
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""당신은 KOCCA(한국콘텐츠진흥원) 동남아시아 콘텐츠 산업 동향 분석가입니다.

[임무]
아래 뉴스 기사가 KOCCA 동남아 동향 아카이브에 수록될 자격이 있는지 판단하고, 있다면 분류하십시오.

[수록 조건 — 두 가지 모두 충족해야 YES]
조건 A: 동남아시아 국가(싱가포르·말레이시아·태국·인도네시아·베트남·필리핀·미얀마·캄보디아 등) 관련 기사
조건 B: 아래 7개 카테고리 중 하나에 명확히 해당하는 콘텐츠 산업 기사
  - 방송/영화/OTT: 드라마, 영화, 스트리밍 플랫폼 전략, OTT 투자
  - 게임/융복합: 게임 산업, e스포츠, 게임 규제/투자
  - 애니/캐릭터: 애니메이션, 캐릭터 IP, 가상 인플루언서
  - 만화/웹툰: 웹툰, 만화, 그래픽노블 시장
  - 음악/공연: K-pop, 음악 스트리밍, 공연 산업, 아티스트 활동
  - 패션/라이프스타일: 패션, K-뷰티, 라이프스타일 브랜드
  - 정책/규제: 콘텐츠 관련 법률·정책·진흥 기금·정부 기관 발표

[즉시 NO 처리 — 하나라도 해당되면 무조건 NO]
- 스포츠(축구·농구·테니스·골프·e스포츠 외 일반 스포츠 경기)
- 사건/사고/범죄/재해
- 항공·교통·인프라
- 비관련 경제(금리·환율·부동산·유가)
- 의료·보건
- 외교·군사·분쟁
- 동남아 기사라도 콘텐츠 산업과 무관한 일반 뉴스

[판단 예시]
YES → "Netflix increases content investment in Southeast Asia" (OTT 전략, 동남아)
YES → "Singapore IMDA launches animation co-production fund" (정책, 동남아)
YES → "K-drama popularity drives tourism surge in Thailand" (방송/OTT, 동남아)
YES → "Indonesian webtoon platform Ciayo acquired by Korean firm" (웹툰, 동남아)
YES → "Malaysia introduces new content rating regulation for streaming" (정책, 동남아)
NO  → "Singapore Airlines suspends route to Doha" (항공, 콘텐츠 무관)
NO  → "Chinese influencer dies during livestream" (사망 사고)
NO  → "Thailand GDP growth forecast revised upward" (비관련 경제)
NO  → "Philippines wins gold at SEA Games basketball" (스포츠)
NO  → "Malaysia petrol prices unchanged this week" (비관련 경제)

[응답 형식 — 반드시 아래 순서와 형식을 지키세요]
SUITABLE: YES 또는 NO
CATEGORY: {" / ".join(CATEGORIES)} 중 하나 (SUITABLE이 NO이면 "해당없음")
AI_SUMMARY: 기사 핵심을 한 문장으로 요약 (SUITABLE이 NO이면 "해당없음")
DETAILED_SUMMARY: 산업적 시사점 중심 3문장 요약, 한국 콘텐츠 기업 관점 포함 (SUITABLE이 NO이면 "해당없음")
"""

    prompt = f"제목: {article['title']}\n링크: {article['link']}\n소스: {article.get('source', '')}"

    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        res = msg.content[0].text
        data = {"cat": "기타", "ai": "", "det": "", "ok": False}

        for line in res.split("\n"):
            line = line.strip()
            if line.startswith("SUITABLE:"):
                data["ok"] = "YES" in line.upper()
            elif line.startswith("CATEGORY:"):
                data["cat"] = line.split(":", 1)[1].strip()
            elif line.startswith("AI_SUMMARY:"):
                data["ai"] = line.split(":", 1)[1].strip()
            elif line.startswith("DETAILED_SUMMARY:"):
                data["det"] = line.split(":", 1)[1].strip()

        verdict = "✅ YES" if data["ok"] else "❌ NO"
        print(f"  {verdict} [{data['cat']}] {article['title'][:50]}")
        return data

    except Exception as e:
        print(f"  [Claude ERROR] {e}")
        return None


def send_to_notion(article, ai_data):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    img_url = article["image"] if article["image"] else "https://www.notion.so/icons/news_gray.svg"
    today_date = datetime.datetime.now().strftime("%Y-%m-%d")

    properties = {
        "제목": {"title": [{"text": {"content": article["title"]}}]},
        "태그": {"multi_select": [{"name": "News"}, {"name": ai_data["cat"]}]},
        "URL": {"url": article["link"]},
        "Summary": {"rich_text": [{"text": {"content": ai_data["det"]}}]},
        "생성일자": {"date": {"start": today_date}},
        "이미지": {"files": [{"name": "Thumbnail", "external": {"url": img_url}}]}
    }

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"  📌 Notion 저장: {article['title'][:40]}...")
    else:
        print(f"  ❌ Notion 실패: {response.text[:100]}")


def update_github_markdown(results):
    today = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    header = "# 📰 KOCCA 동남아 콘텐츠 산업 동향 아카이브\n\n"
    new_entry = f"## 📅 {today} 업데이트\n\n"

    if not results:
        new_entry += "> 📭 **KOCCA 선정 기준에 부합하는 새로운 콘텐츠가 없습니다.**\n\n"
    else:
        # 카테고리별 정렬
        cat_order = {c: i for i, c in enumerate(CATEGORIES)}
        results_sorted = sorted(results, key=lambda x: cat_order.get(x["cat"], 99))
        for item in results_sorted:
            new_entry += (
                f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n"
                f"  * 💡 {item['ai']}\n"
            )

    existing = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + new_entry + "\n---\n" + existing)

    print(f"\n✅ MARKET_ARCHIVE.md 업데이트 완료 ({len(results)}건 수록)")


def main():
    print("=" * 60)
    print("KOCCA 동남아 콘텐츠 산업 동향 수집 시작")
    print("=" * 60)

    articles = fetch_articles()

    combined_list = []
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res["ok"]:
            send_to_notion(art, ai_res)
            save_processed_link(art["link"])
            combined_list.append({**art, **ai_res})
        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"수집 완료: {len(combined_list)}건 수록 / {len(articles)}건 분석")
    print("=" * 60)

    update_github_markdown(combined_list)


if __name__ == "__main__":
    main()
