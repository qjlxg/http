import requests
import re
import os
import time
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "."

# 排除关键词：包含这些内容的节点将被丢弃（如官网地址、本地回环地址）
EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com", "github.com"]

# 节点匹配正则
NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[a-zA-Z0-9%@\[\]\._\-\?&=\+#/:]+'

# 精品节点池
RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/mueiba/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/StaySleepless/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/v2ray.txt",
    "https://raw.githubusercontent.com/v2ray-free/free/main/v2ray"
]

GITHUB_DORKS = [
    'extension:txt "vmess://"',
    'extension:txt "vless://"',
    'extension:txt "ssr://"',
    'extension:txt "hysteria2://"',
    'filename:nodes.txt "ss://"',
    'filename:README.md "更新时间" "vmess://"'
]

def extract_host_port(node_url):
    """提取节点中的 (host, port) 用于去重"""
    try:
        # 处理 vmess (通常是 Base64 后的 JSON)
        if node_url.startswith("vmess://"):
            v2_raw = base64.b64decode(node_url[8:]).decode('utf-8')
            v2_json = json.loads(v2_raw)
            return str(v2_json.get('add')).strip(), str(v2_json.get('port')).strip()
        
        # 处理其他协议 (vless, ss, trojan, etc.)
        parsed = urlparse(node_url)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        
        if ":" in netloc:
            host, port = netloc.split(":")
            return host.strip(), port.strip()
        return netloc.strip(), "0"
    except:
        return None, None

def auto_decode_base64(text):
    """鲁棒性强的 Base64 解码"""
    text = text.strip()
    if "://" in text and len(text) > 60:
        return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding:
            clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

def fetch_from_sources(url):
    """从单一 URL 抓取并解析节点"""
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            return re.findall(NODE_PATTERN, content, re.IGNORECASE)
    except:
        pass
    return []

def fetch_from_github():
    """通过 GitHub API 搜索最新节点"""
    if not GITHUB_TOKEN: return set()
    found = set()
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    for dork in GITHUB_DORKS:
        try:
            url = f"https://api.github.com/search/code?q={dork}&sort=indexed"
            res = requests.get(url, headers=headers, timeout=15).json()
            for item in res.get('items', []):
                raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                try:
                    content = requests.get(raw_url, timeout=5).text
                    decoded_content = auto_decode_base64(content)
                    matches = re.findall(NODE_PATTERN, decoded_content, re.IGNORECASE)
                    found.update(matches)
                except: continue
            time.sleep(1) # 避免触发 Rate Limit
        except: pass
    return found

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量节点收割 (深度去重版)...")
    
    raw_nodes = set()

    # 1. 并发抓取订阅源
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: raw_nodes.update(nodes)

    # 2. 抓取 GitHub 发现源
    raw_nodes.update(fetch_from_github())

    # 3. 深度过滤与基于 (IP, Port) 的去重
    unique_pool = {} # Key: "host:port", Value: node_url
    
    for node in raw_nodes:
        # 基本长度过滤
        if len(node) < 15:
            continue
            
        # 关键词黑名单过滤 (127.0.0.1 等)
        if any(kw in node.lower() for kw in EXCLUDE_KEYWORDS):
            continue
            
        host, port = extract_host_port(node)
        if host and port:
            # 只有当该 IP:Port 组合第一次出现时才加入
            identity = f"{host}:{port}"
            if identity not in unique_pool:
                unique_pool[identity] = node

    final_list = sorted(unique_pool.values())
    
    # 4. 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, "nodes.txt")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(final_list))

    print(f"---")
    print(f"✅ 处理完成！")
    print(f"📦 原始抓取总数: {len(raw_nodes)}")
    print(f"🛡️  (IP:Port) 去重后有效总数: {len(final_list)}")
    print(f"⏱️  总耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
