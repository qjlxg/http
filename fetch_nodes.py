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

# --- 官方协议参数白名单 (只保留官方定义的关键连接参数) ---
PROTOCOL_CONFIG = {
    'ss': {'whitelist': ['plugin']},
    'vmess': {'whitelist': ['net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp', 'aid']},
    'vless': {'whitelist': ['type', 'security', 'sni', 'fp', 'path', 'host', 'pbk', 'sid', 'serviceName', 'headerType', 'flow']},
    'trojan': {'whitelist': ['type', 'security', 'sni', 'fp', 'path', 'host', 'alpn']},
    'hy2': {'whitelist': ['sni', 'obfs', 'obfs-password']},
    'hysteria2': {'whitelist': ['sni', 'obfs', 'obfs-password']},
    'hysteria': {'whitelist': ['protocol', 'sni', 'peer', 'insecure', 'obfs']},
    'tuic': {'whitelist': ['sni', 'alpn', 'congestion_control', 'udp_relay_mode']}
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def parse_node(raw_url):
    """解析并提取官方核心参数"""
    try:
        raw_url = re.split(r'[<"\s\'\`,]', raw_url)[0]
        if '://' not in raw_url: return None
        
        parsed = urlparse(raw_url)
        proto = parsed.scheme.lower()
        if proto not in PROTOCOL_CONFIG and proto != 'hysteria2': 
            # 兼容 hysteria2 的简写 hy2
            if proto == 'hy2': proto = 'hy2'
            else: return None
        
        res = {'type': proto, 'query': {}}
        conf = PROTOCOL_CONFIG.get(proto, PROTOCOL_CONFIG.get('hy2'))

        # 1. 处理 VMess
        if proto == 'vmess':
            content = raw_url.split('://')[1]
            try:
                padding = len(content) % 4
                if padding: content += "=" * (4 - padding)
                data = json.loads(base64.b64decode(content).decode('utf-8'))
                if not data.get('add') or not data.get('id'): return None
                res['server'], res['port'], res['uuid'] = data['add'], str(data['port']), data['id']
                res['meta'] = {k: data[k] for k in conf['whitelist'] if k in data and data[k]}
                return res
            except: return None

        # 2. 处理标准 URL 格式
        netloc = parsed.netloc.split('#')[0]
        if '@' in netloc:
            user_info = unquote(netloc.split('@')[0])
            server_port = netloc.split('@')[-1]
        else:
            user_info = ""
            server_port = netloc

        # 提取 Server/Port (支持 IPv6)
        if ']' in server_port:
            res['server'] = server_port.split(']')[0] + ']'
            p_part = server_port.split(']')[-1]
            res['port'] = p_part.split(':')[1] if ':' in p_part else "443"
        else:
            res['server'] = server_port.split(':')[0]
            res['port'] = server_port.split(':')[1] if ':' in server_port else "443"

        if not res['server'] or res['server'] in ['server', 'host']: return None

        # 提取账号信息
        if proto == 'ss':
            if ':' in user_info:
                res['cipher'], res['password'] = user_info.split(':', 1)
            else:
                try: # 处理 ss://base64@host:port
                    dec = base64.b64decode(user_info).decode('utf-8')
                    if ':' in dec: res['cipher'], res['password'] = dec.split(':', 1)
                    else: return None
                except: return None
        else:
            res['uuid'] = user_info # 包含 vless/trojan/hy2 的 id 或 password

        # 提取 Query 参数
        qs = parse_qs(parsed.query)
        res['query'] = {k: qs[k] for k in conf['whitelist'] if k in qs}
        return res
    except:
        return None

def rebuild_node(d, name):
    """重组为标准格式"""
    try:
        proto = d['type']
        if proto == 'vmess':
            m = d.get('meta', {})
            m.update({'add': d['server'], 'port': d['port'], 'id': d['uuid'], 'ps': name, 'v': "2"})
            return f"vmess://{base64.b64encode(json.dumps(m).encode()).decode()}"
        else:
            q_str = urlencode(d.get('query', {}), doseq=True)
            auth = f"{d['cipher']}:{d['password']}" if proto == 'ss' else d.get('uuid', '')
            url = f"{proto}://{quote(auth)}@{d['server']}:{d['port']}"
            if q_str: url += f"?{unquote(q_str)}"
            url += f"#{quote(name)}"
            return url
    except:
        return None

def process_url(url):
    log(f"Fetching: {url}")
    try:
        res = requests.get(url, timeout=(10, 20), verify=False, headers=HEADERS)
        if res.status_code != 200: return []
        content = res.text
        
        # 识别是否是全页 Base64 订阅
        if "://" not in content and len(content) > 20:
            try:
                content = base64.b64decode(content.strip()).decode('utf-8')
            except: pass
    except: return []

    raw_urls = re.findall(r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2|tuic)://[^\s<"\'\`]+', content, re.IGNORECASE)
    results = []
    local_fp = set()

    for raw in raw_urls:
        d = parse_node(raw)
        if not d: continue
        
        # 去重指纹
        auth = d.get('uuid') or d.get('password') or ""
        fp = f"{d['type']}|{d['server']}|{d['port']}|{auth}"
        
        if fp not in local_fp:
            local_fp.add(fp)
            results.append(d)
    return results

def main():
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    global_node_dicts = []
    global_fp = set()
    stats = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            url_nodes = f.result()
            new_count = 0
            for d in url_nodes:
                auth = d.get('uuid') or d.get('password') or ""
                fp = f"{d['type']}|{d['server']}|{d['port']}|{auth}"
                if fp not in global_fp:
                    global_fp.add(fp)
                    global_node_dicts.append(d)
                    new_count += 1
            stats.append([futures[f], new_count, "Success" if url_nodes else "Empty"])

    global_node_dicts.sort(key=lambda x: x['type'])
    final_urls = [rebuild_node(d, f"{d['type'].upper()}_{i+1:03d}") for i, d in enumerate(global_node_dicts)]
    final_urls = [l for l in final_urls if l]

    # 保存
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    with open(os.path.join(month_dir, f"nodes_{ts}.txt"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_urls))
    with open(ROOT_LATEST_TXT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_urls))
    with open(ROOT_LATEST_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Source', 'Count', 'Status'])
        writer.writerows(stats)
    
    log(f"Finished. Total Unique Clean Nodes: {len(final_urls)}")

if __name__ == "__main__":
    main()
