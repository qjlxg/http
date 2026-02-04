import requests
import re
import os
import time
import base64
import socket
import json
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'
NODE_PATTERN = r'(vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[^\s]+'
BAD_KEYWORDS = ['过期', '流量', '耗尽', '到期', '0GB', '剩余', '官网', '维护', '重置']

# 精品静态源
BOUTIQUE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://t.me/s/v2ray_free_conf",
    "https://t.me/s/V2ray_Free_Conf"
]

# GitHub 搜索 Dorks
GITHUB_DORKS = [
    'extension:txt "api/v1/client/subscribe?token="',
    'filename:README.md "更新时间" "订阅链接"'
]

# --- 核心功能区 ---

def check_tcp_alive(node_url):
    """TCP 端口探测"""
    try:
        host, port = None, None
        if node_url.startswith(('ss://', 'trojan://', 'vless://')):
            part = node_url.split('@')[1].split('#')[0].split('?')[0]
            host, port = part.split(':')[0], int(part.split(':')[1])
        elif node_url.startswith('vmess://'):
            b64_data = node_url.replace('vmess://', '')
            b64_data += '=' * (-len(b64_data) % 4)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            host, port = data['add'], int(data['port'])
        
        if host and port:
            with socket.create_connection((host, port), timeout=2):
                return True
    except:
        pass
    return False

def fetch_sub_and_nodes(url):
    """请求订阅链接并提取存活节点"""
    headers = {"User-Agent": "Clash/1.0; v2rayN/6.23"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        
        raw = res.text.strip()
        try:
            missing_padding = len(raw) % 4
            if missing_padding: raw += '=' * (4 - missing_padding)
            content = base64.b64decode(raw).decode('utf-8')
        except:
            content = raw
            
        alive_nodes = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(tuple(NODE_PATTERN.split('|'))) and not any(w in line for w in BAD_KEYWORDS):
                if check_tcp_alive(line):
                    alive_nodes.append(line)
        return {"url": url, "count": len(alive_nodes), "nodes": alive_nodes}
    except:
        return None

def get_github_subs():
    """通过 API 搜索订阅链接"""
    if not GITHUB_TOKEN: return set()
    subs = set()
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3.text-match+json"}
    for dork in GITHUB_DORKS:
        try:
            url = f"https://api.github.com/search/code?q={dork}&sort=indexed"
            res = requests.get(url, headers=headers, timeout=20).json()
            for item in res.get('items', []):
                raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                content = requests.get(raw_url, timeout=10).text
                subs.update(re.findall(SUB_PATTERN, content))
        except: pass
    return subs

# --- 主逻辑 ---

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 全自动合并收割开始...")
    
    # 1. 汇总所有订阅源
    target_subs = set()
    # 加入静态源
    for src in BOUTIQUE_SOURCES:
        content = requests.get(src, timeout=10).text
        target_subs.update(re.findall(SUB_PATTERN, content))
    # 加入 GitHub API 搜索结果
    target_subs.update(get_github_subs())
    
    print(f"📡 共锁定 {len(target_subs)} 个订阅源，准备深度探测...")

    # 2. 并发处理所有源
    all_final_nodes = []
    stats = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(fetch_sub_and_nodes, target_subs))

    for r in results:
        if r and r["count"] > 0:
            stats.append([r["url"], r["count"]])
            all_final_nodes.extend(r["nodes"])

    # 3. 结果去重与保存
    unique_nodes = list(set(all_final_nodes))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))
        
    with open(f"{OUTPUT_DIR}/statistics.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["订阅链接", "存活节点数"])
        stats.sort(key=lambda x: x[1], reverse=True)
        writer.writerows(stats)

    print(f"✅ 完成！共耗时: {datetime.now() - start_time}")
    print(f"💎 捕获真存活节点: {len(unique_nodes)} 个")

if __name__ == "__main__":
    main()
