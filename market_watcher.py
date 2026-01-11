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
# 사용자님이 인증해주신 토큰과 하이픈을 제거한 순수 DB ID
NOTION_TOKEN = "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"
DATABASE_ID = "2e5653bb339a80a4b5a3e75043b8cb65"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"
CATEGORIES = ["방송/영화", "게임/융복합", "애니/캐릭터", "만화/웹툰", "음악", "패션", "통합"]

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
            for entry in feed.entries[:3]:
                if entry.link not in processed:
                    img = ""
                    if hasattr(entry, 'media_thumbnail'): img = entry.media_thumbnail[0]['url']
                    all_articles.append({'title': entry.title, 'link': entry.link, 'image': img})
        except: continue
    return all_articles

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"당신은 KOCCA 분석가입니다. 결과를 반드시 CATEGORY, AI_SUMMARY, DETAILED_SUMMARY, SUITABLE(YES/NO) 형식으로 응답하세요.\n\n제목: {article['title']}\n카테고리 후보: {', '.join(CATEGORIES)}"
    try:
        msg = client.messages.create(model="claude-3-haiku-20240307", max_tokens=800, messages=[{"role": "user", "content": prompt}])
        res = msg.content[0].text
        data = {'cat': '통합', 'ai': '', 'det': '', 'ok': False}
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
    
    # image_075fad.png 컬럼명과 100% 일치 매핑
    properties = {
        "제목": {"title": [{"text": {"content": article['title']}}]},
        "태그": {"multi_select": [{"name": "News"}, {"name": ai_data['cat']}]},
        "URL": {"url": article['link']},
        "Summary": {"rich_text": [{"text": {"content": ai_data['det']}}]}
    }
    
    if article['image']:
        properties["이미지"] = {"files": [{"name": "Thumbnail", "external": {"url": article['image']}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"❌ Notion 전송 실패 ({response.status_code}): {response.text}")
        response.raise_for_status() 
    print(f"✅ Notion 전송 성공: {article['title'][:20]}...")

def update_github_markdown(results):
    today = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 KOCCA 글로벌 콘텐츠 산업 동향 아카이브\n\n"
    new_entry = f"## 📅 {today} 업데이트\n\n"
    if not results:
        new_entry += "> 📭 **오늘 업데이트 할 새로운 콘텐츠가 없습니다.**\n\n"
    else:
        for item in results:
            new_entry += f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n  * 💡 {item['ai']}\n"
    
    existing = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f: existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f: f.write(header + new_entry + "\n---\n" + existing)

def main():
    articles = fetch_articles()
    print(f"{len(articles)}개 뉴스 분석 및 노션 전송 시작...")
    combined_list = []
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res['ok']:
            try:
                send_to_notion(art, ai_res)
                save_processed_link(art['link'])
                combined_list.append({**art, **ai_res})
            except Exception as e:
                print(f"⚠️ 전송 오류 발생: {e}")
            time.sleep(0.5)
    update_github_markdown(combined_list)

if __name__ == "__main__":
    main()