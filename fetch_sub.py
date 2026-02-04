import requests
import re
import os
import urllib.parse
from datetime import datetime

# 搜索关键词列表 (Dorks)
DORKS = [
    'inurl:"/api/v1/client/subscribe?token="',
    '"/api/v1/client/subscribe?token=" site:pastebin.com',
    '"/api/v1/client/subscribe?token=" site:github.com',
    '"/api/v1/client/subscribe?token=" site:t.me'
]

# 精准匹配 token 的正则
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'

def fetch_from_searxng(query):
    """从 SearXNG 实例抓取内容"""
    found = set()
    encoded_query = urllib.parse.quote(query)
    # 使用你提供的 SearXNG 实例地址
    url = f"https://search.mdel.net/search?q={encoded_query}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print(f"正在搜索: {query}")
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            # 直接扫描页面中的所有匹配链接
            links = re.findall(SUB_PATTERN, response.text)
            for link in links:
                # 简单清洗：去掉末尾可能的干扰字符
                clean_link = link.split("'")[0].split('"')[0]
                found.add(clean_link)
            print(f"  └─ 本次发现 {len(links)} 条潜在链接")
    except Exception as e:
        print(f"  └─ 搜索出错: {e}")
    
    return found

def main():
    all_links = set()
    
    # 执行 Dorks 搜索
    for dork in DORKS:
        links = fetch_from_searxng(dork)
        all_links.update(links)
    
    # 结果保存
    os.makedirs("results", exist_ok=True)
    file_path = "results/subscriptions.txt"
    
    # 过滤掉一些明显的无效链接（如 example.com）
    final_links = [l for l in all_links if "example.com" not in l]
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"# 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Shanghai)\n")
        f.write(f"# 总计有效链接: {len(final_links)}\n\n")
        for l in sorted(final_links):
            f.write(l + "\n")
    
    print(f"\n✅ 任务完成！共捕获 {len(final_links)} 条订阅链接。")

if __name__ == "__main__":
    main()
