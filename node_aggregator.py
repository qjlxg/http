import requests
import re
import os
import time
import base64
import json
import socket
import csv
import geoip2.database
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "."
GEOIP_DB_PATH = "GeoLite2-Country.mmdb"
STATS_CSV_PATH = "source_stats.csv"  # 新增统计文件路径
MAX_WORKERS = 60

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

# --- 全局工具 ---
GEO_READER = None
if os.path.exists(GEOIP_DB_PATH):
    GEO_READER = geoip2.database.Reader(GEOIP_DB_PATH)

def extract_host_port(node_url):
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
    except: return None, None

def get_country_code(host):
    if not GEO_READER: return "UN"
    try:
        ip = host
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
            ip = socket.gethostbyname(host)
        return GEO_READER.country(ip).country.iso_code
    except: return "UN"

def check_alive(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            return s.connect_ex((host, int(port))) == 0
    except: return False

def auto_decode_base64(text):
    text = text.strip()
    if "://" in text and len(text) > 60: return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except: return text

# --- 核心逻辑 ---

def fetch_url_with_stats(url):
    """抓取并返回 (URL, 节点列表, 状态码)"""
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            nodes = re.findall(NODE_PATTERN, content, re.IGNORECASE)
            return url, nodes, 200
        return url, [], res.status_code
    except Exception as e:
        return url, [], str(e)

def main():
    start_time = datetime.now()
    print(f"[{start_time.strftime('%H:%M:%S')}] 🚀 开始全功能收割并生成统计报表...")

    raw_nodes = set()
    source_stats = [] # 用于保存 CSV 数据

    # 1. 抓取阶段并统计
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_url_with_stats, url) for url in RAW_NODE_SOURCES]
        for f in as_completed(futures):
            url, nodes, status = f.result()
            count = len(nodes)
            raw_nodes.update(nodes)
            source_stats.append({
                "date": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "source_url": url,
                "node_count": count,
                "status": status
            })

    # 保存统计 CSV
    with open(STATS_CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "source_url", "node_count", "status"])
        writer.writeheader()
        writer.writerows(source_stats)
    print(f"📊 统计报表已更新: {STATS_CSV_PATH}")

    # 2. 深度去重 (L2: 协议+Host+Port, L3: 清洗)
    unique_pool = {}
    for node in raw_nodes:
        if len(node) < 15 or any(kw in node.lower() for kw in EXCLUDE_KEYWORDS):
            continue
        host, port = extract_host_port(node)
        if host and port:
            protocol = node.split("://")[0].lower()
            identity = f"{protocol}://{host}:{port}"
            if identity not in unique_pool:
                # 清洗备注
                unique_pool[identity] = node.split("#")[0] if "#" in node else node

    # 3. 检测与分类
    print(f"⚡ 正在检测 {len(unique_pool)} 个独特节点...")
    results_by_country = {}
    
    def process_node(item):
        identity, url = item
        protocol = identity.split("://")[0]
        host, port = identity.split("://")[-1].split(":")
        if check_alive(host, port):
            country = get_country_code(host)
            return country, f"{url}#{country}_{protocol}_{host}"
        return None, None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_node = [executor.submit(process_node, it) for it in unique_pool.items()]
        for f in as_completed(future_to_node):
            country, node_str = f.result()
            if country:
                if country not in results_by_country:
                    results_by_country[country] = []
                results_by_country[country].append(node_str)

    # 4. 最终保存
    final_count = 0
    with open(os.path.join(OUTPUT_DIR, "nodes.txt"), "w", encoding="utf-8") as f:
        for country in sorted(results_by_country.keys()):
            f.write(f"\n# --- {country} ---\n")
            nodes = sorted(results_by_country[country])
            f.write("\n".join(nodes) + "\n")
            final_count += len(nodes)

    print(f"---")
    print(f"✅ 完成！有效节点: {final_count} | 原始节点: {len(raw_nodes)}")
    print(f"⏱️  总耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
