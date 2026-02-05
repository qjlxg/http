import requests
import re
import os
import time
import base64
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "."
MAX_WORKERS = 50  # 增加并发数，提升检测速度

EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com", "github.com"]
NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[a-zA-Z0-9%@\[\]\._\-\?&=\+#/:]+'

RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/mueiba/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/StaySleepless/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/v2ray.txt",
    "https://raw.githubusercontent.com/v2ray-free/free/main/v2ray",
    "https://raw.githubusercontent.com/qjlxg/aggregator/refs/heads/main/data/clash.yaml",
    "https://raw.githubusercontent.com/qjlxg/aggregator/refs/heads/main/data/520.yaml",
    "https://raw.githubusercontent.com/qjlxg/one/refs/heads/main/nodes_list.txt",
    "https://raw.githubusercontent.com/qjlxg/one/refs/heads/main/latest_nodes.txt"
]

def check_node_alive(host, port):
    """通过 TCP 握手判断节点端口是否开放"""
    if not host or not port: return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0) # 2秒超时
            return s.connect_ex((host, int(port))) == 0
    except:
        return False

def extract_host_port(node_url):
    """提取 Host 和 Port"""
    try:
        if node_url.startswith("vmess://"):
            v2_raw = base64.b64decode(node_url[8:]).decode('utf-8')
            v2_json = json.loads(v2_raw)
            return str(v2_json.get('add')).strip(), str(v2_json.get('port')).strip()
        
        parsed = urlparse(node_url)
        netloc = parsed.netloc
        if "@" in netloc: netloc = netloc.split("@")[-1]
        
        if ":" in netloc:
            host, port = netloc.split(":")
            return host.strip(), port.strip()
        return netloc.strip(), "0"
    except:
        return None, None

def auto_decode_base64(text):
    """增强版 Base64 解码"""
    text = text.strip()
    if "://" in text and len(text) > 60: return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

def fetch_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            return re.findall(NODE_PATTERN, content, re.IGNORECASE)
    except: pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time.strftime('%H:%M:%S')}] 🚀 开始收割节点...")

    # 1. 抓取阶段
    raw_nodes = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_url, url) for url in RAW_NODE_SOURCES]
        for f in as_completed(futures):
            raw_nodes.update(f.result())
    
    print(f"📥 初始抓取数量: {len(raw_nodes)}")

    # 2. 预处理与去重
    temp_pool = {} # identity -> node_url
    for node in raw_nodes:
        if len(node) < 15 or any(kw in node.lower() for kw in EXCLUDE_KEYWORDS):
            continue
        host, port = extract_host_port(node)
        if host and port:
            temp_pool[f"{host}:{port}"] = node

    # 3. 并发存活检测
    print(f"⚡ 正在检测节点可用性 (线程数: {MAX_WORKERS})...")
    final_nodes = []
    
    def worker(item):
        identity, url = item
        host, port = identity.split(":")
        if check_node_alive(host, port):
            return url
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(worker, temp_pool.items()))
        final_nodes = [r for r in results if r]

    # 4. 写入文件
    final_nodes.sort()
    with open(os.path.join(OUTPUT_DIR, "nodes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(final_nodes))

    print(f"---")
    print(f"✅ 完成！有效节点: {len(final_nodes)} / 独特地址: {len(temp_pool)}")
    print(f"⏱️  总耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
