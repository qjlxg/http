import requests
import re
import os
import time
import socket
import json
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"
# 更加宽松的正则，防止漏掉带参数的节点
NODE_PATTERN = r'(vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[^\s^"\'\(\)]+'
BAD_KEYWORDS = ['过期', '流量', '耗尽', '维护', '重置']

# 实时更新的节点聚合源 (这些源目前非常稳，每天更新上万节点)
RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/mueiba/free-nodes/main/nodes.txt",
    "https://raw.githubusercontent.com/v2ray-free/free/main/v2ray",
    "https://raw.githubusercontent.com/StaySleepless/free-nodes/main/nodes.txt"
]

GITHUB_DORKS = [
    'extension:txt "vmess://"',
    'extension:txt "vless://"',
    'extension:txt "trojan://"',
    'filename:nodes.txt "ss://"'
]

# --- 功能函数 ---

def check_tcp_alive(node_url):
    """TCP 探测：2秒超时"""
    try:
        host, port = None, None
        if node_url.startswith(('ss://', 'trojan://', 'vless://', 'ssr://', 'hysteria2://', 'hysteria://', 'tuic://')):
            if '@' in node_url:
                part = node_url.split('@')[1].split('#')[0].split('?')[0]
                if ':' in part:
                    host, port = part.split(':')[0], int(part.split(':')[1])
        elif node_url.startswith('vmess://'):
            b64_data = node_url.replace('vmess://', '')
            b64_data += '=' * (-len(b64_data) % 4)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            host, port = data['add'], int(data['port'])
        
        if host and port:
            with socket.create_connection((host, port), timeout=2.0):
                return True
    except:
        pass
    return False

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
                    nodes = re.findall(NODE_PATTERN, c)
                    found_nodes.update(nodes)
                except: continue
            time.sleep(2)
        except: pass
    return found_nodes

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🛰️ 启动多维节点收割机...")
    
    all_raw = set()

    # 1. 抓取外部聚合源
    for src in RAW_NODE_SOURCES:
        try:
            print(f"📡 正在请求聚合源: {src}")
            res = requests.get(src, timeout=10)
            if res.status_code == 200:
                # 尝试对整个返回内容进行 Base64 探测解码
                text = res.text
                try:
                    # 有些源是全 base64 编码的
                    text = base64.b64decode(text).decode('utf-8')
                except:
                    pass
                nodes = re.findall(NODE_PATTERN, text)
                all_raw.update(nodes)
                print(f"   ✨ 发现 {len(nodes)} 个候选")
        except: pass

    # 2. 抓取 GitHub 搜索
    print("🔍 启动 GitHub 深度挖掘...")
    all_raw.update(get_github_raw_nodes())

    # 3. 验证
    print(f"⚙️ 开始对 {len(all_raw)} 个原始数据进行 TCP 验证...")
    def verify(node):
        if any(w in node for w in BAD_KEYWORDS): return None
        if check_tcp_alive(node): return node
        return None

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(verify, list(all_raw)))
        final_nodes = [r for r in results if r]

    # 4. 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(list(set(final_nodes)))))

    print(f"✅ 完成！真·活节点总数: {len(final_nodes)}")
    print(f"⏱️ 耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
