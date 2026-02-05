import requests
import re
import os
import time
import base64
import json
import socket
import geoip2.database
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "."
GEOIP_DB_PATH = "GeoLite2-Country.mmdb"
MAX_WORKERS = 60  # 提高并发，加速检测和DNS解析

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

# --- 全局 GeoIP Reader ---
GEO_READER = None
if os.path.exists(GEOIP_DB_PATH):
    GEO_READER = geoip2.database.Reader(GEOIP_DB_PATH)
else:
    print(f"⚠️ 警告: 未在根目录找到 {GEOIP_DB_PATH}，将跳过归属地识别。")

# --- 核心工具函数 ---

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

def get_country_code(host):
    """识别国家代码 (L4 逻辑: 域名转IP后查询)"""
    if not GEO_READER: return "UN"
    try:
        ip = host
        # 如果是域名则尝试解析
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
            ip = socket.gethostbyname(host)
        return GEO_READER.country(ip).country.iso_code
    except:
        return "UN"

def refine_node_url(node_url):
    """L3 智能清洗：去除备注和干扰项"""
    if "#" in node_url:
        node_url = node_url.split("#")[0]
    return node_url

def check_alive(host, port):
    """TCP 端口检测"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            return s.connect_ex((host, int(port))) == 0
    except:
        return False

def auto_decode_base64(text):
    text = text.strip()
    if "://" in text and len(text) > 60: return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

# --- 抓取与处理 ---

def fetch_url(url):
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            return re.findall(NODE_PATTERN, content, re.IGNORECASE)
    except: pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time.strftime('%H:%M:%S')}] 🚀 开始执行全功能节点收割...")

    # 1. 全量抓取 (L1: 初始 set 自动去重字符串)
    raw_nodes = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        sources = RAW_NODE_SOURCES
        futures = [executor.submit(fetch_url, url) for url in sources]
        for f in as_completed(futures):
            raw_nodes.update(f.result())
    
    print(f"📥 抓取完成，原始节点数: {len(raw_nodes)}")

    # 2. L2/L3 深度去重
    unique_pool = {} # identity -> cleaned_url
    for node in raw_nodes:
        if len(node) < 15 or any(kw in node.lower() for kw in EXCLUDE_KEYWORDS):
            continue
        
        host, port = extract_host_port(node)
        if host and port:
            protocol = node.split("://")[0].lower()
            # L2 特征: 协议+Host+Port
            identity = f"{protocol}://{host}:{port}"
            if identity not in unique_pool:
                # L3 清洗: 移除原有备注
                unique_pool[identity] = refine_node_url(node)

    # 3. 多线程检测与 GeoIP 分类
    print(f"⚡ 正在检测 {len(unique_pool)} 个独特节点的可用性并识别归属地...")
    results_by_country = {} # {"HK": [url1, url2], "US": [...]}
    
    def process_node(item):
        identity, url = item
        protocol = identity.split("://")[0]
        host, port = identity.split("://")[-1].split(":")
        
        if check_alive(host, port):
            country = get_country_code(host)
            # 格式化输出：给节点带上国家后缀
            labeled_node = f"{url}#{country}_{protocol}_{host}"
            return country, labeled_node
        return None, None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_node = [executor.submit(process_node, it) for it in unique_pool.items()]
        for f in as_completed(future_to_node):
            country, node_str = f.result()
            if country:
                if country not in results_by_country:
                    results_by_country[country] = []
                results_by_country[country].append(node_str)

    # 4. 保存结果 (按国家分组排序)
    final_count = 0
    with open(os.path.join(OUTPUT_DIR, "nodes.txt"), "w", encoding="utf-8") as f:
        for country in sorted(results_by_country.keys()):
            f.write(f"\n# --- {country} ---\n")
            nodes = sorted(results_by_country[country])
            f.write("\n".join(nodes) + "\n")
            final_count += len(nodes)

    print(f"---")
    print(f"✅ 处理完成！")
    print(f"📦 独特节点 (L2): {len(unique_pool)}")
    print(f"🌍 存活节点 (GeoIP 分类): {final_count}")
    print(f"⏱️  总耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
