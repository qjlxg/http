import requests
import base64
import yaml
import os
import csv
import urllib3
import re
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote, urlencode, parse_qs

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
MAX_WORKERS = 65  # 略微调高并发数

# 定义合法协议前缀
SUPPORTED_SCHEMES = ['ss', 'ssr', 'vmess', 'vless', 'trojan', 'hysteria', 'hy2']

def log(msg):
    """实时打印日志"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def standardize_node(node_str):
    """标准化节点：提取核心要素，去除备注，用于精准去重"""
    node_str = node_str.strip()
    if not node_str: return None
    
    try:
        # 简单处理 vmess (通常是base64 json)
        if node_str.startswith('vmess://'):
            # vmess 协议通常不带 # 备注，如果带了则截断
            return node_str.split('#')[0]
            
        u = urlparse(node_str)
        if u.scheme not in SUPPORTED_SCHEMES:
            return None
        
        # 核心要素：协议、用户信息(密码/UUID)、地址、端口
        core_netloc = u.netloc.split('#')[0]
        
        # 过滤掉备注类查询参数
        query = parse_qs(u.query)
        for skip_arg in ['remarks', 'name', 'title', 'group', 'memo']:
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
    valid_nodes = set()
    if not content: return valid_nodes

    lines = []
    # 尝试 Base64 解码整个内容
    try:
        b64_str = re.sub(r'\s+', '', content)
        missing_padding = len(b64_str) % 4
        if missing_padding: b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        lines = decoded.splitlines()
    except:
        lines = content.splitlines()

    for line in lines:
        std = standardize_node(line)
        if std:
            valid_nodes.add(std)
    return valid_nodes

def get_content(url):
    url = url.strip()
    if not url: return None, None, 0
    clean_url = url.replace('https://', '').replace('http://', '')
    
    # 优先尝试 https
    for protocol in ['https://', 'http://']:
        target = f"{protocol}{clean_url}"
        try:
            # 缩短超时时间：连接5秒，读取8秒
            response = requests.get(target, timeout=(5, 8), verify=False)
            if response.status_code == 200:
                return response.text, protocol, 200
        except Exception as e:
            continue
    return None, None, "Timeout/Error"

def process_url(url):
    log(f"正在抓取: {url} ...")
    content, protocol, status = get_content(url)
    nodes = parse_nodes(content) if content else set()
    log(f"完成: {url} (找到 {len(nodes)} 个标准节点)")
    return {
        'url': url, 
        'protocol': protocol or "None", 
        'nodes': nodes, 
        'count': len(nodes), 
        'status': "Success" if content else f"Fail({status})"
    }

def main():
    if not os.path.exists(INPUT_FILE):
        log("错误: 未找到 http.txt 文件")
        return

    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    if not urls:
        log("http.txt 为空")
        return

    log(f"开始并行处理 {len(urls)} 个域名，并发线程数: {MAX_WORKERS}")
    
    all_nodes_global = set()
    stats_data = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in as_completed(future_to_url):
            try:
                res = future.result()
                all_nodes_global.update(res['nodes'])
                stats_data.append([res['url'], res['protocol'], res['count'], res['status']])
            except Exception as e:
                log(f"处理任务时发生严重错误: {e}")

    # 归档处理
    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    current_month = now.strftime('%Y-%m')
    dir_path = os.path.join(OUTPUT_BASE_DIR, current_month)
    os.makedirs(dir_path, exist_ok=True)

    txt_name = f"fetch_nodes_{timestamp}.txt"
    csv_name = f"fetch_nodes_{timestamp}.csv"

    # 保存 TXT
    with open(os.path.join(dir_path, txt_name), 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(all_nodes_global)))

    # 保存 CSV
    with open(os.path.join(dir_path, csv_name), 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Domain', 'Protocol', 'StandardizedNodes', 'Status'])
        writer.writerows(stats_data)

    log(f"任务结束。总计捕获唯一节点: {len(all_nodes_global)}")
    log(f"结果已存入目录: {dir_path}")

if __name__ == "__main__":
    main()
