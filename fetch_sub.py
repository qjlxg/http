import requests
import re
import os
import base64
import time
from datetime import datetime

# 获取仓库 Secret 中的 Token
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")

# 搜索关键词：精准锁定机场订阅链接特征
SEARCH_QUERIES = [
    'extension:txt "api/v1/client/subscribe?token="',
    'extension:yaml "api/v1/client/subscribe?token="',
    'extension:conf "api/v1/client/subscribe?token="'
]

SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'

def search_github(query):
    if not GITHUB_TOKEN:
        print("⚠️ 未发现 MY_GITHUB_TOKEN，跳过 GitHub API 搜索。")
        return set()

    found = set()
    url = f"https://api.github.com/search/code?q={query}&sort=indexed&order=desc"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.text-match+json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            items = response.json().get('items', [])
            for item in items:
                # 获取文件的 raw 内容
                raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                print(f"   📄 发现潜在泄露源: {raw_url}")
                res = requests.get(raw_url, timeout=10)
                links = re.findall(SUB_PATTERN, res.text)
                found.update(links)
        elif response.status_code == 403:
            print("   🚫 API 速率限制，请稍后再试。")
    except Exception as e:
        print(f"   ❌ 搜索出错: {e}")
    
    return found

def main():
    all_links = set()
    print(f"[{datetime.now()}] 🛰️ 启动 GitHub 全站 API 深度探测...")

    for q in SEARCH_QUERIES:
        print(f"🔍 搜索关键词: {q}")
        links = search_github(q)
        all_links.update(links)
        time.sleep(5) # 遵守 API 速率限制

    # 保存
    os.makedirs("results", exist_ok=True)
    final_list = sorted(list(all_links))
    
    with open("results/subscriptions.txt", "w", encoding="utf-8") as f:
        f.write(f"# GitHub API 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Shanghai)\n")
        f.write(f"# 本次共捕获有效泄露链接: {len(final_list)}\n\n")
        for l in final_list:
            f.write(l + "\n")

    print(f"✅ 完成！捕获到 {len(final_list)} 条。")

if __name__ == "__main__":
    main()
