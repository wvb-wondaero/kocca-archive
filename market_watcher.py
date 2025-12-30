import feedparser
import datetime
import os
import time
import urllib.parse
import re
import anthropic
import requests
from requests.auth import HTTPBasicAuth
import json
import subprocess

# --- [비밀키 및 설정] ---
JIRA_EMAIL = "cs@wiltvb.com"
JIRA_API_TOKEN = "ATATT3xFfGF0-C9fwMahIjdZRnR6n8KlWJSRbd3Njirhn1lJMT9J4MqJU6YiwQYdRfTeDP7M3oiiTSgoDEmAyBwwuK7FtH7rAQVCQN2mwgROkZBbJDx59BPo5L_F_tYeMXd5ANXRlsKzX_F4IlRHi59E0Q671wX5sDKIfZgHZEuOnRvRqY9nETE=321C6984"
JIRA_DOMAIN = "wiltvb.atlassian.net"
JIRA_URL_FIELD_ID = "customfield_10072" 
ARCHIVE_FILE = "MARKET_ARCHIVE.md"

KEYWORDS = ["성수동 팝업스토어", "푸드테크 투자", "국내 유니콘 스타트업"]

# --- [함수 로직들] ---
def update_github_markdown(all_results):
    today_str = datetime.datetime.now().strftime('%Y년 %m월 %d일')
    header = "# 📰 Market Watcher 아카이브\n\n"
    new_entry = f"## 📅 {today_str}\n\n"
    for item in all_results:
        new_entry += f"* [{item['title']}]({item['link']}) ({item['keyword']})\n"
    new_entry += "\n---\n"
    
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.write(header + new_entry)
    
    try:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Archive: {today_str}"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("🚀 GitHub Push 성공!")
    except: pass

def send_to_jira(article):
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = json.dumps({
        "fields": {
            "project": {"key": "PJM"},
            "summary": article['title'],
            "issuetype": {"name": "Task"},
            "labels": ["Wilt_Bot"],
            JIRA_URL_FIELD_ID: article['link']
        }
    })
    requests.post(url, data=payload, headers=headers, auth=auth)

def main():
    results = []
    for kw in KEYWORDS:
        encoded = urllib.parse.quote(kw)
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={encoded}+when:1d&hl=ko&gl=KR&ceid=KR:ko")
        if feed.entries:
            article = {'title': feed.entries[0].title, 'link': feed.entries[0].link, 'keyword': kw}
            send_to_jira(article)
            results.append(article)
    if results:
        update_github_markdown(results)

if __name__ == "__main__":
    main()