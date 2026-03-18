import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests
import re

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
NOTION_TOKEN      = "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"
DATABASE_ID       = "2e5653bb339a8069a3dcc3a6748a2ce3"
ARCHIVE_FILE      = "MARKET_ARCHIVE.md"
DB_FILE           = "processed_links.txt"

CATEGORIES = [
    "방송/영화/OTT",
    "게임/융복합",
    "애니/캐릭터",
    "만화/웹툰",
    "음악/공연",
    "패션/라이프스타일",
    "정책/규제",
]

# ─────────────────────────────────────────────
# 소스 — 동남아 콘텐츠 전문 매체만
#
# 핵심 원칙
#   1. 종합 뉴스 매체(CNA 메인, ST 메인, Mothership, Malay Mail 전체, Bernama 전체) 완전 제거
#   2. 각 쿼리에 반드시 콘텐츠 키워드 + 국가명 포함
#   3. 소스당 최대 2건 → 전체 최대 30건 → Claude 필터 후 목표 10~15건
# ─────────────────────────────────────────────
SOURCES = [
    # 방송 / OTT
    {
        "name": "CNA Entertainment",
        "query": "site:channelnewsasia.com/entertainment",
        "cap": 2,
    },
    {
        "name": "Variety Asia",
        "query": "site:variety.com (Singapore OR Malaysia OR Thailand OR Indonesia OR Vietnam OR Philippines) (streaming OR OTT OR drama OR film OR K-drama)",
        "cap": 2,
    },
    {
        "name": "Deadline Asia",
        "query": "site:deadline.com (Southeast Asia OR Singapore OR Malaysia OR Thailand OR Indonesia) (film OR streaming OR OTT)",
        "cap": 2,
    },

    # 게임
    {
        "name": "Digital News Asia",
        "query": "site:digitalnewsasia.com (game OR gaming OR esports OR e-sports)",
        "cap": 2,
    },
    {
        "name": "Niko Partners",
        "query": "site:nikopartners.com (Southeast Asia OR SEA) (game OR gaming OR esports)",
        "cap": 2,
    },
    {
        "name": "The Magic Rain",
        "query": "site:themagicrain.com (game OR gaming OR anime OR webtoon OR K-pop OR K-drama)",
        "cap": 2,
    },

    # 애니 / 캐릭터
    {
        "name": "Anime News Network SEA",
        "query": "site:animenewsnetwork.com (Singapore OR Malaysia OR Thailand OR Indonesia OR Vietnam OR Philippines)",
        "cap": 2,
    },

    # 만화 / 웹툰
    {
        "name": "KrASIA",
        "query": "site:kr.asia (webtoon OR manhwa OR K-content OR K-pop OR OTT OR streaming OR entertainment)",
        "cap": 2,
    },

    # 음악
    {
        "name": "Digital Music News SEA",
        "query": "site:digitalmusicnews.com (Southeast Asia OR Singapore OR Malaysia OR Thailand OR Indonesia) (K-pop OR music market OR streaming)",
        "cap": 2,
    },

    # 패션 / 라이프스타일
    {
        "name": "Vogue SEA",
        "query": "site:vogue.com (Singapore OR Malaysia OR Thailand OR Indonesia OR Philippines) (fashion OR K-beauty OR lifestyle)",
        "cap": 2,
    },

    # 정책 / 규제 — 전문 기관 / 섹션 한정
    {
        "name": "IMDA",
        "query": "site:imda.gov.sg (content OR media OR streaming OR animation OR game OR digital entertainment)",
        "cap": 2,
    },
    {
        "name": "Bernama Entertainment",
        "query": "site:bernama.com (film OR drama OR music OR streaming OR entertainment industry OR content industry OR webtoon OR animation OR game)",
        "cap": 2,
    },
    {
        "name": "Malay Mail Entertainment",
        "query": "site:malaymail.com/entertainment",
        "cap": 2,
    },
]

# ─────────────────────────────────────────────
# 사전 필터 — Claude 호출 전 제목 기반 즉시 차단
# ─────────────────────────────────────────────

SEA_WHITELIST = [
    "singapore", "malaysia", "thailand", "indonesia", "vietnam", "philippines",
    "myanmar", "cambodia", "laos", "brunei", "asean", "southeast asia",
    "bangkok", "jakarta", "kuala lumpur", "manila", "ho chi minh", "hanoi",
    "yangon", "phnom penh",
    "싱가포르", "말레이시아", "태국", "인도네시아", "베트남", "필리핀", "동남아", "아세안",
]

SEA_NATIVE = {
    "IMDA", "Digital News Asia", "The Magic Rain",
    "Bernama Entertainment", "Malay Mail Entertainment",
    "Anime News Network SEA", "KrASIA",
}

