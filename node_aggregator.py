import requests
import re
import os
import time
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"

# 排除关键词：包含这些内容的节点将被丢弃
EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com"]

# 节点匹配正则
NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[a-zA-Z0-9%@\[\]\._\-\?&=\+#/:]+'

# 精品节点池 (保持不变)
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

def extract_host_port(node_url):
    """
    核心：从节点链接中提取 (host, port) 用于精准去重
    """
    try:
        # 处理常见格式 vmess://BASE64
        if node_url.startswith("vmess://"):
            import json
            v2_raw = base64.b64decode(node_url[8:]).decode('utf-8')
            v2_json = json.loads(v2_raw)
            return str(v2_json.get('add')), str(v2_json.get('port'))
        
        # 处理标准 URI 格式 (vless, ss, trojan, etc.)
        parsed = urlparse(node_url)
        host_netloc = parsed.netloc
        
        # 处理 ss/ssr 可能存在的 userinfo@host:port
        if "@" in host_netloc:
            host_netloc = host_netloc.split("@")[-1]
            
        if ":" in host_netloc:
            parts = host_netloc.split(":")
            return parts[0], parts[1]
        
        return host_netloc, "0"
    except:
        return None, None

def is_valid_node(node_url):
    """
    过滤无效节点
    """
    # 1. 长度过滤
    if len(node_url) < 15:
        return False
    
    # 2. 关键词黑名单过滤 (127.0.0.1 等)
    for kw in EXCLUDE_KEYWORDS:
        if kw in node_url.lower():
            return False
            
    return True

def auto_decode_base64(text):
    # (保持你原来的代码不变)
    text = text.strip()
    if "://" in text and len(text) > 50:
        return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding:
            clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

# ... (fetch_from_github 和 fetch_from_sources 函数逻辑保持一致) ...

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量节点收割 (深度去重版)...")
    
    raw_nodes = set()

    # 1. 抓取
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: raw_nodes.update(nodes)

    # 2. 深度过滤与去重
    unique_pool = {} # Key: (host, port), Value: original_url
    
    for node in raw_nodes:
        if not is_valid_node(node):
            continue
            
        host, port = extract_host_port(node)
        if host and port:
            # 如果 (host, port) 已存在，则跳过，实现物理去重
            identity = f"{host}:{port}"
            if identity not in unique_pool:
                unique_pool[identity] = node

    final_list = sorted(unique_pool.values())
    
    # 3. 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, "nodes.txt")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(final_list))

    print(f"✅ 处理完成！")
    print(f"📦 原始抓取: {len(raw_nodes)} | 深度去重后: {len(final_list)}")
    if final_list:
        print(f"📝 样例: {final_list[0][:60]}...")

if __name__ == "__main__":
    main()
