import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests
from requests.auth import HTTPBasicAuth
import json

# --- [설정 및 비밀키] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") 
JIRA_EMAIL = "cs@wiltvb.com"
JIRA_API_TOKEN = "ATATT3xFfGF0-C9fwMahIjdZRnR6n8KlWJSRbd3Njirhn1lJMT9J4MqJU6YiwQYdRfTeDP7M3oiiTSgoDEmAyBwwuK7FtH7rAQVCQN2mwgROkZBbJDx59BPo5L_F_tYeMXd5ANXRlsKzX_F4IlRHi59E0Q671wX5sDKIfZgHZEuOnRvRqY9nETE=321C6984"
JIRA_DOMAIN = "wiltvb.atlassian.net"

ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"
CATEGORIES = ["방송·영화·OTT", "게임·융복합", "애니·캐릭터", "만화·웹툰·스토리", "음악", "패션", "통합(정책 등)"]

SOURCES = [
    {"name": "CNA Lifestyle", "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511", "type": "rss"},
    {"name": "Variety", "url": "https://variety.com/feed/", "type": "rss"},
    {"name": "Malay Mail", "url": "https://www.malaymail.com/rss/malaysia", "type": "rss"},
    {"name": "The Magic Rain", "url": "https://themagicrain.com/feed/", "type": "rss"},
    {"name": "Digital News Asia", "url": "https://www.digitalnewsasia.com/rss.xml", "type": "rss"},
    {"name": "Yahoo News Malaysia", "url": "https://malaysia.news.yahoo.com/rss", "type": "rss"},
    {"name": "WebProNews", "url": "https://www.webpronews.com/feed/", "type": "rss"},
    {"name": "The Star (ASEANPlus)", "url": "https://www.thestar.com.my/rss/aseanplus", "type": "rss"},
    {"name": "The Straits Times", "url": "https://www.straitstimes.com/news/world/rss.xml", "type": "rss"},
    {"name": "New Straits Times", "url": "https://www.nst.com.my/news/world/rss", "type": "rss"},
    {"name": "Digital Music News", "url": "https://www.digitalmusicnews.com/feed/", "type": "rss"},
    {"name": "Travel And Tour World", "url": "http://feeds.feedburner.com/travelandtourworld/tourismnews", "type": "rss"},
    {"name": "Bernama", "url": "http://mrembm.bernama.com/rss.php", "type": "rss"},
    {"name": "Nabalune News", "query": "site:nabalunews.com", "type": "search"},
    {"name": "iNews ZoomBangla", "query": "site:inews.zoombangla.com", "type": "search"},
    {"name": "AP News", "query": "site:apnews.com", "type": "search"},
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
            if source["type"] == "rss":
                feed = feedparser.parse(source["url"])
            else:
                encoded_q = urllib.parse.quote(source["query"])
                url = f"https://news.google.com/rss/search?q={encoded_q}+when:1d&hl=en-SG&gl=SG&ceid=SG:en"
                feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                if entry.link not in processed:
                    all_articles.append({'title': entry.title, 'link': entry.link, 'source': source['name']})
        except: continue
    return all_articles

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"당신은 KOCCA 산업 분석가입니다. 다음 뉴스를 분석해 한국어로 요약하고 다음 카테고리 중 하나로 분류하세요: {', '.join(CATEGORIES)}\n\n제목: {article['title']}\n링크: {article['link']}\n\n결과 형식:\nCATEGORY: 카테고리명\nSUMMARY: 한국어 요약\nSUITABLE: YES 또는 NO"
    try:
        msg = client.messages.create(model="claude-3-haiku-20240307", max_tokens=600, messages=[{"role": "user", "content": prompt}])
        res = msg.content[0].text
        data = {'cat': '통합(정책 등)', 'sum': '요약 실패', 'ok': False}
        for line in res.split('\n'):
            if "CATEGORY:" in line: data['cat'] = line.split(":")[1].strip()
            if "SUMMARY:" in line: data['sum'] = line.split(":")[1].strip()
            if "SUITABLE:" in line: data['ok'] = "YES" in line.upper()
        return data
    except: return None

def send_to_jira(article, ai_data):
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    safe_label = ai_data['cat'].replace("·", "_").replace(" ", "_").replace("(", "").replace(")", "").replace(",", "")
    
    # 🔗 핵심 솔루션: 에러가 발생하는 커스텀 필드 대신 'Description'에 모든 내용을 ADF 형식으로 넣음
    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "issuetype": {"name": "Task"},
            "summary": f"[{ai_data['cat']}] {article['title']}",
            "labels": [safe_label, "KOCCA_Bot"],
            "description": {
                "type": "doc", "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "🔗 원문 링크: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": article['link'], "marks": [{"type": "link", "attrs": {"href": article['link']}}]}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "📝 AI 요약: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": ai_data['sum']}]}
                ]
            }
        }
    })
    try:
        response = requests.post(url, data=payload, headers=headers, auth=auth)
        if response.status_code == 201: print(f"✅ Jira 성공: {article['title']}")
        else: print(f"❌ Jira 실패 ({response.status_code}): {response.text}")
    except Exception as e: print(f"⚠️ 네트워크 오류: {e}")

def update_github_markdown(combined_results):
    today = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 KOCCA 글로벌 콘텐츠 산업 동향 아카이브\n\n" # 제목도 KOCCA용으로 변경
    
    # 신규 항목 생성
    new_entry = f"## 📅 {today} 업데이트\n\n"
    for item in combined_results:
        # [카테고리] 제목 (링크) 형식으로 더 직관적으로 변경
        new_entry += f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n"
        new_entry += f"  * 💡 {item['sum']}\n" # 요약 앞에 전구 아이콘 추가
    
    existing_content = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            full_text = f.read()
            # 기존 헤더를 제거하고 내용만 추출
            existing_content = full_text.replace(header, "")
    
    # 새 헤더 + 신규 내용 + 기존 내용 순으로 저장 (최신글이 맨 위로)
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + new_entry + "\n---\n" + existing_content)

def main():
    articles = fetch_articles()
    print(f"새로운 기사 {len(articles)}개 발견")
    combined_list = []
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res.get('ok'):
            send_to_jira(art, ai_res)
            save_processed_link(art['link'])
            combined_list.append({**art, **ai_res})
            time.sleep(1)
    if combined_list: update_github_markdown(combined_list)

if __name__ == "__main__":
    main()