_BLOCK_RAW = [
    # URL / 시스템 노이즈
    r"https?://", r"\bsitemap\b", r"feeds?\.(xml|rss)", r"\.xml\b",

    # 사건 / 사고 / 범죄 / 재해
    r"\bmilitary\b", r"\bcrash(ed|es)?\b", r"\bmurder(ed|s)?\b",
    r"\bassault(ed|s)?\b", r"\barrested?\b", r"\bconvicted?\b",
    r"\bsentenced?\b", r"\baccident\b", r"\be-waste\b",
    r"\btheft\b", r"\bscam\b", r"\bfraud\b",
    r"\bdied?\b", r"\bdeath\b", r"\bkilled?\b", r"\binjured?\b",
    r"\bexplosion\b", r"\bflood(ing|s)?\b", r"\bearthquake\b",
    r"\bcane\b", r"\bjail\b", r"\bprison\b",
    r"\bsexually assaulted?\b", r"\bdrug abuse\b",

    # 전쟁 / 외교 / 군사
    r"\bwar\b", r"\bmissile\b", r"\bnuclear\b", r"\bsanctions?\b",
    r"\bmiddle east\b", r"\biraq\b", r"\bukraine\b",
    r"\bpalestine\b", r"\bgaza\b", r"\bisrael\b", r"\biran\b",
    r"\brussia[n]?\b", r"\bzelensky\b", r"\bputin\b",
    r"\bnato\b", r"\bkharg\b", r"\bhormuz\b", r"\bstraits of\b",
    r"\brafah\b", r"\bhezbollah\b", r"\bhamas\b",

    # 스포츠
    r"\bworld cup\b", r"\bolympics?\b", r"\bfootball match\b",
    r"\bfriendly match\b", r"\bfifa\b", r"\bsoccer\b",
    r"\bbasketball\b", r"\btennis\b", r"\bgolf\b",
    r"\bformula\s*1\b", r"\bmarathon\b", r"\bathletics\b",
    r"\bbadminton\b", r"\bshuttler\b", r"\bswiss open\b",
    r"\baustralia open\b", r"\bsea games\b", r"\bquarter.final\b",

    # 항공 / 교통 / 인프라
    r"\bairline\b", r"\bflight\b", r"\bairport\b",
    r"\bdoha\b", r"\bcathay\b", r"\bfuel surcharge\b",
    r"\btrain derail\b", r"\bpmd\b",

    # 비관련 경제 / 금융
    r"\bpetrol price\b", r"\bron9[57]\b", r"\bdiesel price\b",
    r"\belectricity (price|tariff|bill)\b",
    r"\binterest rate\b", r"\bstock(s| market)\b",
    r"\bcurrency\b", r"\bexchange rate\b",
    r"\binflation\b", r"\bgdp\b", r"\bcentral bank\b",
    r"\bmonetary policy\b", r"\bhedge fund\b",
    r"\binsider trading\b", r"\bcrypto\b", r"\bbitcoin\b",
    r"\breal estate\b", r"\bproperty (price|market)\b",
    r"\bhousing (price|loan)\b", r"\bblue chips?\b",

    # 에너지 / 인프라 (콘텐츠 무관)
    r"\bdata cent(re|er)\b", r"\blng\b", r"\benergy stock\b",
    r"\bgreen energy\b", r"\bsolar\b", r"\bpower plant\b",
    r"\bsembcorp\b", r"\bmwh\b",

    # 의료 / 보건
    r"\bhospital\b", r"\bsurgery\b", r"\bmedical error\b",
    r"\bmalpractice\b", r"\bvaccine\b", r"\bpandemic\b",
    r"\bepidemic\b", r"\bkidney\b", r"\barteries\b",

    # 정치 / 선거 / 안보 사건 (콘텐츠 무관)
    r"\belection\b", r"\bgeneral election\b", r"\bvoting\b",
    r"\bparliament (debate|vote|passes)\b",
    r"\bprime minister resign\b", r"\bcabinet reshuffle\b",
    r"\bdrone (attack|strike)\b", r"\bembassy attack\b",
    r"\bdiplomatic (incident|row|crisis)\b",

    # 게임 플랫폼 악용 범죄 (게임 산업 기사 아님)
    r"\bvirtual kidnap\b", r"\bsecuestro virtual\b",
    r"\bonline predator\b", r"\bchild (grooming|abuse) online\b",

    # 기타 완전 무관
    r"\bgoogle maps?\b", r"\belephant\b", r"\bwill (contest|dispute)\b",
    r"\bwork.from.home\b", r"\bcost saving\b", r"\boverproduction\b",
    r"\biftar\b", r"\bramadan\b", r"\breusable bag\b",
    r"\bpizza hut\b", r"\bprovidore\b", r"\bbeauty spa\b",
    r"\bimf warns?\b", r"\bdubai airport\b",
]
BLOCK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _BLOCK_RAW]


