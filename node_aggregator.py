import requests
import re
import os
import time
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"

# --- 加固 1：优化正则，确保匹配到空格或引号为止，并强制要求协议后必须有内容 ---
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

def auto_decode_base64(text):
    """加固 2：更强的 Base64 探测，处理多行编码"""
    text = text.strip()
    if "://" in text and len(text) > 50: # 如果已经是明文长列表，直接回
        return text
    try:
        # 尝试清理非 Base64 字符
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding:
            clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except:
        return text

def fetch_from_github():
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
                    # 匹配
                    matches = re.findall(NODE_PATTERN, decoded_content, re.IGNORECASE)
                    found.update(matches)
                except: continue
            time.sleep(2)
        except: pass
    return found

def fetch_from_sources(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            matches = re.findall(NODE_PATTERN, content, re.IGNORECASE)
            return matches
    except: pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量节点收割...")
    
    all_nodes = set()

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: all_nodes.update(nodes)

    all_nodes.update(fetch_from_github())

    # --- 加固 3：强制过滤掉长度小于 15 的无效字符（防止只写协议名） ---
    final_list = sorted([n for n in all_nodes if len(n) > 15])
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, "nodes.txt")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(final_list))

    print(f"✅ 处理完成！")
    print(f"📦 最终有效节点总数: {len(final_list)}")
    if final_list:
        print(f"📝 样例: {final_list[0][:60]}...")

if __name__ == "__main__":
    main()
