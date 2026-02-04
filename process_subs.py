import requests
import base64
import re
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 文件路径配置
INPUT_FILE = "results/subscriptions.txt"
OUTPUT_NODES = "results/nodes.txt"
OUTPUT_CSV = "results/statistics.csv"

def fetch_content(url):
    url = url.strip()
    if not url or url.startswith("#"):
        return None
    
    headers = {
        "User-Agent": "Clash/1.0; v2rayN/6.23" # 模拟客户端
    }
    
    try:
        # 增加超时控制，防止某个死链接卡住脚本
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            raw_data = response.text.strip()
            
            # 1. 尝试 Base64 解码 (大多数机场的格式)
            try:
                # 补齐 Base64 填充符
                missing_padding = len(raw_data) % 4
                if missing_padding:
                    raw_data += '=' * (4 - missing_padding)
                decoded_data = base64.b64decode(raw_data).decode('utf-8')
                nodes = [n for n in decoded_data.splitlines() if "://" in n]
                return {"url": url, "count": len(nodes), "status": "Success", "nodes": nodes}
            except:
                # 2. 如果解码失败，尝试直接作为明文处理 (部分 YAML 或单行链接)
                nodes = [n for n in raw_data.splitlines() if "://" in n]
                return {"url": url, "count": len(nodes), "status": "Plaintext", "nodes": nodes}
    except Exception as e:
        return {"url": url, "count": 0, "status": "Connect Error", "nodes": []}
    return {"url": url, "count": 0, "status": f"HTTP {response.status_code}", "nodes": []}

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 错误: 找不到 {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.startswith("http")]

    print(f"🚀 正在处理 {len(urls)} 个订阅链接...")
    
    all_extracted_nodes = []
    stats_data = []

    # 使用并发加速处理
    with ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(fetch_content, urls))

    for res in results:
        if res:
            stats_data.append([res["url"], res["count"], res["status"]])
            all_extracted_nodes.extend(res["nodes"])

    # 结果保存
    os.makedirs("results", exist_ok=True)

    # 1. 保存 nodes.txt (去重处理)
    unique_nodes = list(set(all_extracted_nodes))
    with open(OUTPUT_NODES, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))

    # 2. 保存统计报告 CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["订阅链接", "获取节点数", "状态"])
        writer.writerows(stats_data)

    print(f"✅ 处理完成!")
    print(f"📁 节点文件: {OUTPUT_NODES} (总计 {len(unique_nodes)} 个唯一节点)")
    print(f"📊 统计报表: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
