import feedparser
import datetime
import os
import time
import urllib.parse
import anthropic
import requests
from requests.auth import HTTPBasicAuth
import json
import subprocess

# --- [설정 및 비밀키] ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") 
JIRA_EMAIL = "cs@wiltvb.com"
JIRA_API_TOKEN = "ATATT3xFfGF0-C9fwMahIjdZRnR6n8KlWJSRbd3Njirhn1lJMT9J4MqJU6YiwQYdRfTeDP7M3oiiTSgoDEmAyBwwuK7FtH7rAQVCQN2mwgROkZBbJDx59BPo5L_F_tYeMXd5ANXRlsKzX_F4IlRHi59E0Q671wX5sDKIfZgHZEuOnRvRqY9nETE=321C6984"
JIRA_DOMAIN = "wiltvb.atlassian.net"

# 지라 커스텀 필드 ID (사용자 화면 기준)
JIRA_AI_SUMMARY_FIELD = "customfield_10073" 
JIRA_ORIGINAL_LINK_FIELD = "customfield_10072" 
ARCHIVE_FILE = "MARKET_ARCHIVE.md"

KEYWORDS = ["성수동 팝업스토어", "푸드테크 투자", "국내 유니콘 스타트업"]

def send_to_jira(article, ai_text):
    """지라 리스트 뷰 컬럼에 맞춰 데이터 전송"""
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "issuetype": {"name": "Task"},
            "summary": article['title'],               # Summary
            "labels": [article['keyword'].replace(" ", "_"), "Wilt_Bot"], # Labels
            JIRA_AI_SUMMARY_FIELD: ai_text,            # AI Summary
            JIRA_ORIGINAL_LINK_FIELD: article['link'], # Original Link
            "description": {                           # 본문 상세
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": ai_text}]}]
            }
        }
    })
    requests.post(url, data=payload, headers=headers, auth=auth)

def generate_ai_content(article):
    """Claude AI를 통한 요약 생성"""
    if not ANTHROPIC_API_KEY: return "AI Key missing"
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=500,
            messages=[{"role": "user", "content": f"Summarize this news for a VC in 2 sentences: {article['title']}"}]
        )
        return msg.content[0].text
    except:
        return "AI 요약 생성에 실패했습니다."

def update_github_markdown(all_results):
    """GitHub 마크다운 아카이브 업데이트"""
    today_str = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 Market Watcher 아카이브\n\n"
    new_entry = f"## 📅 {today_str}\n\n"
    for item in all_results:
        new_entry += f"* [{item['title']}]({item['link']}) ({item['keyword']})\n"
    new_entry += "\n---\n"
    
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + new_entry)

def main():
    results = []
    for kw in KEYWORDS:
        encoded = urllib.parse.quote(kw)
        url = f"https://news.google.com/rss/search?q={encoded}+when:1d&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(url)
        if feed.entries:
            article = {'title': feed.entries[0].title, 'link': feed.entries[0].link, 'keyword': kw}
            ai_text = generate_ai_content(article)
            # [수정 포인트] ai_text 인자를 반드시 전달해야 에러가 나지 않습니다.
            send_to_jira(article, ai_text) 
            results.append(article)
            time.sleep(1)

    if results:
        update_github_markdown(results)

if __name__ == "__main__":
    main()