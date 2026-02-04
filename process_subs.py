import requests
import base64
import re
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 输入输出配置
INPUT_FILE = "results/subscriptions.txt"
OUTPUT_NODES = "results/nodes.txt"
OUTPUT_CSV = "results/statistics.csv"

def fetch_and_count(url):
    url = url.strip()
    if not url or url.startswith("#"):
        return None
    
    headers = {
        "User-Agent": "Clash/1.0" # 模拟 Clash 客户端，有些机场屏蔽普通爬虫
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            content = response.text.strip()
            # 机场返回通常是 Base64
            try:
                decoded = base64.b64decode(content + '=' * (-len(content) % 4)).decode('utf-8')
                # 统计节点数量（通常一行一个节点，以 vmess://, ss://, trojan:// 开头）
                nodes = [n for n in decoded.splitlines() if "://" in n]
                return {
                    "url": url,
                    "count": len(nodes),
                    "status": "Success",
                    "data": nodes
                }
            except:
                # 有些返回的是明文 yaml/conf，直接统计包含节点的行
                nodes = [n for n in content.splitlines() if "://" in n]
                return {
                    "url": url,
                    "count": len(nodes),
                    "status": "Partial/Plain",
                    "data": nodes
                }
    except Exception as e:
        return {"url": url, "count": 0, "status": f"Error: {str(e)[:20]}", "data": []}
    return {"url": url, "count": 0, "status": "Failed", "data": []}

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"File {INPUT_FILE} not found!")
        return

    with open(INPUT_FILE, "r") as f:
        urls = [line for line in f if line.startswith("http")]

    print(f"🚀 开始处理 {len(urls)} 条链接...")
    
    all_nodes = []
    stats = []

    # 使用 20 个线程并发处理
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(fetch_and_count, urls))

    for res in results:
        if res:
            stats.append([res["url"], res["count"], res["status"]])
            all_nodes.extend(res["data"])

    # 1. 保存所有节点（去重）
    unique_nodes = list(set(all_nodes))
    os.makedirs("results", exist_ok=True)
    with open(OUTPUT_NODES, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))

    # 2. 生成统计 CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["订阅链接", "获取节点数", "状态"])
        writer.writerows(stats)

    print(f"✅ 处理完成！")
    print(f"📊 总计获取独立节点: {len(unique_nodes)} 个")
    print(f"📝 统计报表已保存至: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
