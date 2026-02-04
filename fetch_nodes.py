import requests
import base64
import json
import os
import csv
import urllib3
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlencode, parse_qs, unquote

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'
MAX_WORKERS = 80  
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clean_vmess(vmess_link):
    """深度去重 VMess：删除所有备注和统计字段"""
    try:
        b64_data = vmess_link.replace('vmess://', '')
        missing_padding = len(b64_data) % 4
        if missing_padding: b64_data += '=' * (4 - missing_padding)
        data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
        
        if not data.get('add') or not data.get('port'): return None
        
        # 核心连接字段白名单 (排除了 ps 备注字段)
        core_fields = ['add', 'port', 'id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp']
        clean_data = {k: v for k, v in data.items() if k in core_fields and v}
        
        # 通过排序 key 序列化，确保去重一致性
        sorted_str = json.dumps(clean_data, sort_keys=True)
        return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
    except: return None

def standardize_node(node_str):
    """标准化所有节点，剔除备注和冗余参数"""
    try:
        # 1. 基础过滤与截断
        node_str = re.split(r'[<"\s\'\`,]', node_str)[0]
        if len(node_str) < 12: return None
        
        # 2. 针对协议处理
        if node_str.startswith('vmess://'):
            return clean_vmess(node_str)
            
        # 3. 处理 SS/VLESS/Trojan 等 URL 格式
        # 移除 # 及其后面的备注信息
        node_str = node_str.split('#')[0]
        
        u = urlparse(node_str)
        if not u.netloc: return None

        # 核心：地址、端口、认证信息
        netloc = u.netloc
        
        # 4. 参数清洗
        query = parse_qs(u.query)
        # 仅保留影响连接的必要参数，剔除 ps、remark、source 等
        keep_params = ['type', 'security', 'sni', 'fp', 'path', 'serviceName', 'mode', 'cert', 'sid', 'pbk', 'plugin', 'encryption']
        new_query_dict = {k: sorted(v) for k, v in query.items() if k.lower() in keep_params}
        
        # 重新按字母序组装参数，防止因为参数顺序不同导致的重复
        new_query = urlencode(new_query_dict, doseq=True)
        
        standardized = f"{u.scheme}://{netloc}"
        if new_query:
            standardized += f"?{new_query}"
            
        return standardized
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
            res = requests.get(f"{protocol}{clean_url}", timeout=(10, 20), verify=False, headers=HEADERS, allow_redirects=True)
            if res.status_code == 200: return res.text, protocol
        except: continue
    return None, None

def process_url(url):
    log(f"Fetch: {url}")
    text, protocol = get_content(url)
    if not text:
        return {'url': url, 'nodes': set(), 'protocol': 'None', 'status': 'Fail'}
    
    # 自动识别 Base64 订阅
    try:
        # 如果是标准的订阅内容（Base64 编码的列表），先解码
        # 简单的 Base64 检测逻辑
        if not any(s in text for s in ['://', 'vmess', 'vless', 'ss']):
            decoded_text = base64.b64decode(text.strip()).decode('utf-8')
            nodes = extract_nodes_from_text(decoded_text)
        else:
            nodes = extract_nodes_from_text(text)
    except:
        nodes = extract_nodes_from_text(text)
        
    return {'url': url, 'nodes': nodes, 'protocol': protocol, 'status': 'Success'}

def main():
    if not os.path.exists(INPUT_FILE):
        log(f"Error: {INPUT_FILE} not found.")
        return
        
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    all_nodes = set()
    stats = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            r = f.result()
            all_nodes.update(r['nodes'])
            stats.append([r['url'], r['protocol'], len(r['nodes']), r['status']])
            log(f"Done: {r['url']} | New: {len(r['nodes'])}")

    # 存储逻辑
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    sorted_nodes = sorted(list(all_nodes))

    def save_to_file(txt_p, csv_p):
        with open(txt_p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted_nodes))
        with open(csv_p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Source URL', 'Protocol', 'Node Count', 'Status'])
            writer.writerows(stats)

    save_to_file(os.path.join(month_dir, f"fetch_{ts}.txt"), os.path.join(month_dir, f"fetch_{ts}.csv"))
    save_to_file(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    
    log(f"Finished. Unique nodes after deep clean: {len(all_nodes)}")

if __name__ == "__main__":
    main()
