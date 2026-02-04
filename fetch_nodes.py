import requests
import base64
import json
import os
import csv
import urllib3
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote, quote, urlencode

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 配置 ---
INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
ROOT_LATEST_TXT = 'latest_nodes.txt'
ROOT_LATEST_CSV = 'latest_nodes_stats.csv'
MAX_WORKERS = 80
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

# 协议验证核心参数
REQUIRED_PARAMS = {
    'ss': ['server', 'port', 'cipher', 'password'],
    'vmess': ['server', 'port', 'uuid'],
    'vless': ['server', 'port', 'uuid'],
    'trojan': ['server', 'port', 'password'],
    'hysteria2': ['server', 'port', 'password'],
    'hy2': ['server', 'port', 'password'],
    'hysteria': ['server', 'port', 'auth'],
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- 工具函数 ---

def parse_to_standard_dict(raw_url):
    """将各种协议链接统一解析为标准字典进行深度校验"""
    try:
        raw_url = re.split(r'[<"\s\'\`,]', raw_url)[0]
        if '://' not in raw_url: return None
        
        parsed = urlparse(raw_url)
        proto = parsed.scheme.lower()

        if proto == 'vmess':
            content = raw_url.split('://')[1]
            padding = len(content) % 4
            if padding: content += "=" * (4 - padding)
            data = json.loads(base64.b64decode(content).decode('utf-8'))
            return {
                'type': 'vmess', 'server': data.get('add'), 'port': data.get('port'),
                'uuid': data.get('id'), 'cipher': data.get('type', 'auto'),
                'raw': raw_url, 'meta': data
            }
        
        elif proto in REQUIRED_PARAMS or proto == 'hy2':
            # 处理 IPv6 格式: [2001:...]:port
            netloc = parsed.netloc.split('#')[0]
            user_info = unquote(netloc.split('@')[0]) if '@' in netloc else ""
            server_port = netloc.split('@')[-1] if '@' in netloc else netloc
            
            if ']' in server_port: # IPv6
                server = server_port.split(']')[0] + ']'
                port_part = server_port.split(']')[-1]
                port = port_part.split(':')[1] if ':' in port_part else 443
            else: # IPv4 or Domain
                server = server_port.split(':')[0]
                port = server_port.split(':')[1] if ':' in server_port else 443

            res = {'type': proto, 'server': server, 'port': str(port), 'raw': raw_url}
            
            if proto == 'ss':
                if ':' in user_info:
                    res['cipher'], res['password'] = user_info.split(':', 1)
                else: # 处理可能存在的 Base64 用户信息
                    try:
                        decoded_user = base64.b64decode(user_info).decode('utf-8')
                        if ':' in decoded_user:
                            res['cipher'], res['password'] = decoded_user.split(':', 1)
                    except: pass
            else:
                res['uuid'] = user_info
                res['password'] = user_info
                res['auth'] = user_info
            
            # 提取必要 Query 参数 (TLS/SNI 等) 用于重建链接
            query = parse_qs(parsed.query)
            keep = ['type', 'security', 'sni', 'fp', 'path', 'pbk', 'sid']
            res['query'] = {k: v for k, v in query.items() if k.lower() in keep}
            
            return res
    except:
        return None

def rebuild_url(d):
    """根据标准字典重新生成去备注的规范化 URL"""
    try:
        if d['type'] == 'vmess':
            meta = d['meta']
            # 清理 VMess 备注
            meta['ps'] = "CleanNode" 
            core_meta = {k: v for k, v in meta.items() if k in ['add', 'port', 'id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp', 'ps']}
            return f"vmess://{base64.b64encode(json.dumps(core_meta).encode()).decode()}"
        else:
            # 重新拼装 SS/VLESS/Trojan 等，彻底去掉原始备注
            new_query = urlencode(d.get('query', {}), doseq=True)
            # 简化版拼装，不带备注
            url = f"{d['type']}://{unquote(d.get('cipher','') + ':' + d.get('password','') if d['type'] == 'ss' else d.get('uuid',''))}@{d['server']}:{d['port']}"
            if new_query: url += f"?{new_query}"
            return url
    except:
        return d['raw']

def get_content(url):
    clean_url = url.strip().replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        try:
            res = requests.get(f"{protocol}{clean_url}", timeout=(8, 15), verify=False, headers=HEADERS)
            if res.status_code == 200: return res.text, protocol
        except: continue
    return None, None

def process_url(url):
    log(f"Fetch: {url}")
    text, protocol = get_content(url)
    if not text: return {'url': url, 'nodes': set(), 'protocol': 'None', 'status': 'Fail'}
    
    # 提取并初步清洗
    raw_list = re.findall(r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2)://[^\s<"\'\`]+', text, re.IGNORECASE)
    
    valid_results = []
    seen_in_this_url = set()

    for raw in raw_list:
        d = parse_to_standard_dict(raw)
        if not d: continue
        
        # 指纹生成：协议 + 地址 + 端口 + 核心认证(UUID/密码)
        auth = d.get('uuid') or d.get('password') or d.get('cipher', '')
        fingerprint = f"{d['type']}|{d['server']}|{d['port']}|{auth}"
        
        if fingerprint not in seen_in_this_url:
            # 验证必要参数是否存在
            reqs = REQUIRED_PARAMS.get(d['type'], ['server', 'port'])
            if all(d.get(r) for r in reqs):
                seen_in_this_url.add(fingerprint)
                valid_results.append(rebuild_url(d))

    return {'url': url, 'nodes': valid_results, 'protocol': protocol, 'status': 'Success'}

def main():
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    global_seen_fingerprints = set()
    final_nodes = []
    stats = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for f in as_completed(futures):
            r = f.result()
            unique_nodes_from_url = []
            for node in r['nodes']:
                # 二次全局去重
                if node not in global_seen_fingerprints:
                    global_seen_fingerprints.add(node)
                    unique_nodes_from_url.append(node)
            
            final_nodes.extend(unique_nodes_from_url)
            stats.append([r['url'], r['protocol'], len(unique_nodes_from_url), r['status']])
            log(f"Done: {r['url']} | Unique: {len(unique_nodes_from_url)}")

    # 存储
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    def save(t_p, c_p):
        with open(t_p, 'w', encoding='utf-8') as f: f.write('\n'.join(sorted(final_nodes)))
        with open(c_p, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Source', 'Proto', 'Count', 'Status'])
            writer.writerows(stats)

    save(os.path.join(month_dir, f"nodes_{ts}.txt"), os.path.join(month_dir, f"stats_{ts}.csv"))
    save(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    log(f"Finished. Total Unique Nodes: {len(final_nodes)}")

if __name__ == "__main__":
    main()
