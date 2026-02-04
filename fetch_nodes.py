import requests
import base64
import json
import os
import csv
import urllib3
import re
import socket
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlencode, parse_qs

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置参数
INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'
MAX_WORKERS = 100 
TIMEOUT_PING = 2 # TCP 测速超时（秒）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def ping_node(node_url):
    """检测节点 TCP 连通性并返回延迟"""
    try:
        addr, port = None, None
        if node_url.startswith('vmess://'):
            b64_data = node_url.replace('vmess://', '')
            missing_padding = len(b64_data) % 4
            if missing_padding: b64_data += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            addr, port = data.get('add'), data.get('port')
        else:
            u = urlparse(node_url)
            addr, port = u.hostname, u.port
        
        if not addr or not port: return False, 9999
        
        start = datetime.now()
        with socket.create_connection((addr, int(port)), timeout=TIMEOUT_PING):
            latency = (datetime.now() - start).total_seconds() * 1000
            return True, int(latency)
    except:
        return False, 9999

def standardize_and_get_fingerprint(node_str):
    """
    核心去重逻辑：协议 + 地址 + 端口
    目的是：同一个IP如果同时有SS和VLESS，都保留；但如果有多个VLESS，只保留一个。
    """
    try:
        node_str = re.split(r'[<"\s\'\`,]', node_str)[0]
        if len(node_str) < 12: return None, None
        
        protocol = node_str.split('://')[0].lower()
        addr, port = None, None
        
        if protocol == 'vmess':
            b64_data = node_str.replace('vmess://', '')
            missing_padding = len(b64_data) % 4
            if missing_padding: b64_data += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            addr, port = data.get('add'), data.get('port')
        else:
            u = urlparse(node_str.split('#')[0])
            addr, port = u.hostname, u.port
            
        if not addr or not port: return None, None
        
        # 指纹标识：协议 + 地址 + 端口
        fingerprint = f"{protocol}://{addr}:{port}"
        return fingerprint, node_str
    except:
        return None, None

def clean_and_rename_node(node_url, index, latency):
    """重命名节点：自定义格式 Node_协议_序号_延迟"""
    try:
        protocol_raw = node_url.split('://')[0].upper()
        new_name = f"Node_{protocol_raw}_{index:03d}_{latency}ms"
        
        if node_url.startswith('vmess://'):
            b64_data = node_url.replace('vmess://', '')
            missing_padding = len(b64_data) % 4
            if missing_padding: b64_data += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            # 清理所有备注字段
            data['ps'] = new_name
            # 移除可能存在的统计信息字段（常见于一些面板导出的链接）
            data.pop('remark', None)
            sorted_str = json.dumps(data, sort_keys=True)
            return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
        else:
            # 去除旧备注，添加新名称
            base_url = node_url.split('#')[0]
            return f"{base_url}#{new_name}"
    except:
        return node_url

def extract_nodes_from_text(text):
    pattern = r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\'\`]+'
    found_urls = re.findall(pattern, text, re.IGNORECASE)
    
    unique_pool = {} # 使用字典按指纹去重
    for raw in found_urls:
        fingerprint, clean_url = standardize_and_get_fingerprint(raw)
        if fingerprint and fingerprint not in unique_pool:
            unique_pool[fingerprint] = clean_url
    return set(unique_pool.values())

def get_content(url):
    clean_url = url.strip().replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        try:
            res = requests.get(f"{protocol}{clean_url}", timeout=(10, 15), verify=False, headers=HEADERS)
            if res.status_code == 200: return res.text, protocol
        except: continue
    return None, None

def process_url(url):
    text, protocol = get_content(url)
    if not text: return {'url': url, 'nodes': set(), 'protocol': 'None', 'status': 'Fail'}
    # 自动识别 Base64 订阅
    try:
        if "://" not in text[:100] and len(text) > 20:
            text = base64.b64decode(text.strip()).decode('utf-8', errors='ignore')
    except: pass
    nodes = extract_nodes_from_text(text)
    return {'url': url, 'nodes': nodes, 'protocol': protocol, 'status': 'Success'}

def main():
    if not os.path.exists(INPUT_FILE):
        log(f"Error: {INPUT_FILE} not found.")
        return
        
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    # 第一阶段：爬取与初步去重
    raw_node_pool = set()
    fetch_stats = []
    log(f"Step 1: Fetching from {len(urls)} sources...")
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            r = f.result()
            raw_node_pool.update(r['nodes'])
            fetch_stats.append([r['url'], r['protocol'], len(r['nodes']), r['status']])
            log(f"Fetched: {r['url']} ({len(r['nodes'])} nodes)")

    # 第二阶段：物理地址级深度去重（跨订阅去重）
    # 同协议、同IP、同端口的节点，在这一步会被压缩
    log(f"Step 2: Deep cleaning... Unique candidates: {len(raw_node_pool)}")
    final_dedup_pool = {}
    for node in raw_node_pool:
        fp, url = standardize_and_get_fingerprint(node)
        if fp and fp not in final_dedup_pool:
            final_dedup_pool[fp] = url

    # 第三阶段：并发测速
    log(f"Step 3: Testing {len(final_dedup_pool)} nodes...")
    live_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ping_executor:
        ping_futures = {ping_executor.submit(ping_node, url): url for url in final_dedup_pool.values()}
        for f in as_completed(ping_futures):
            node_url = ping_futures[f]
            is_ok, latency = f.result()
            if is_ok:
                live_results.append({'url': node_url, 'latency': latency})

    # 第四阶段：排序与重命名
    live_results.sort(key=lambda x: x['latency'])
    final_output_nodes = []
    for i, item in enumerate(live_results, 1):
        renamed = clean_and_rename_node(item['url'], i, item['latency'])
        final_output_nodes.append(renamed)

    # 存储逻辑
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    def save_files(txt_p, csv_p):
        with open(txt_p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_output_nodes))
        with open(csv_p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Source URL', 'Protocol', 'Node Count', 'Status'])
            writer.writerows(fetch_stats)

    save_files(os.path.join(month_dir, f"fetch_{ts}.txt"), os.path.join(month_dir, f"fetch_{ts}.csv"))
    save_files(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    
    log(f"DONE! Unique: {len(final_dedup_pool)} | Live: {len(final_output_nodes)}")

if __name__ == "__main__":
    main()
