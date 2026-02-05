import requests
import re
import os
import time
import base64
import json
import urllib.parse
import yaml  # 确保已执行 pip install pyyaml
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 1. 配置与规则 ---
# 修改：直接保存到根目录
OUTPUT_DIR = "." 
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
EXCLUDE_KEYWORDS = ["127.0.0.1", "localhost", "0.0.0.0", "google.com", "github.com"]

# 协议参数强制校验：包含所有常用协议的核心必填项
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
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt"
]

# --- 2. 核心处理工具 ---

def is_valid_port(port):
    try:
        p = int(port)
        return 1 <= p <= 65535
    except: return False

def parse_yaml_to_links(content):
    """增加功能：解析 YAML 订阅格式"""
    links = []
    try:
        data = yaml.safe_load(content)
        if not data or 'proxies' not in data:
            return []
        
        for p in data['proxies']:
            try:
                t = p.get('type', '').lower()
                # 转换 YAML 节点为标准 URI 格式以便后续统一去重校验
                if t == 'ss':
                    info = base64.b64encode(f"{p.get('cipher')}:{p.get('password')}".encode()).decode()
                    links.append(f"ss://{info}@{p.get('server')}:{p.get('port')}")
                elif t == 'vmess':
                    v_json = json.dumps({"add": p.get('server'), "port": p.get('port'), "id": p.get('uuid'), "type": p.get('cipher', 'auto')})
                    links.append(f"vmess://{base64.b64encode(v_json.encode()).decode()}")
                elif t in ['vless', 'trojan', 'hysteria2', 'hysteria', 'tuic']:
                    pwd = p.get('uuid') or p.get('password') or p.get('auth')
                    links.append(f"{t}://{pwd}@{p.get('server')}:{p.get('port')}")
            except: continue
    except: pass
    return links

def parse_to_standard_dict(raw_url):
    """统一解析：协议参数强制校验的核心逻辑"""
    try:
        parsed = urllib.parse.urlparse(raw_url)
        proto = parsed.scheme.lower()
        
        if proto == 'vmess':
            content = raw_url.split('://')[1]
            padding = len(content) % 4
            if padding: content += "=" * (4 - padding)
            data = json.loads(base64.b64decode(content).decode('utf-8'))
            return {
                'type': 'vmess', 'server': data.get('add'), 'port': data.get('port'),
                'uuid': data.get('id'), 'cipher': data.get('type', 'auto'), 'raw': raw_url
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
                    except: pass
            else:
                res['uuid'] = user_info
                res['password'] = user_info
                res['auth'] = user_info
                res['cipher'] = 'default' # 部分协议非核心
            return res
    except: return None

def auto_decode_base64(text):
    text = text.strip()
    # 如果包含 YAML 特征或已经是协议格式，跳过整体 Base64 解码
    if any(s in text for s in ["proxies:", "://"]): return text
    try:
        clean_text = re.sub(r'[^a-zA-Z0-9+/=]', '', text)
        missing_padding = len(clean_text) % 4
        if missing_padding: clean_text += '=' * (4 - missing_padding)
        return base64.b64decode(clean_text).decode('utf-8', errors='ignore')
    except: return text

# --- 3. 任务执行 ---

def fetch_from_sources(url):
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            content = auto_decode_base64(res.text)
            # 模式 1：正则提取 URI
            nodes = re.findall(NODE_PATTERN, content, re.IGNORECASE)
            # 模式 2：尝试 YAML 解析
            if "proxies:" in content:
                nodes.extend(parse_yaml_to_links(content))
            return nodes
    except: pass
    return []

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 启动全量收割 (根目录保存 + 二次去重 + YAML解析)...")
    
    raw_nodes = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_from_sources, RAW_NODE_SOURCES))
        for nodes in results:
            if nodes: raw_nodes.update(nodes)

    # 二次去重与协议强制校验
    seen_keys = set()
    valid_nodes_raw = []
    
    for raw_url in raw_nodes:
        if any(kw in raw_url.lower() for kw in EXCLUDE_KEYWORDS): continue
            
        d = parse_to_standard_dict(raw_url)
        if not d or not is_valid_port(d.get('port')): continue
            
        # 强制校验：检查该协议所有必填参数是否存在
        proto = d['type']
        if not all(d.get(p) for p in REQUIRED_PARAMS.get(proto, [])): continue

        # 生成指纹：协议+地址+端口+核心认证(UUID/Pass)
        core_auth = d.get('uuid') or d.get('password') or d.get('auth') or d.get('cipher', '')
        unique_key = (d['type'], d['server'], d['port'], core_auth)
        
        if unique_key not in seen_keys:
            seen_keys.add(unique_key)
            valid_nodes_raw.append(raw_url)

    # 保存到根目录下的 nodes.txt
    file_path = os.path.join(OUTPUT_DIR, "nodes.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(valid_nodes_raw)))

    print(f"---")
    print(f"✅ 处理完成！")
    print(f"📦 最终有效节点总数: {len(valid_nodes_raw)}")
    print(f"📂 文件位置: {os.path.abspath(file_path)}")

if __name__ == "__main__":
    main()
