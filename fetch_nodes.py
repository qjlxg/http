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

INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'
MAX_WORKERS = 100  # 增加并发提高检测速度
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def ping_node(node_url, timeout=2):
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
        with socket.create_connection((addr, int(port)), timeout=timeout):
            latency = (datetime.now() - start).total_seconds() * 1000
            return True, int(latency)
    except:
        return False, 9999

def clean_and_rename_node(node_url, index, latency):
    """清洗节点参数并自定义名称"""
    try:
        scheme = node_url.split('://')[0].upper()
        new_name = f"Node_{scheme}_{index:03d}_{latency}ms"
        
        if node_url.startswith('vmess://'):
            b64_data = node_url.replace('vmess://', '')
            missing_padding = len(b64_data) % 4
            if missing_padding: b64_data += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            data['ps'] = new_name # 自定义名称
            sorted_str = json.dumps(data, sort_keys=True)
            return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
        else:
            # 处理其他协议的备注 (#后面部分)
            base_url = node_url.split('#')[0]
            return f"{base_url}#{new_name}"
    except:
        return node_url

def standardize_node(node_str):
    """指纹级去重逻辑"""
    try:
        node_str = re.split(r'[<"\s\'\`,]', node_str)[0]
        if len(node_str) < 12: return None
        
        if node_str.startswith('vmess://'):
            b64_data = node_url_part = node_str.replace('vmess://', '')
            missing_padding = len(b64_data) % 4
            if missing_padding: b64_data += '=' * (4 - missing_padding)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            core_fields = ['add', 'port', 'id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni']
            clean_data = {k: v for k, v in data.items() if k in core_fields and v}
            sorted_str = json.dumps(clean_data, sort_keys=True)
            return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
        
        u = urlparse(node_str.split('#')[0])
        query = parse_qs(u.query)
        keep_params = ['type', 'security', 'sni', 'fp', 'path', 'serviceName', 'mode', 'pbk', 'sid']
        new_query = urlencode({k: sorted(v) for k, v in query.items() if k.lower() in keep_params}, doseq=True)
        return f"{u.scheme}://{u.netloc}{'?' + new_query if new_query else ''}"
    except: return None

def extract_nodes_from_text(text):
    pattern = r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\'\`]+'
    found_urls = re.findall(pattern, text, re.IGNORECASE)
    results = set()
    for raw in found_urls:
        std = standardize_node(raw)
        if std: results.add(std)
    return results

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
    try:
        if not any(s in text for s in ['://', 'vmess', 'vless']):
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

    raw_all_nodes = set()
    fetch_stats = []
    
    log(f"Starting fetch from {len(urls)} sources...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS//2) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            r = f.result()
            raw_all_nodes.update(r['nodes'])
            fetch_stats.append([r['url'], r['protocol'], len(r['nodes']), r['status']])

    log(f"Fetch done. Unique nodes: {len(raw_all_nodes)}. Starting connectivity test...")

    # 并发检测延迟
    valid_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ping_executor:
        ping_futures = {ping_executor.submit(ping_node, node): node for node in raw_all_nodes}
        for f in as_completed(ping_futures):
            node = ping_futures[f]
            is_ok, latency = f.result()
            if is_ok:
                valid_results.append({'url': node, 'latency': latency})

    # 按延迟排序
    valid_results.sort(key=lambda x: x['latency'])
    
    # 重命名并构建最终列表
    final_nodes = []
    for i, item in enumerate(valid_results, 1):
        renamed = clean_and_rename_node(item['url'], i, item['latency'])
        final_nodes.append(renamed)

    # 存储逻辑
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    def save_files(txt_p, csv_p):
        with open(txt_p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_nodes))
        with open(csv_p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Source URL', 'Protocol', 'Node Count', 'Status'])
            writer.writerows(fetch_stats)

    save_files(os.path.join(month_dir, f"fetch_{ts}.txt"), os.path.join(month_dir, f"fetch_{ts}.csv"))
    save_files(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    
    log(f"Finished. Total nodes found: {len(raw_all_nodes)}, Live: {len(final_nodes)}")

if __name__ == "__main__":
    main()