def is_valid_title(title: str) -> bool:
    if not title or len(title.strip()) < 10:
        return False
    for pat in BLOCK_PATTERNS:
        if pat.search(title):
            return False
    return True


def is_sea_related(title: str) -> bool:
    """동남아 직접 관련 OR K-콘텐츠 글로벌 위상 신호 — 둘 중 하나면 통과."""
    t = title.lower()
    # 1) 동남아 직접 언급
    if any(kw in t for kw in SEA_WHITELIST):
        return True
    # 2) K-콘텐츠 글로벌 위상 신호
    #    지역이 서구여도 K-팝/K-드라마의 국제적 영향력을 담은 기사는 유효
    #    예: "[뉴욕] K팝 데몬헌터스 그래미", "[프랑스] 박찬욱 칸 심사위원장"
    K_GLOBAL = [
        "k-pop", "k-drama", "k-content", "k-beauty", "k-fashion",
        "korean film", "korean series", "korean content", "korean wave",
        "hallyu", "bts", "blackpink", "stray kids", "kocca",
        "park chan-wook", "bong joon-ho",
    ]
    return any(kw in t for kw in K_GLOBAL)


# ─────────────────────────────────────────────
# 수집
# ─────────────────────────────────────────────
def load_processed_links():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()


def save_processed_link(link):
    with open(DB_FILE, "a") as f:
        f.write(link + "\n")


def fetch_articles():
    TOTAL_CAP = 30
    processed = load_processed_links()
    all_articles = []
    stats = {"dup": 0, "title": 0, "sea": 0, "pass": 0}

    for source in SOURCES:
        if len(all_articles) >= TOTAL_CAP:
            break
        try:
            encoded_q = urllib.parse.quote(source["query"])
            url = (
                f"https://news.google.com/rss/search?"
                f"q={encoded_q}+when:1d&hl=en-SG&gl=SG&ceid=SG:en"
            )
            feed  = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= source["cap"] or len(all_articles) >= TOTAL_CAP:
                    break

                title = entry.get("title", "").strip()
                link  = entry.get("link", "")

                if link in processed:
                    stats["dup"] += 1
                    continue

                if not is_valid_title(title):
                    stats["title"] += 1
                    print(f"  [BLOCK-TITLE] {title[:70]}")
                    continue

                if source["name"] not in SEA_NATIVE and not is_sea_related(title):
                    stats["sea"] += 1
                    print(f"  [BLOCK-SEA]   {title[:70]}")
                    continue

                img = ""
                if hasattr(entry, "media_thumbnail"):
                    img = entry.media_thumbnail[0]["url"]

                all_articles.append({
                    "title":  title,
                    "link":   link,
                    "image":  img,
                    "source": source["name"],
                })
                stats["pass"] += 1
                count += 1

        except Exception as e:
            print(f"  [ERROR] {source['name']}: {e}")

    print(
        f"\n📥 수집 결과 — 중복제외:{stats['dup']} / "
        f"제목차단:{stats['title']} / SEA차단:{stats['sea']} / "
        f"통과:{stats['pass']}건 → Claude 분석 시작\n"
    )
    return all_articles


# ─────────────────────────────────────────────
# Claude 분석
# ─────────────────────────────────────────────
def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY:
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""당신은 KOCCA(한국콘텐츠진흥원) 동남아시아 콘텐츠 산업 동향 분석가입니다.

[수록 조건 — 반드시 두 조건 모두 충족해야 YES]
A. 동남아시아(싱가포르·말레이시아·태국·인도네시아·베트남·필리핀·미얀마·캄보디아 등) 관련 기사
   OR 한국 콘텐츠·아티스트의 글로벌 위상을 다룬 기사 (지역 무관)
B. 아래 7개 카테고리 중 하나에 명확히 해당하는 콘텐츠 산업 기사
   방송/영화/OTT  |  게임/융복합  |  애니/캐릭터  |  만화/웹툰  |  음악/공연  |  패션/라이프스타일  |  정책/규제

[즉시 NO — 하나라도 해당되면 A·B 조건 무관하게 NO]
- 전쟁·군사·외교 사건 (러시아, 이란, 중동, 이스라엘, 우크라이나 등)
- 스포츠 경기 결과 (배드민턴, 축구, 농구, 골프, 테니스 등)
- 사건·사고·범죄·재해 (드론 공격, 사기, 납치, 살인 등)
- 항공·교통·에너지·인프라
- 비관련 경제 (금리·환율·유가·주가·부동산)
- 의료·보건
- 선거·총선·의회 정치 사건 (콘텐츠 정책 기사는 제외)
- 동남아 기사라도 콘텐츠 산업과 무관한 일반 사회 뉴스

