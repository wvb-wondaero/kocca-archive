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

# 지라 고유 필드 ID (이미지 112a67.png 기준)
JIRA_AI_SUMMARY_FIELD = "customfield_10073"  # 'AI Summary' 컬럼
JIRA_ORIGINAL_LINK_FIELD = "customfield_10072" # 'Original Link' 컬럼
JIRA_IMAGE_FIELD = "customfield_10101"        # 'Images' 컬럼 (ID 확인 필요)

DB_FILE = "processed_links.txt"
CATEGORIES = ["방송/영화", "게임/융복합", "애니/캐릭터", "만화/웹툰", "음악", "패션", "통합"]

# 이미지(10ae82.jpg) 기반 최신 소스 리스트
SOURCES = [
    {"name": "Mothership.SG", "query": "site:mothership.sg", "type": "search"},
    {"name": "CNA", "query": "site:channelnewsasia.com", "type": "search"},
    {"name": "Straits Times", "query": "site:straitstimes.com", "type": "search"},
    {"name": "Today Online", "query": "site:todayonline.com", "type": "search"},
    {"name": "The New Paper", "query": "site:tnp.sg", "type": "search"},
    {"name": "Marketing Interactive", "query": "site:marketing-interactive.com", "type": "search"},
    {"name": "AsiaOne", "query": "site:asiaone.com", "type": "search"},
    {"name": "Vogue Singapore", "query": "site:vogue.sg", "type": "search"},
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
            for entry in feed.entries[:2]:
                if entry.link not in processed:
                    img = entry.media_thumbnail[0]['url'] if hasattr(entry, 'media_thumbnail') else ""
                    all_articles.append({'title': entry.title, 'link': entry.link, 'image': img})
        except: continue
    return all_articles

def analyze_and_classify(article):
    if not ANTHROPIC_API_KEY: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"당신은 KOCCA 분석가입니다. 결과를 반드시 CATEGORY, AI_SUMMARY(1문장), DETAILED_SUMMARY(3문장), SUITABLE(YES/NO) 형식으로 응답하세요.\n\n제목: {article['title']}\n카테고리 후보: {', '.join(CATEGORIES)}"
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

def send_to_jira(article, ai_data):
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    # 카테고리 태그 정리
    safe_cat = ai_data['cat'].replace("/", "_")
    
    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "issuetype": {"name": "Task"},
            "summary": article['title'], # 'Summary' 컬럼에 제목 입력
            "labels": ["News", safe_cat, "KOCCA_Bot"], # 'Labels' 컬럼에 태그 입력
            JIRA_AI_SUMMARY_FIELD: ai_data['ai'], # 'AI Summary' 컬럼에 입력
            JIRA_ORIGINAL_LINK_FIELD: article['link'], # 'Original Link' 컬럼에 입력
            JIRA_IMAGE_FIELD: article['image'], # 'Images' 컬럼에 이미지 주소 입력
            "description": { # 상세 내용은 본문에 추가
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": ai_data['det']}]}]
            }
        }
    })
    try:
        response = requests.post(url, data=payload, headers=headers, auth=auth)
        if response.status_code == 201: print(f"✅ 성공: {article['title']}")
    except: pass

def main():
    articles = fetch_articles()
    print(f"{len(articles)}개 기사 분석 시작")
    for art in articles:
        ai_res = analyze_and_classify(art)
        if ai_res and ai_res['ok']:
            send_to_jira(art, ai_res)
            save_processed_link(art['link'])
            time.sleep(1)

if __name__ == "__main__":
    main()