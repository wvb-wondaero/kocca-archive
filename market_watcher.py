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

# 지라 필드 ID (사용자 지라 설정 기준)
JIRA_AI_SUMMARY_FIELD = "customfield_10073" 
JIRA_ORIGINAL_LINK_FIELD = "customfield_10072" 
ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt"

# 이미지(image_10ae82.jpg) 기반 카테고리
CATEGORIES = ["방송/영화", "게임/융복합", "애니/캐릭터", "만화/웹툰", "음악", "패션", "통합"]

# 이미지 속 모든 뉴스 소스 통합 리스트
SOURCES = [
    {"name": "Mothership.SG", "query": "site:mothership.sg", "type": "search"},
    {"name": "The New Paper", "query": "site:tnp.sg", "type": "search"},
    {"name": "Straits Times", "query": "site:straitstimes.com", "type": "search"},
    {"name": "Today Online", "query": "site:todayonline.com", "type": "search"},
    {"name": "CNA", "query": "site:channelnewsasia.com", "type": "search"},
    {"name": "Marketing Interactive", "query": "site:marketing-interactive.com", "type": "search"},
    {"name": "AsiaOne", "query": "site:asiaone.com", "type": "search"},
    {"name": "Vogue Singapore", "query": "site:vogue.sg", "type": "search"},
    {"name": "Business Times SG", "query": "site:businesstimes.com.sg", "type": "search"},
    {"name": "Stomp", "query": "site:stomp.straitstimes.com", "type": "search"},
    {"name": "Animation Xpress", "query": "site:animationxpress.com", "type": "search"},
    {"name": "Cartoon Brew", "query": "site:cartoonbrew.com", "type": "search"},
    {"name": "Gamescom Asia", "query": "site:gamescom.asia", "type": "search"},
    {"name": "IMDA", "query": "site:imda.gov.sg", "type": "search"},
    {"name": "GOVInsider", "query": "site:govinsider.asia", "type": "search"},
    {"name": "ASEAN Briefing", "query": "site:aseanbriefing.com", "type": "search"},
    {"name": "The Online Citizen", "query": "site:theonlinecitizen.com", "type": "search"},
    {"name": "SBR", "query": "site:sbr.com.sg", "type": "search"}
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
            for entry in feed.entries[:2]: # 소스당 2개씩만 수집
                if entry.link not in processed:
                    all_articles.append({'title': entry.title, 'link': entry.link, 'source': source['name']})
        except: continue
    return all_articles

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"당신은 KOCCA 산업 분석가입니다. 다음 뉴스를 분석해 한국어로 요약하고 다음 카테고리 중 하나로만 분류하세요: {', '.join(CATEGORIES)}\n\n제목: {article['title']}\n링크: {article['link']}\n\n결과 형식:\nCATEGORY: 카테고리명\nSUMMARY: 한국어 요약\nSUITABLE: YES 또는 NO"
    try:
        msg = client.messages.create(model="claude-3-haiku-20240307", max_tokens=600, messages=[{"role": "user", "content": prompt}])
        res = msg.content[0].text
        data = {'cat': '통합', 'sum': '요약 실패', 'ok': False}
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
    
    # 두 번째 사진(image_10b5ad.jpg) 형식: Labels에 News와 카테고리를 넣음
    safe_cat = ai_data['cat'].replace("/", "_")
    
    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "issuetype": {"name": "Task"},
            "summary": f"[{ai_data['cat']}] {article['title']}",
            "labels": ["News", safe_cat, "KOCCA_Bot"],
            JIRA_AI_SUMMARY_FIELD: ai_data['sum'], # AI Summary 컬럼에 데이터 전송
            JIRA_ORIGINAL_LINK_FIELD: article['link'], # Original Link 컬럼에 데이터 전송
            "description": {
                "type": "doc", "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "📝 AI Summary: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": ai_data['sum']}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "🔗 URL: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": article['link'], "marks": [{"type": "link", "attrs": {"href": article['link']}}]}]}
                ]
            }
        }
    })
    try:
        response = requests.post(url, data=payload, headers=headers, auth=auth)
        if response.status_code == 201: print(f"✅ Jira 생성 성공: {article['title']}")
        else: print(f"❌ Jira 생성 실패: {response.status_code}")
    except: pass

def update_github_markdown(combined_results):
    today = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 KOCCA 글로벌 콘텐츠 산업 동향 아카이브\n\n"
    new_entry = f"## 📅 {today} 업데이트\n\n"
    for item in combined_results:
        new_entry += f"* **[{item['cat']}]** [{item['title']}]({item['link']})\n"
        new_entry += f"  * 💡 {item['sum']}\n"
    
    existing = ""
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f: existing = f.read().replace(header, "")
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f: f.write(header + new_entry + "\n---\n" + existing)

def main():
    articles = fetch_articles()
    print(f"새로운 뉴스 {len(articles)}개 분석 시작...")
    combined = []
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res.get('ok'):
            send_to_jira(art, ai_res)
            save_processed_link(art['link'])
            combined.append({**art, **ai_res})
            time.sleep(1)
    if combined: update_github_markdown(combined)

if __name__ == "__main__":
    main()