[판단 예시]
YES → "Netflix increases content investment in Southeast Asia"          ← SEA + OTT
YES → "Singapore IMDA launches animation co-production fund"           ← SEA + 정책
YES → "K-drama popularity drives tourism surge in Thailand"            ← SEA + K-콘텐츠
YES → "Malaysia introduces new content rating regulation for streaming" ← SEA + 정책
YES → "Stray Kids film tops global box office"                         ← K-콘텐츠 글로벌 위상
YES → "Park Chan-wook appointed Cannes jury president"                 ← K-크리에이터 위상
NO  → "Thailand general election results"                              ← 선거 (콘텐츠 무관)
NO  → "Singapore Airlines suspends Doha route"                         ← 항공
NO  → "Iran war causes oil price spike"                                ← 전쟁·에너지
NO  → "Malaysia badminton player wins tournament"                      ← 스포츠
NO  → "Singapore doctor charged over surgery"                          ← 의료·범죄
NO  → "Sweden local drama series premiere"                             ← 서구 내수, SEA·K-콘텐츠 무관
NO  → "Russia OTT platform viewer statistics"                          ← 러시아 내수
NO  → "Virtual kidnapping via game platform"                           ← 게임 악용 범죄 (산업 기사 아님)

[응답 형식 — 첫 줄 반드시 SUITABLE, 순서 고정]
SUITABLE: YES 또는 NO
CATEGORY: {" / ".join(CATEGORIES)} 중 하나 (NO이면 해당없음)
AI_SUMMARY: 한 문장 요약 (NO이면 해당없음)
DETAILED_SUMMARY: 산업적 시사점 3문장, 한국 콘텐츠 기업 관점 포함 (NO이면 해당없음)"""

    prompt = f"제목: {article['title']}\n링크: {article['link']}\n소스: {article.get('source', '')}"

    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        res  = msg.content[0].text
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

        verdict = "✅ YES" if data["ok"] else "❌ NO "
        print(f"  {verdict} [{data['cat']:12s}] {article['title'][:55]}")
        return data

    except Exception as e:
        print(f"  [Claude ERROR] {e}")
        return None


# ─────────────────────────────────────────────
# Notion 저장
# ─────────────────────────────────────────────
def send_to_notion(article, ai_data):
    headers = {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Content-Type":   "application/json",
        "Notion-Version": "2022-06-28",
    }
    img_url    = article["image"] if article["image"] else "https://www.notion.so/icons/news_gray.svg"
    today_date = datetime.datetime.now().strftime("%Y-%m-%d")

    properties = {
        "제목":     {"title":        [{"text": {"content": article["title"]}}]},
        "태그":     {"multi_select": [{"name": "News"}, {"name": ai_data["cat"]}]},
        "URL":      {"url":          article["link"]},
        "Summary":  {"rich_text":    [{"text": {"content": ai_data["det"]}}]},
        "생성일자": {"date":         {"start": today_date}},
        "이미지":   {"files":        [{"name": "Thumbnail", "external": {"url": img_url}}]},
    }
    payload  = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    response = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)

    if response.status_code == 200:
        print(f"  📌 Notion 저장: {article['title'][:40]}")
    else:
        print(f"  ❌ Notion 실패: {response.text[:100]}")


# ─────────────────────────────────────────────
# Markdown 업데이트
# ─────────────────────────────────────────────
def update_github_markdown(results):
    today  = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    header = "# 📰 KOCCA 동남아 콘텐츠 산업 동향 아카이브\n\n"
    entry  = f"## 📅 {today} 업데이트\n\n"

    if not results:
        entry += "> 📭 **KOCCA 선정 기준에 부합하는 새로운 콘텐츠가 없습니다.**\n\n"
    else:
        order   = {c: i for i, c in enumerate(CATEGORIES)}
        sorted_ = sorted(results, key=lambda x: order.get(x["cat"], 99))
        for item in sorted_:
            entry += f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n  * 💡 {item['ai']}\n"

    existing = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + entry + "\n---\n" + existing)

    print(f"\n✅ MARKET_ARCHIVE.md 업데이트 완료 ({len(results)}건 수록)")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("KOCCA 동남아 콘텐츠 산업 동향 수집")
    print("=" * 60)

    articles = fetch_articles()
    results  = []

    for art in articles:
        ai = analyze_and_classify(art)
        if ai and ai["ok"]:
            send_to_notion(art, ai)
            save_processed_link(art["link"])
            results.append({**art, **ai})
        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"수집 완료: {len(results)}건 수록 / {len(articles)}건 분석")
    print("=" * 60)

    update_github_markdown(results)


if __name__ == "__main__":
    main()
