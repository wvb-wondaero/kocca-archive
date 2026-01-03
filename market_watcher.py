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

JIRA_AI_SUMMARY_FIELD = "customfield_10073" 
JIRA_ORIGINAL_LINK_FIELD = "customfield_10072" 
ARCHIVE_FILE = "MARKET_ARCHIVE.md"
DB_FILE = "processed_links.txt" # 중복 방지용 파일

# --- [수집 소스 정의: 총 17개 + 알파] ---
# type 'rss'는 직접 주소, 'search'는 구글 뉴스 검색 사용
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
    # RSS가 없는 경우 구글 뉴스 검색 활용
    {"name": "Nabalune News", "query": "site:nabalunews.com", "type": "search"},
    {"name": "iNews ZoomBangla", "query": "site:inews.zoombangla.com", "type": "search"},
    {"name": "AP News", "query": "site:apnews.com", "type": "search"},
    {"name": "IMDA", "query": "site:imda.gov.sg", "type": "search"},
    # 추가 확장 검색 (AI에게 새로운 소스 발견 기회 제공)
    {"name": "Extra Content News", "query": "Singapore Malaysia Content Industry trends", "type": "search"}
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
        if source["type"] == "rss":
            feed = feedparser.parse(source["url"])
        else:
            encoded_q = urllib.parse.quote(source["query"])
            url = f"https://news.google.com/rss/search?q={encoded_q}+when:1d&hl=en-SG&gl=SG&ceid=SG:en"
            feed = feedparser.parse(url)
            
        for entry in feed.entries[:3]: # 소스당 최신 3개만
            if entry.link not in processed:
                all_articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'source_name': source['name']
                })
    return all_articles

def analyze_and_classify(article):
    """Claude AI를 통해 카테고리 분류 및 한국어 요약 생성"""
    if not ANTHROPIC_API_KEY: return None
    
    prompt = f"""
    당신은 한국콘텐츠진흥원(KOCCA)의 글로벌 산업 분석가입니다.
    다음 뉴스를 분석하여 '위클리 글로벌' 리포트에 들어갈 내용을 생성하세요.

    뉴스 제목: {article['title']}
    원본 링크: {article['link']}

    1. 카테고리 선정: 다음 중 하나만 선택하세요: [방송·영화·OTT, 게임·융복합, 애니·캐릭터, 만화·웹툰·스토리, 음악, 패션, 통합(정책 등)]
    2. 한국어 요약: 콘텐츠 산업 관점에서 2~3문장으로 핵심을 요약하세요.
    3. 적합성: 이 뉴스가 KOCCA 리포트에 적합하면 'YES', 아니면 'NO'라고 답변하세요.

    형식:
    CATEGORY: [카테고리명]
    SUMMARY: [한국어 요약]
    SUITABLE: [YES/NO]
    """
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        res = msg.content[0].text
        # 파싱 로직 (간단화)
        lines = res.split('\n')
        data = {}
        for line in lines:
            if "CATEGORY:" in line: data['cat'] = line.split(":")[1].strip()
            if "SUMMARY:" in line: data['sum'] = line.split(":")[1].strip()
            if "SUITABLE:" in line: data['ok'] = "YES" in line.upper()
        return data
    except Exception as e:
        print(f"AI 분석 오류: {e}")
        return None

def send_to_jira(article, ai_data):
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "issuetype": {"name": "Task"},
            "summary": f"[{ai_data['cat']}] {article['title']}",
            "labels": [ai_data['cat'].replace("·", "_"), "KOCCA_Global", "Wilt_Bot"],
            JIRA_AI_SUMMARY_FIELD: ai_data['sum'],
            JIRA_ORIGINAL_LINK_FIELD: article['link'],
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": ai_data['sum']}]}]
            }
        }
    })
    requests.post(url, data=payload, headers=headers, auth=auth)
    if response.status_code == 201:
        print(f"✅ 지라 생성 성공: {article['title']}")
    else:
        print(f"❌ 지라 생성 실패 ({response.status_code}): {response.text}")

def main():
    articles = fetch_articles()
    print(f"새로운 뉴스 {len(articles)}건 발견.")
    
    results_for_archive = []
    for art in articles:
        ai_result = analyze_and_classify(art)
        
        if ai_result and ai_result.get('ok'):
            send_to_jira(art, ai_result)
            save_processed_link(art['link'])
            results_for_archive.append({**art, **ai_result})
            print(f"처리 완료: {art['title']}")
            time.sleep(1) # 지라 API 과부하 방지

    if results_for_archive:
        # 여기에 기존 update_github_markdown 함수 호출 로직 추가 가능
        print(f"총 {len(results_for_archive)}건의 데이터가 지라 및 아카이브에 기록되었습니다.")

if __name__ == "__main__":
    main()