import requests
import base64
import re
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 文件路径
INPUT_FILE = "results/subscriptions.txt"
OUTPUT_NODES = "results/nodes.txt"
OUTPUT_CSV = "results/statistics.csv"

# 定义合法的协议头
VALID_PROTOCOLS = ('vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'tuic://', 'hysteria2://', 'hysteria://')

def clean_and_validate_node(line):
    """清洗单行数据，只保留合法的节点字符串"""
    line = line.strip()
    # 必须以合法协议开头，且不能包含 HTML 标签
    if line.startswith(VALID_PROTOCOLS) and '<' not in line and '{' not in line:
        return line
    return None

def fetch_content(url):
    url = url.strip()
    if not url or url.startswith("#"):
        return None
    
    headers = {"User-Agent": "Clash/1.0; v2rayN/6.23"}
    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            raw_data = response.text.strip()
            
            # 尝试 Base64 解码
            content = ""
            try:
                # 自动补全并尝试解码
                missing_padding = len(raw_data) % 4
                if missing_padding: raw_data += '=' * (4 - missing_padding)
                content = base64.b64decode(raw_data).decode('utf-8')
            except:
                # 解码失败则视为明文
                content = raw_data
            
            # 提取并清洗节点
            extracted_nodes = []
            for line in content.splitlines():
                node = clean_and_validate_node(line)
                if node:
                    extracted_nodes.append(node)
            
            return {"url": url, "count": len(extracted_nodes), "nodes": extracted_nodes}
    except:
        pass
    return {"url": url, "count": 0, "nodes": []}

def main():
    if not os.path.exists(INPUT_FILE):
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.startswith("http")]

    print(f"🚀 正在清洗并提取 {len(urls)} 个源...")
    
    all_nodes = []
    stats = []

    with ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(fetch_content, urls))

    for res in results:
        if res:
            stats.append([res["url"], res["count"]])
            all_nodes.extend(res["nodes"])

    # 去重并保存
    unique_nodes = sorted(list(set(all_nodes)))
    
    os.makedirs("results", exist_ok=True)
    with open(OUTPUT_NODES, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["订阅链接", "有效节点数"])
        writer.writerows(stats)

    print(f"✅ 清洗完成！剩余纯净节点: {len(unique_nodes)} 个")

if __name__ == "__main__":
    main()
