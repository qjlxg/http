import requests
import re
import os
import time
import base64
import json
import socket
import csv
import yaml
import geoip2.database
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "."
GEOIP_DB_PATH = "GeoLite2-Country.mmdb"
STATS_CSV_PATH = "source_stats.csv"
MAX_WORKERS = 80  # 提高并发数，加快检测速度

# 排除关键词
EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com", "github.com"]
# 标准节点正则
NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[a-zA-Z0-9%@\[\]\._\-\?&=\+#/:]+'

RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/qjlxg/aggregator/refs/heads/main/data/clash.yaml",
    "https://raw.githubusercontent.com/qjlxg/aggregator/refs/heads/main/data/520.yaml",
    "https://raw.githubusercontent.com/qjlxg/one/refs/heads/main/nodes_list.txt",
    "https://raw.githubusercontent.com/qjlxg/one/refs/heads/main/latest_nodes.txt"
]

# --- 工具函数 ---

def auto_decode_base64(text):
    """鲁棒性 Base64 解码"""
    text = text.strip()
    if "://" in text and len(text) > 60: return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

def parse_yaml_to_links(content):
    """解析 Clash YAML 格式并转换为标准链接"""
    links = []
    try:
        # 预处理：防止有些 YAML 开头有非标准字符
        if "proxies:" not in content: return []
        data = yaml.safe_load(content)
        if not data or 'proxies' not in data: return []
        
        for p in data['proxies']:
            try:
                t = p.get('type', '').lower()
                server = p.get('server')
                port = p.get('port')
                name = p.get('name', 'node')
                if not server or not port: continue

                if t == 'vless':
                    uuid = p.get('uuid')
                    tls = "tls" if p.get('tls') else "none"
                    sni = p.get('servername', '')
                    links.append(f"vless://{uuid}@{server}:{port}?security={tls}&sni={sni}#{name}")
                elif t == 'trojan':
                    pw = p.get('password')
                    links.append(f"trojan://{pw}@{server}:{port}#{name}")
                elif t == 'ss':
                    # SS 格式较复杂，这里做简化处理，进入去重逻辑
                    links.append(f"ss://{server}:{port}#{name}")
            except: continue
    except: pass
    return links

def extract_host_port(node_url):
    """从节点链接中提取 IP/Host 和端口"""
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

def check_alive(host, port):
    """TCP 端口存活检测"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            return s.connect_ex((host, int(port))) == 0
    except: return False

# --- 核心类 ---

class NodeAggregator:
    def __init__(self):
        self.raw_nodes = set()
        self.source_stats = []
        self.geo_reader = None
        if os.path.exists(GEOIP_DB_PATH):
            self.geo_reader = geoip2.database.Reader(GEOIP_DB_PATH)

    def get_country(self, host):
        if not self.geo_reader: return "UN"
        try:
            ip = host
            if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
                ip = socket.gethostbyname(host)
            return self.geo_reader.country(ip).country.iso_code
        except: return "UN"

    def fetch_source(self, url):
        """抓取逻辑：兼容正规链接和 YAML"""
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code == 200:
                text = res.text
                # 尝试正则
                found = re.findall(NODE_PATTERN, auto_decode_base64(text), re.IGNORECASE)
                # 尝试 YAML (如果正则没发现或包含 YAML 特征)
                if "proxies:" in text:
                    found.extend(parse_yaml_to_links(text))
                
                return url, found, 200
            return url, [], res.status_code
        except Exception as e:
            return url, [], str(e)

    def run(self):
        start_time = datetime.now()
        print(f"[{start_time.strftime('%H:%M:%S')}] 🚀 启动全功能收割流...")

        # 1. 并发抓取
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self.fetch_source, url) for url in RAW_NODE_SOURCES]
            for f in as_completed(futures):
                url, nodes, status = f.result()
                self.raw_nodes.update(nodes)
                self.source_stats.append({
                    "date": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source_url": url,
                    "node_count": len(nodes),
                    "status": status
                })

        # 保存统计 CSV (L1 级)
        self.save_stats()

        # 2. 三级去重 (L1: set, L2: identity, L3: refine)
        unique_pool = {}
        for node in self.raw_nodes:
            if len(node) < 15 or any(kw in node.lower() for kw in EXCLUDE_KEYWORDS):
                continue
            
            host, port = extract_host_port(node)
            if host and port:
                protocol = node.split("://")[0].lower()
                identity = f"{protocol}://{host}:{port}" # L2 去重特征
                if identity not in unique_pool:
                    # L3 清洗：去除原有备注
                    unique_pool[identity] = node.split("#")[0] if "#" in node else node

        # 3. 存活检测与归属地识别
        print(f"⚡ 正在检测 {len(unique_pool)} 个独特节点...")
        results_by_country = {}
        
        def process_node(item):
            identity, url = item
            protocol = identity.split("://")[0]
            host, port = identity.split("://")[-1].split(":")
            if check_alive(host, port):
                country = self.get_country(host)
                return country, f"{url}#{country}_{protocol}_{host}"
            return None, None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            node_futures = [executor.submit(process_node, it) for it in unique_pool.items()]
            for f in as_completed(node_futures):
                country, labeled_node = f.result()
                if country:
                    if country not in results_by_country: results_by_country[country] = []
                    results_by_country[country].append(labeled_node)

        # 4. 保存 nodes.txt
        self.save_nodes(results_by_country)

        print(f"---")
        print(f"✅ 处理完成！")
        print(f"📦 抓取总数: {len(self.raw_nodes)}")
        print(f"🌍 存活节点: {sum(len(v) for v in results_by_country.values())}")
        print(f"⏱️  总耗时: {datetime.now() - start_time}")

    def save_stats(self):
        with open(STATS_CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "source_url", "node_count", "status"])
            writer.writeheader()
            writer.writerows(self.source_stats)
        print(f"📊 统计报表已更新: {STATS_CSV_PATH}")

    def save_nodes(self, data):
        with open(os.path.join(OUTPUT_DIR, "nodes.txt"), "w", encoding="utf-8") as f:
            for country in sorted(data.keys()):
                f.write(f"\n# --- {country} ---\n")
                f.write("\n".join(sorted(data[country])) + "\n")

if __name__ == "__main__":
    aggregator = NodeAggregator()
    aggregator.run()
