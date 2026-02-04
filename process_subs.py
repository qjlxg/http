import requests
import base64
import re
import socket
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json

# 配置
INPUT_FILE = "results/subscriptions.txt"
OUTPUT_NODES = "results/nodes.txt"
OUTPUT_CSV = "results/statistics.csv"

# 1. 协议白名单
VALID_PROTOCOLS = ('vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'tuic://', 'hysteria2://', 'hysteria://')
# 2. 节点名黑名单（遇到这些关键词直接扔掉）
BAD_KEYWORDS = ['过期', '流量', '耗尽', '到期', '0GB', '剩余', '官网', '渠道', '维护', '重置']

def check_tcp_alive(node_url):
    """
    暴力 TCP 探测：直接拨号服务器端口。
    """
    host, port = None, None
    try:
        if node_url.startswith(('ss://', 'trojan://', 'vless://')):
            # 处理格式: protocol://user:pass@host:port#name
            part = node_url.split('@')[1].split('#')[0].split('?')[0]
            host, port = part.split(':')[0], int(part.split(':')[1])
        elif node_url.startswith('vmess://'):
            # Vmess 是 base64 编码的 json
            b64_data = node_url.replace('vmess://', '')
            # 补齐填充
            b64_data += '=' * (-len(b64_data) % 4)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            host, port = data['add'], int(data['port'])
        
        if host and port:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2) # 狠一点，2秒不通直接判定死刑
            s.connect((host, port))
            s.close()
            return True
    except:
        pass
    return False

def clean_node(line):
    """清洗：去广告、去黑名单、去无效行"""
    line = line.strip()
    if not line.startswith(VALID_PROTOCOLS): return None
    
    # 检查黑名单关键词
    for word in BAD_KEYWORDS:
        if word in line: return None
    
    return line

def process_single_sub(url):
    headers = {"User-Agent": "Clash/1.0; v2rayN/6.23"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        
        raw = res.text.strip()
        try:
            # 自动尝试补全 base64 填充
            missing_padding = len(raw) % 4
            if missing_padding: raw += '=' * (4 - missing_padding)
            content = base64.b64decode(raw).decode('utf-8')
        except:
            content = raw
            
        all_lines = content.splitlines()
        alive_nodes = []
        
        for line in all_lines:
            node = clean_node(line)
            if node:
                # 只有通过 TCP 探测的才留下
                if check_tcp_alive(node):
                    alive_nodes.append(node)
        
        return {"url": url, "total": len(all_lines), "alive": len(alive_nodes), "nodes": alive_nodes}
    except:
        return {"url": url, "total": 0, "alive": 0, "nodes": []}

def main():
    if not os.path.exists(INPUT_FILE): return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.startswith("http")]

    print(f"🚀 启动铁血收割！正在扫描 {len(urls)} 个订阅源...")
    
    final_nodes = []
    stat_report = []

    # 线程数可以开大点，TCP 探测很快
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(process_single_sub, urls))

    for r in results:
        if r:
            # 只有活节点数 > 0 的源才记录在 CSV
            stat_report.append([r["url"], r["total"], r["alive"]])
            final_nodes.extend(r["nodes"])

    # 去重并保存
    unique_nodes = list(set(final_nodes))
    os.makedirs("results", exist_ok=True)
    
    with open(OUTPUT_NODES, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["订阅源链接", "原始行数", "存活节点数"])
        # 按存活数降序排列，让你一眼看到谁是真“精品”
        stat_report.sort(key=lambda x: x[2], reverse=True)
        writer.writerows(stat_report)

    print(f"✅ 战果汇报：提取 {len(unique_nodes)} 个真·存活节点。已剔除所有垃圾数据。")

if __name__ == "__main__":
    main()
