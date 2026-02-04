import requests
import re
import os
import time
from datetime import datetime

# 1. 订阅链接和节点正则
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'
NODE_PATTERN = r'(vmess|vless|ss|ssr|trojan|hysteria2|hysteria|tuic)://[^\s]+'

# 2. 精品静态源 (这些通常每天都在更新，质量极高)
BOUTIQUE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/MidScoll/free-sub/main/v2ray.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://t.me/s/v2ray_free_conf",
    "https://t.me/s/V2ray_Free_Conf",
    "https://t.me/s/SSR_V2RAY_Clash"
]

# 3. GitHub API 精准 Dorks (专搜定时更新的 README 或 txt)
GITHUB_DORKS = [
    'filename:README.md "更新时间" "订阅链接"',
    'path:/ "自动更新" "v2ray" extension:txt',
    '"机场订阅" extension:txt'
]

def fetch_content(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        return res.text if res.status_code == 200 else ""
    except:
        return ""

def main():
    all_subs = set()
    all_nodes = set()
    print(f"[{datetime.now()}] 💎 启动精品矿场收割模式...")

    # A. 抓取静态精品源
    for src in BOUTIQUE_SOURCES:
        print(f"📡 扫描精品源: {src}")
        content = fetch_content(src)
        # 提取订阅链接
        all_subs.update(re.findall(SUB_PATTERN, content))
        # 提取直接提供的节点
        all_nodes.update(re.findall(NODE_PATTERN, content))
        time.sleep(1)

    # B. 保存结果
    os.makedirs("results", exist_ok=True)
    
    # 保存订阅链接供 process_subs.py 使用
    with open("results/subscriptions.txt", "w", encoding="utf-8") as f:
        f.write(f"# 精品源采集时间: {datetime.now()}\n")
        for sub in sorted(list(all_subs)):
            f.write(sub + "\n")
            
    # 如果源里直接有节点，我们也存一份 nodes_raw.txt
    with open("results/nodes_raw.txt", "w", encoding="utf-8") as f:
        for node in sorted(list(all_nodes)):
            f.write(node + "\n")

    print(f"✅ 捕获完成！订阅: {len(all_subs)} 条, 直接节点: {len(all_nodes)} 条")

if __name__ == "__main__":
    main()
