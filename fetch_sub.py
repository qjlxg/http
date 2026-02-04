import requests
import re
import os
import random
import time
from datetime import datetime

# 1. 订阅链接正则（保持精准）
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'

# 2. 静态源：这些是专门泄露或分享订阅链接的“矿场”
# 我们直接请求这些 URL 的内容，比搜索更可靠
STATIC_SOURCES = [
    "https://t.me/s/V2ray_Free_Conf",
    "https://t.me/s/SSRSUB",
    "https://t.me/s/v2rayfree666",
    "https://t.me/s/v2ray_free_conf",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt"
]

def fetch_content(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"   ❌ 请求失败: {url} -> {e}")
    return ""

def main():
    all_found = set()
    print(f"[{datetime.now()}] 🚀 开始收割模式...")

    # 第一步：收割 Telegram 频道和 GitHub 静态源
    print("--- 正在收割静态矿场 ---")
    for source in STATIC_SOURCES:
        print(f"📡 扫描: {source}")
        content = fetch_content(source)
        links = re.findall(SUB_PATTERN, content)
        if links:
            print(f"   ✨ 发现 {len(links)} 条潜在链接")
            all_found.update(links)
        time.sleep(1)

    # 第二步：结果去重、清洗与保存
    os.makedirs("results", exist_ok=True)
    file_path = "results/subscriptions.txt"
    
    # 简单的格式二次校验
    final_list = sorted([l for l in all_found if "token=" in l and len(l) > 30])

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"# 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Shanghai)\n")
        f.write(f"# 有效链接总数: {len(final_list)}\n\n")
        for link in final_list:
            f.write(link + "\n")

    print(f"\n✅ 任务完成！共捕获 {len(final_list)} 条有效订阅。")

if __name__ == "__main__":
    main()
