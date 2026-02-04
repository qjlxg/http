import requests
import base64
import json
import os
import csv
import urllib3
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote, quote, urlencode, parse_qs

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'
MAX_WORKERS = 80
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def safe_decode_base64(s):
    """鲁棒的 Base64 解码"""
    s = s.strip()
    try:
        # 补全填充
        padding = len(s) % 4
        if padding: s += "=" * (4 - padding)
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except:
        return None

def parse_and_clean_node(raw_url):
    """解析并进行最小化清理（仅去除备注和非法参数）"""
    try:
        # 1. 基础预处理：去掉 HTML 干扰
        raw_url = re.split(r'[<"\s\'\`,]', raw_url)[0]
        if '://' not in raw_url: return None
        
        parsed = urlparse(raw_url)
        proto = parsed.scheme.lower()
        
        # 仅处理已知协议
        valid_protos = ['ss', 'ssr', 'vmess', 'vless', 'trojan', 'hysteria', 'hysteria2', 'hy2', 'tuic']
        if proto not in valid_protos: return None

        # 2. 特殊处理 VMess (JSON 格式)
        if proto == 'vmess':
            content = raw_url.split('://')[1]
            decoded = safe_decode_base64(content)
            if not decoded: return None
            data = json.loads(decoded)
            if not data.get('add'): return None
            # 清理：仅移除 ps (备注)，保留其他所有参数
            data.pop('ps', None)
            return {'fp': f"vmess|{data.get('add')}|{data.get('port')}|{data.get('id')}", 
                    'content': data, 'proto': 'vmess'}

        # 3. 处理标准 URL 协议
        # 移除备注 (#)
        clean_url_no_tag = raw_url.split('#')[0]
        u = urlparse(clean_url_no_tag)
        
        # 提取指纹 (用于去重)
        netloc = u.netloc
        auth = netloc.split('@')[0] if '@' in netloc else ""
        addr = netloc.split('@')[-1]
        
        # 简单的指纹：协议+地址+账号部分
        fingerprint = f"{proto}|{addr}|{auth}"
        
        # 过滤明显的占位符
        if 'server' in addr or 'host' in addr or '${' in addr: return None

        return {'fp': fingerprint, 'content': clean_url_no_tag, 'proto': proto}
    except:
        return None

def process_url(url):
    log(f"Fetching: {url}")
    try:
        res = requests.get(url, timeout=(10, 25), verify=False, headers=HEADERS)
        if res.status_code != 200: return []
        text = res.text
        
        # 尝试解码 Base64 订阅页
        if "://" not in text and len(text) > 30:
            decoded = safe_decode_base64(text)
            if decoded: text = decoded
    except:
        return []

    # 提取所有链接
    pattern = r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2|tuic)://[^\s<"\'\`]+'
    raw_found = re.findall(pattern, text, re.IGNORECASE)
    
    results = []
    for raw in raw_found:
        cleaned = parse_and_clean_node(raw)
        if cleaned:
            results.append(cleaned)
    return results

def main():
    if not os.path.exists(INPUT_FILE):
        log(f"Error: {INPUT_FILE} not found.")
        return
        
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    all_node_data = []
    global_fps = set()
    stats = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            source_url = futures[f]
            nodes_from_url = f.result()
            
            new_count = 0
            for n in nodes_from_url:
                if n['fp'] not in global_fps:
                    global_fps.add(n['fp'])
                    all_node_data.append(n)
                    new_count += 1
            
            stats.append([source_url, new_count, "Success" if nodes_from_url else "Empty"])
            log(f"Done: {source_url} | New Nodes: {new_count}")

    # --- 重新命名并生成最终 URL ---
    final_urls = []
    # 按协议排序
    all_node_data.sort(key=lambda x: x['proto'])
    
    for i, n in enumerate(all_node_data):
        custom_name = f"{n['proto'].upper()}_{i+1:03d}"
        
        if n['proto'] == 'vmess':
            data = n['content']
            data['ps'] = custom_name
            final_urls.append(f"vmess://{base64.b64encode(json.dumps(data).encode()).decode()}")
        else:
            # 直接拼接自定义名称
            final_urls.append(f"{n['content']}#{quote(custom_name)}")

    # --- 保存结果 ---
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    # 历史记录
    with open(os.path.join(month_dir, f"nodes_{ts}.txt"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_urls))
        
    # 根目录最新结果
    with open(ROOT_LATEST_TXT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_urls))
        
    # 统计表
    with open(ROOT_LATEST_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Source', 'Unique_Count', 'Status'])
        writer.writerows(stats)

    log(f"--- Finished ---")
    log(f"Total Unique Nodes Found: {len(final_urls)}")

if __name__ == "__main__":
    main()
