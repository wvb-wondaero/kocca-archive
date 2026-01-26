import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests
import json

# --- [설정 및 비밀키] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") 
NOTION_TOKEN = "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"
DATABASE_ID = "2e5653bb339a8069a3dcc3a6748a2ce3"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"
CATEGORIES = ["방송/영화/OTT", "게임/융복합", "애니/캐릭터", "만화/웹툰", "음악/공연", "패션/라이프스타일"]

SOURCES = [
    {"name": "Mothership.SG", "query": "site:mothership.sg", "type": "search"},
    {"name": "CNA", "query": "site:channelnewsasia.com", "type": "search"},
    {"name": "Straits Times", "query": "site:straitstimes.com", "type": "search"},
    {"name": "Today Online", "query": "site:todayonline.com", "type": "search"},
    {"name": "IMDA", "query": "site:imda.gov.sg", "type": "search"}
]

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
    
    system_prompt = f"""당신은 KOCCA(한국콘텐츠진흥원)의 글로벌 산업 분석가입니다. 
    당신의 임무는 뉴스 기사가 한국 콘텐츠 산업에 주는 시사점이 있는지 판단하는 것입니다.

    [선정 기준 - 하나라도 해당되면 YES]
    1. 플랫폼/거대 자본의 전략: OTT(넷플릭스 등), 테크 기업의 콘텐츠 투자 및 현지 전략.
    2. 정부/규제: 현지 정부의 저작권법, 콘텐츠 규제, 진흥 정책 변화.
    3. 시장 트렌드: IP 확장(웹툰의 드라마화 등), K-콘텐츠 현지 반응, 라이선싱 시장 변화.

    [배제 기준 - 하나라도 해당되면 NO]
    1. 단순 가십: 연예인 개인 신상, 단순 시상식 참석.
    2. 일회성 이벤트: 단순 전시회, 티켓 예매 공지.
    3. 일반 기술: 콘텐츠 산업과 직접 관련 없는 일반 IT 기기나 테크 뉴스.

    응답은 반드시 아래 형식을 지키세요:
    CATEGORY: {', '.join(CATEGORIES)} 중 하나 선택
    AI_SUMMARY: 기사 내용을 한 줄로 핵심 요약
    DETAILED_SUMMARY: 산업적 시사점 중심의 3문장 요약 (한국 콘텐츠 기업이 참고할 점 포함)
    SUITABLE: YES 또는 NO
    """

    prompt = f"제목: {article['title']}\n링크: {article['link']}"
    
    try:
        msg = client.messages.create(
            model="claude-3-haiku-20240307", 
            max_tokens=1000, 
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        res = msg.content[0].text
        data = {'cat': '기타', 'ai': '', 'det': '', 'ok': False}
        for line in res.split('\n'):
            if "CATEGORY:" in line: data['cat'] = line.split(":")[1].strip()
            if "AI_SUMMARY:" in line: data['ai'] = line.split(":")[1].strip()
            if "DETAILED_SUMMARY:" in line: data['det'] = line.split(":")[1].strip()
            if "SUITABLE: YES" in line.upper(): data['ok'] = True
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
    
    # 오늘 날짜 생성 (YYYY-MM-DD 형식)
    today_date = datetime.datetime.now().strftime('%Y-%m-%d')
    
    properties = {
        "제목": {"title": [{"text": {"content": article['title']}}]},
        "태그": {"multi_select": [{"name": "News"}, {"name": ai_data['cat']}]},
        "URL": {"url": article['link']},
        "Summary": {"rich_text": [{"text": {"content": ai_data['det']}}]},
        "생성일자": {"date": {"start": today_date}} # 🔗 생성일자 추가됨
    }
    properties["이미지"] = {"files": [{"name": "Thumbnail", "external": {"url": img_url}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200: print(f"✅ Notion: {article['title'][:20]}...")
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
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f: existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f: f.write(header + new_entry + "\n---\n" + existing)

def main():
    articles = fetch_articles()
    print(f"{len(articles)}개 뉴스 분석 시작 (KOCCA 필터 적용)...")
    combined_list = []
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res['ok']:
            send_to_notion(art, ai_res)
            save_processed_link(art['link'])
            combined_list.append({**art, **ai_res})
            time.sleep(0.5)
    update_github_markdown(combined_list)

if __name__ == "__main__":
    main()