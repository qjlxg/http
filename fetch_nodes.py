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

# --- 官方协议必备参数与可选白名单 ---
# 只有在白名单里的参数才会被保留，其它的全部删除
PROTOCOL_CONFIG = {
    'ss': {
        'required': ['cipher', 'password'],
        'whitelist': ['plugin']
    },
    'vmess': {
        'required': ['add', 'port', 'id'],
        'whitelist': ['net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp', 'aid']
    },
    'vless': {
        'required': ['uuid', 'server', 'port'],
        'whitelist': ['type', 'security', 'sni', 'fp', 'path', 'host', 'pbk', 'sid', 'serviceName', 'headerType', 'flow']
    },
    'trojan': {
        'required': ['password', 'server', 'port'],
        'whitelist': ['type', 'security', 'sni', 'fp', 'path', 'host', 'alpn']
    },
    'hy2': {
        'required': ['password', 'server', 'port'],
        'whitelist': ['sni', 'obfs', 'obfs-password']
    },
    'hysteria2': {
        'required': ['password', 'server', 'port'],
        'whitelist': ['sni', 'obfs', 'obfs-password']
    },
    'hysteria': {
        'required': ['auth', 'server', 'port'],
        'whitelist': ['protocol', 'sni', 'peer', 'insecure', 'obfs']
    },
    'tuic': {
        'required': ['uuid', 'password', 'server', 'port'],
        'whitelist': ['sni', 'alpn', 'congestion_control', 'udp_relay_mode']
    }
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def parse_node(raw_url):
    """根据每种协议的官方标准提取参数"""
    try:
        raw_url = re.split(r'[<"\s\'\`,]', raw_url)[0]
        if '://' not in raw_url: return None
        
        parsed = urlparse(raw_url)
        proto = parsed.scheme.lower()
        if proto not in PROTOCOL_CONFIG: return None
        
        conf = PROTOCOL_CONFIG[proto]
        res = {'type': proto, 'query': {}}

        # 1. 处理 VMess (JSON 格式)
        if proto == 'vmess':
            content = raw_url.split('://')[1]
            padding = len(content) % 4
            if padding: content += "=" * (4 - padding)
            data = json.loads(base64.b64decode(content).decode('utf-8'))
            
            # 校验必备项
            if not all(data.get(k) for k in ['add', 'port', 'id']): return None
            
            # 仅提取白名单参数
            res['server'] = data.get('add')
            res['port'] = str(data.get('port'))
            res['uuid'] = data.get('id')
            res['meta'] = {k: data[k] for k in conf['whitelist'] if k in data and data[k]}
            return res

        # 2. 处理通用 URL 格式 (SS, VLESS, Trojan, Hy2, etc.)
        netloc = parsed.netloc.split('#')[0]
        user_info = unquote(netloc.split('@')[0]) if '@' in netloc else ""
        server_port = netloc.split('@')[-1]
        
        # 提取 Server 和 Port
        if ']' in server_port: # IPv6
            res['server'] = server_port.split(']')[0] + ']'
            p_part = server_port.split(']')[-1]
            res['port'] = p_part.split(':')[1] if ':' in p_part else "443"
        else: # IPv4/Domain
            res['server'] = server_port.split(':')[0]
            res['port'] = server_port.split(':')[1] if ':' in server_port else "443"

        # 提取核心认证信息
        if proto == 'ss':
            if ':' in user_info:
                res['cipher'], res['password'] = user_info.split(':', 1)
            else: # 处理 Base64 的用户信息
                try:
                    dec = base64.b64decode(user_info).decode('utf-8')
                    if ':' in dec: res['cipher'], res['password'] = dec.split(':', 1)
                except: return None
        else:
            res['uuid'] = user_info # VLESS/Trojan/Hy2 的密码或 UUID 都在这里

        # 校验必备项
        req_keys = ['server', 'port'] + [k for k in conf['required'] if k not in ['server', 'port']]
        if not all(res.get(k) for k in req_keys): return None

        # 提取 Query 白名单
        query = parse_qs(parsed.query)
        res['query'] = {k: query[k] for k in conf['whitelist'] if k in query}
        
        return res
    except:
        return None

def rebuild_node(d, name):
    """重构成最纯净的官方格式链接"""
    try:
        proto = d['type']
        if proto == 'vmess':
            m = d['meta']
            m.update({'add': d['server'], 'port': d['port'], 'id': d['uuid'], 'ps': name})
            return f"vmess://{base64.b64encode(json.dumps(m).encode()).decode()}"
        else:
            q_str = urlencode(d.get('query', {}), doseq=True)
            auth = f"{d['cipher']}:{d['password']}" if proto == 'ss' else d['uuid']
            url = f"{proto}://{quote(auth)}@{d['server']}:{d['port']}"
            if q_str: url += f"?{unquote(q_str)}" # unquote 为了让路径 / 更美观
            url += f"#{quote(name)}"
            return url
    except:
        return None

def process_url(url):
    log(f"Fetching: {url}")
    try:
        res = requests.get(url, timeout=(10, 20), verify=False, headers=HEADERS)
        if res.status_code != 200: return []
        text = res.text
    except: return []

    raw_urls = re.findall(r'(?:ss|ssr|vmess|vless|trojan|hysteria|hy2|tuic)://[^\s<"\'\`]+', text, re.IGNORECASE)
    results = []
    local_fp = set()

    for raw in raw_urls:
        d = parse_node(raw)
        if not d: continue
        
        # 极致去重指纹：协议+地址+端口+核心认证
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
            stats.append([futures[f], new_count, "Success" if url_nodes else "Empty/Fail"])

    # 排序并生成最终链接
    global_node_dicts.sort(key=lambda x: x['type'])
    final_urls = []
    for i, d in enumerate(global_node_dicts):
        name = f"{d['type'].upper()}_{i+1:03d}"
        link = rebuild_node(d, name)
        if link: final_urls.append(link)

    # 保存
    now = datetime.now()
    month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(month_dir, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M%S')
    
    def write_res(t_p, c_p):
        with open(t_p, 'w', encoding='utf-8') as f: f.write('\n'.join(final_urls))
        with open(c_p, 'w', encoding='utf-8-sig', newline='') as f:
            csv.writer(f).writerow(['Source', 'Count', 'Status'])
            csv.writer(f).writerows(stats)

    write_res(os.path.join(month_dir, f"nodes_{ts}.txt"), os.path.join(month_dir, f"stats_{ts}.csv"))
    write_res(ROOT_LATEST_TXT, ROOT_LATEST_CSV)
    
    log(f"Completed. Found {len(final_urls)} clean unique nodes.")

if __name__ == "__main__":
    main()
