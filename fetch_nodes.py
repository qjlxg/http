import requests
import base64
import yaml
import os
import csv
import urllib3
import re
import sys
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote, urlencode, parse_qs

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
# 新增：根目录固定文件名
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'

MAX_WORKERS = 80  
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clean_vmess(vmess_link):
    """深度清洗 VMess 节点"""
    try:
        b64_data = vmess_link.replace('vmess://', '')
        missing_padding = len(b64_data) % 4
        if missing_padding: b64_data += '=' * (4 - missing_padding)
        data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
        
        # 核心字段校验
        if not data.get('add') or not data.get('port'):
            return None

        core_fields = ['add', 'port', 'id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp']
        clean_data = {k: v for k, v in data.items() if k in core_fields}
        sorted_str = json.dumps(clean_data, sort_keys=True)
        return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
    except:
        return None

def standardize_node(node_str):
    """标准化并过滤无效节点"""
    try:
        node_str = re.split(r'[<"\s\'\`,]', node_str)[0]
        
        # 过滤占位符和垃圾字符
        invalid_keywords = ['${', '...', 'host:port', 'server:port', 'BASE64', 'your_', 'userinfo', 'password@', 'nodeAddr']
        if any(k in node_str for k in invalid_keywords) or len(node_str) < 15:
            return None
            
        if node_str.startswith('vmess://'):
            return clean_vmess(node_str)
            
        u = urlparse(node_str)
        # 结构校验：必须有地址和端口
        if not u.netloc or (':' not in u.netloc and not re.search(r'\d+\.\d+', u.netloc)):
            return None

        netloc = u.netloc.split('#')[0]
        query = parse_qs(u.query)
        keep_params = ['type', 'security', 'sni', 'fp', 'path', 'serviceName', 'mode', 'cert', 'sid', 'pbk']
        new_query_dict = {k: v for k, v in query.items() if k in keep_params}
        
        new_query = urlencode(new_query_dict, doseq=True)
        standardized = f"{u.scheme}://{netloc}"
        if new_query:
            standardized += f"?{new_query}"
        return standardized
    except:
        return None

def extract_nodes_from_text(text):
    """从文本中正则提取节点"""
    pattern = r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\'\`]+'
    found_urls = re.findall(pattern, text, re.IGNORECASE)
    
    results = set()
    for raw in found_urls:
        std = standardize_node(raw)
        if std:
            results.add(std)
    return results

def get_content(url):
    clean_url = url.strip().replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        try:
            res = requests.get(f"{protocol}{clean_url}", timeout=(5, 15), verify=False, headers=HEADERS, allow_redirects=True)
            if res.status_code == 200:
                return res.text, protocol
        except: continue
    return None, None

def process_url(url):
    log(f"Fetch: {url}")
    text, protocol = get_content(url)
    if not text:
        log(f"Fail: {url}")
        return {'url': url, 'nodes': set(), 'protocol': 'None', 'status': 'Fail'}
    
    try:
        decoded_text = base64.b64decode(text.strip()).decode('utf-8')
        nodes = extract_nodes_from_text(decoded_text)
    except:
        nodes = extract_nodes_from_text(text)
        
    log(f"Done: {url} | Found: {len(nodes)}")
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
            try:
                r = f.result()
                all_nodes.update(r['nodes'])
                stats.append([r['url'], r['protocol'], len(r['nodes']), r['status']])
            except Exception as e:
                log(f"Worker Error: {e}")

    # --- 存储逻辑 ---
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    sorted_nodes_list = sorted(list(all_nodes))

    # 1. 保存到分类文件夹 (带时间戳)
    history_txt = os.path.join(month_dir, f"fetch_nodes_{ts}.txt")
    history_csv = os.path.join(month_dir, f"fetch_nodes_{ts}.csv")
    
    # 2. 写入文件 (封装一下写入操作)
    def save_data(txt_path, csv_path):
        if sorted_nodes_list:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted_nodes_list))
        
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Domain', 'Protocol', 'StandardNodes', 'Status'])
            writer.writerows(stats)

    # 执行保存：历史记录
    save_data(history_txt, history_csv)
    
    # 执行保存：根目录 (最新一份)
    save_data(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    
    log(f"--- Finished ---")
    log(f"Total Unique Nodes: {len(all_nodes)}")
    log(f"Latest results updated in root: {ROOT_LATEST_TXT}")

if __name__ == "__main__":
    main()
