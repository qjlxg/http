import requests
import base64
import yaml
import os
import csv
import urllib3
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote, urlencode, parse_qs

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
MAX_WORKERS = 50

# 定义合法协议前缀
SUPPORTED_SCHEMES = ['ss', 'ssr', 'vmess', 'vless', 'trojan', 'hysteria', 'hy2']

def standardize_node(node_str):
    """
    标准化节点：提取核心要素，去除备注和冗余参数，用于精准去重
    """
    node_str = node_str.strip()
    if not node_str: return None
    
    try:
        # 处理 vmess (通常是base64)
        if node_str.startswith('vmess://'):
            # vmess 内部包含大量非标准要素，通常保留核心地址、端口、uuid
            return node_str.split('#')[0] # 简单处理：截断备注
            
        # 通用解析 (ss, vless, trojan, hy2等)
        u = urlparse(node_str)
        if u.scheme not in SUPPORTED_SCHEMES:
            return None
        
        # 核心要素：协议、用户信息(密码/UUID)、地址、端口
        # u.netloc 包含了 user:pass@host:port
        # 移除查询参数中的备注类信息（如流量统计、名称等）
        # 只保留关键传输参数
        core_netloc = u.netloc.split('#')[0]
        
        # 重新构建不带备注的链接
        # 如果是 hysteria/hy2 等，查询参数可能包含重要证书信息，需保留关键参数
        query = parse_qs(u.query)
        # 过滤掉常见的备注/名称参数
        for skip_arg in ['remarks', 'name', 'title', 'group']:
            query.pop(skip_arg, None)
            
        new_query = urlencode(query, doseq=True)
        standardized = f"{u.scheme}://{core_netloc}"
        if new_query:
            standardized += f"?{new_query}"
            
        return standardized
    except:
        return None

def parse_nodes(content):
    """解析并标准化节点"""
    raw_nodes = set()
    if not content: return raw_nodes

    # 1. 尝试 YAML
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict) and 'proxies' in data:
            # 这里简单处理，实际可根据类型转换成链接，此处暂跳过复杂转换
            pass 
    except: pass

    # 2. 尝试 Base64
    try:
        b64_str = content.replace('\r', '').replace('\n', '').strip()
        missing_padding = len(b64_str) % 4
        if missing_padding: b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        lines = decoded.splitlines()
    except:
        lines = content.splitlines()

    # 3. 标准化与过滤
    valid_nodes = set()
    for line in lines:
        std = standardize_node(line)
        if std:
            valid_nodes.add(std)
    return valid_nodes

def get_content(url):
    url = url.strip()
    if not url: return None, None, 0
    clean_url = url.replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        try:
            response = requests.get(f"{protocol}{clean_url}", timeout=10, verify=False)
            if response.status_code == 200:
                return response.text, protocol, 200
        except: continue
    return None, None, "Error"

def process_url(url):
    content, protocol, status = get_content(url)
    nodes = parse_nodes(content) if content else set()
    return {'url': url, 'protocol': protocol or "None", 'nodes': nodes, 'count': len(nodes), 'status': "Success" if content else f"Failed({status})"}

def main():
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    all_nodes_global = set()
    stats_data = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in as_completed(future_to_url):
            res = future.result()
            all_nodes_global.update(res['nodes'])
            stats_data.append([res['url'], res['protocol'], res['count'], res['status']])

    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    path = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(path, exist_ok=True)

    # 保存 TXT
    with open(os.path.join(path, f"fetch_nodes_{timestamp}.txt"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(all_nodes_global)))

    # 保存 CSV 统计
    with open(os.path.join(path, f"fetch_nodes_{timestamp}.csv"), 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Domain', 'Protocol', 'ValidNodeCount', 'Status'])
        writer.writerows(stats_data)

if __name__ == "__main__":
    main()
