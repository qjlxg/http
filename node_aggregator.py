import requests
import re
import os
import time
import base64
import json
import urllib.parse
import yaml
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 1. 配置与规则 ---
OUTPUT_DIR = "." 
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com", "github.com"]

# 协议参数强制校验：确保基础连接信息存在
REQUIRED_PARAMS = {
    'ss': ['server', 'port', 'cipher', 'password'],
    'vmess': ['server', 'port', 'uuid'],
    'vless': ['server', 'port', 'uuid'],
    'trojan': ['server', 'port', 'password'],
    'hysteria2': ['server', 'port', 'password'],
    'hysteria': ['server', 'port', 'auth'],
    'tuic': ['server', 'port', 'uuid', 'password'],
    'ssr': ['server', 'port', 'cipher', 'password']
}

NODE_PATTERN = r'(?:vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[a-zA-Z0-9%@\[\]\._\-\?&=\+#/:]+'

RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/v2ray-free/free/main/v2ray"
]

# --- 2. 核心处理工具 ---

def is_valid_port(port):
    try:
        p = int(port)
        return 1 <= p <= 65535
    except: return False

def parse_yaml_to_links(content):
    """解析 YAML 格式并兼容不同字段名"""
    links = []
    try:
        data = yaml.safe_load(content)
        if not data or 'proxies' not in data: return []
        for p in data['proxies']:
            try:
                t = p.get('type', '').lower()
                server = p.get('server')
                port = p.get('port')
                if not server or not port: continue

                if t == 'ss':
                    info = base64.b64encode(f"{p.get('cipher')}:{p.get('password')}".encode()).decode()
                    links.append(f"ss://{info}@{server}:{port}")
                elif t == 'vmess':
                    v_json = json.dumps({"add": server, "port": port, "id": p.get('uuid') or p.get('id'), "type": p.get('cipher', 'auto')})
                    links.append(f"vmess://{base64.b64encode(v_json.encode()).decode()}")
                elif t in ['vless', 'trojan', 'hysteria2', 'hysteria', 'tuic']:
                    pwd = p.get('uuid') or p.get('password') or p.get('auth') or p.get('id')
                    links.append(f"{t}://{pwd}@{server}:{port}")
            except: continue
    except: pass
    return links

def parse_to_standard_dict(raw_url):
    """标准解析逻辑，增加字段容错"""
    try:
        parsed = urllib.parse.urlparse(raw_url)
        proto = parsed.scheme.lower()
        
        if proto == 'vmess':
            content = raw_url.split('://')[1]
            padding = len(content) % 4
            if padding: content += "=" * (4 - padding)
            data = json.loads(base64.b64decode(content).decode('utf-8'))
            # 兼容 id 和 add 字段名
            return {
                'type': 'vmess', 
                'server': data.get('add') or data.get('host'), 
                'port': data.get('port'),
                'uuid': data.get('id') or data.get('uuid'), 
                'cipher': data.get('type', 'auto'), 
                'raw': raw_url
            }
        
        elif proto in REQUIRED_PARAMS:
            netloc = parsed.netloc
            user_info = urllib.parse.unquote(netloc.split('@')[0]) if '@' in netloc else ""
            server_port = netloc.split('@')[-1] if '@' in netloc else netloc
            server = server_port.split(':')[0]
            port = server_port.split(':')[1] if ':' in server_port else (443 if proto != 'ss' else 80)
            
            res = {'type': proto, 'server': server, 'port': port, 'raw': raw_url}
            
            if proto == 'ss':
                if ':' in user_info:
                    res['cipher'], res['password'] = user_info.split(':', 1)
                else:
                    try:
                        decoded = base64.b64decode(user_info).decode('utf-8')
                        if ':' in decoded: res['cipher'], res['password'] = decoded.split(':', 1)
                    except: res['cipher'], res['password'] = 'aes-256-gcm', user_info # 兜底策略
            else:
                res['uuid'] = user_info
                res['password'] = user_info
                res['auth'] = user_info
                res['cipher'] = 'auto'
            return res
    except: return None

def auto_decode_base64(text):
    text = text.strip()
    if any(s in text for s in ["proxies:", "://", "proxies\n"]): return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except: return text

def fetch_from_sources(url):
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            # 提取 URI
            nodes = re.findall(NODE_PATTERN, content, re.IGNORECASE)
            # 提取 YAML
            if "proxies" in content:
                nodes.extend(parse_yaml_to_links(content))
            return nodes
    except: pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动节点收割 (兼容性增强版)...")
    
    raw_nodes = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: raw_nodes.update(nodes)

    seen_keys = set()
    valid_nodes_raw = []
    
    for raw_url in raw_nodes:
        if any(kw in raw_url.lower() for kw in EXCLUDE_KEYWORDS): continue
            
        d = parse_to_standard_dict(raw_url)
        if not d or not is_valid_port(d.get('port')): continue
            
        proto = d['type']
        # 强制校验：检查必填项
        if not all(d.get(p) for p in REQUIRED_PARAMS.get(proto, [])): continue

        # 指纹去重
        core_auth = d.get('uuid') or d.get('password') or d.get('auth') or d.get('cipher', '')
        unique_key = (d['type'], d['server'], d['port'], core_auth)
        
        if unique_key not in seen_keys:
            seen_keys.add(unique_key)
            valid_nodes_raw.append(raw_url)

    file_path = os.path.join(OUTPUT_DIR, "nodes.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(valid_nodes_raw)))

    print(f"---")
    print(f"✅ 处理完成！原始抓取: {len(raw_nodes)} | 校验通过: {len(valid_nodes_raw)}")

if __name__ == "__main__":
    main()
