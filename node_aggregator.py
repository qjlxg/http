import requests
import re
import os
import time
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"
# 协议匹配正则
NODE_PATTERN = r'(vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[^\s^"\'\(\)]+'

# 节点池（直接存放节点的文件地址）
RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/mueiba/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/v2ray-free/free/main/v2ray",
    "https://raw.githubusercontent.com/StaySleepless/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/v2ray.txt"
]

GITHUB_DORKS = [
    'extension:txt "vmess://"',
    'extension:txt "vless://"',
    'extension:txt "trojan://"',
    'filename:nodes.txt "ss://"',
    'filename:README.md "更新时间" "vmess://"'
]

def auto_decode_base64(text):
    """尝试各种姿势解码内容"""
    text = text.strip()
    # 1. 已经是明文节点列表
    if "://" in text:
        return text
    # 2. 尝试 Base64 解码
    try:
        # 补齐填充
        missing_padding = len(text) % 4
        if missing_padding:
            text += '=' * (4 - missing_padding)
        decoded = base64.b64decode(text).decode('utf-8')
        return decoded
    except:
        return text

def get_github_raw_nodes():
    if not GITHUB_TOKEN: return set()
    found_nodes = set()
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    for dork in GITHUB_DORKS:
        try:
            url = f"https://api.github.com/search/code?q={dork}&sort=indexed"
            res = requests.get(url, headers=headers, timeout=20).json()
            items = res.get('items', [])
            print(f"🔍 Dork [{dork}] 命中 {len(items)} 个文件")
            for item in items:
                raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                try:
                    c = requests.get(raw_url, timeout=5).text
                    decoded_c = auto_decode_base64(c)
                    nodes = re.findall(NODE_PATTERN, decoded_c)
                    found_nodes.update(nodes)
                except: continue
            time.sleep(2) # 避免 API 限制
        except: pass
    return found_nodes

def fetch_source(src):
    """下载并解析单个源"""
    try:
        print(f"📡 正在请求: {src}")
        res = requests.get(src, timeout=10)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            nodes = re.findall(NODE_PATTERN, content)
            print(f"   ✨ 从 {src[-15:]} 提取到 {len(nodes)} 个节点")
            return nodes
    except:
        return []

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量收割模式（跳过 TCP 验证）...")
    
    all_raw = set()

    # 1. 并发抓取外部源
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_source, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: all_raw.update(nodes)

    # 2. 抓取 GitHub 搜索结果
    print("🔍 启动 GitHub 深度挖掘...")
    all_raw.update(get_github_raw_nodes())

    # 3. 结果去重并保存（不再进行 check_tcp_alive）
    unique_nodes = sorted(list(set(all_raw)))
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(unique_nodes))

    print(f"✅ 完成！共收获节点: {len(unique_nodes)} 个")
    print(f"📁 结果已保存至 {OUTPUT_DIR}/nodes.txt")
    print(f"⏱️ 耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
