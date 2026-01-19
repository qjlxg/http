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
MAX_WORKERS = 20  # 并发数
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clean_vmess(vmess_link):
    """深度清洗 VMess 节点"""
    try:
        b64_data = vmess_link.replace('vmess://', '')
        # 补全填充并解码
        missing_padding = len(b64_data) % 4
        if missing_padding: b64_data += '=' * (4 - missing_padding)
        data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
        
        # 移除备注(ps)和无关统计项
        core_fields = ['add', 'port', 'id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp']
        clean_data = {k: v for k, v in data.items() if k in core_fields}
        # 重新按照字母顺序排序 key，确保去重一致性
        sorted_str = json.dumps(clean_data, sort_keys=True)
        return f"vmess://{base64.b64encode(sorted_str.encode('utf-8')).decode('utf-8')}"
    except:
        return None

def standardize_node(node_str):
    """标准化 SS/Trojan/Vless/Hy2 等节点"""
    try:
        # 预处理：去掉末尾可能的 HTML 标签或干扰
        node_str = re.split(r'[<"\s\']', node_str)[0]
        
        if node_str.startswith('vmess://'):
            return clean_vmess(node_str)
            
        u = urlparse(node_str)
        # 核心：协议 + 用户信息(去备注) + 地址端口
        netloc = u.netloc.split('#')[0]
        
        # 处理查询参数，只保留核心连接参数
        query = parse_qs(u.query)
        # 排除掉所有非连接必须的字段
        keep_params = ['type', 'security', 'sni', 'fp', 'path', 'serviceName', 'mode', 'cert']
        new_query_dict = {k: v for k, v in query.items() if k in keep_params}
        
        new_query = urlencode(new_query_dict, doseq=True)
        standardized = f"{u.scheme}://{netloc}"
        if new_query:
            standardized += f"?{new_query}"
        return standardized
    except:
        return None

def extract_nodes_from_text(text):
    """从杂乱的文本中正则提取节点"""
    # 匹配各类协议的正则表达式
    pattern = r'(ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\']+'
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    # 重新拼接完整的匹配项
    found_urls = re.findall(r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\']+', text)
    
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
            res = requests.get(f"{protocol}{clean_url}", timeout=(5, 10), verify=False, headers=HEADERS)
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
    
    # 尝试 Base64 解码整个页面内容（针对常见的订阅格式）
    try:
        decoded_text = base64.b64decode(text).decode('utf-8')
        nodes = extract_nodes_from_text(decoded_text)
    except:
        nodes = extract_nodes_from_text(text)
        
    log(f"Done: {url} | Found: {len(nodes)}")
    return {'url': url, 'nodes': nodes, 'protocol': protocol, 'status': 'Success'}

def main():
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    all_nodes = set()
    stats = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            r = f.result()
            all_nodes.update(r['nodes'])
            stats.append([r['url'], r['protocol'], len(r['nodes']), r['status']])

    # 存储结果
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    # 保存去重后的节点池
    with open(os.path.join(month_dir, f"fetch_nodes_{ts}.txt"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(all_nodes)))
    
    # 保存详细统计
    with open(os.path.join(month_dir, f"fetch_nodes_{ts}.csv"), 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Domain', 'Protocol', 'StandardNodes', 'Status'])
        writer.writerows(stats)
    
    log(f"Finished. Total Unique Nodes: {len(all_nodes)}")

if __name__ == "__main__":
    main()
