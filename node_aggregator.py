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

# --- 核心修复：使用 (?:...) 非捕获分组，确保匹配完整链接而非仅协议名 ---
NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[^\s^"\'\(\)]+'

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
    """自动探测并解码内容"""
    text = text.strip()
    if "://" in text:
        return text
    try:
        missing_padding = len(text) % 4
        if missing_padding:
            text += '=' * (4 - missing_padding)
        # 解码并忽略无法识别的字符
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except:
        return text

def fetch_from_github():
    if not GITHUB_TOKEN:
        return set()
    
    found = set()
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    for dork in GITHUB_DORKS:
        try:
            print(f"🔍 正在检索 GitHub: {dork}")
            url = f"https://api.github.com/search/code?q={dork}&sort=indexed"
            res = requests.get(url, headers=headers, timeout=15).json()
            for item in res.get('items', []):
                raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                try:
                    content = requests.get(raw_url, timeout=5).text
                    # 关键修复点：先解码再匹配
                    decoded_content = auto_decode_base64(content)
                    matches = re.findall(NODE_PATTERN, decoded_content, re.IGNORECASE)
                    found.update(matches)
                except: continue
            time.sleep(2)
        except: pass
    return found

def fetch_from_sources(url):
    try:
        print(f"📡 抓取源: {url}")
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            matches = re.findall(NODE_PATTERN, content, re.IGNORECASE)
            print(f"   📊 提取到 {len(matches)} 个完整链接")
            return matches
    except:
        pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量节点收割（修正正则分组问题）...")
    
    all_nodes = set()

    # 1. 抓取外部聚合源
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: all_nodes.update(nodes)

    # 2. 抓取 GitHub 搜索结果
    all_nodes.update(fetch_from_github())

    # 3. 结果保存
    unique_list = sorted(list(set(all_nodes)))
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        # 确保每行一个完整节点链接
        f.write("\n".join(unique_list))

    print(f"✅ 处理完成！")
    print(f"📦 成功收割完整节点链接: {len(unique_list)} 个")
    if len(unique_list) > 0:
        print(f"📝 预览第一个节点: {unique_list[0][:50]}...")

if __name__ == "__main__":
    main()
