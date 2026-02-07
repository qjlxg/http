import requests
import os
import json
import time

# 配置
INPUT_FILE = 'duplicate.txt'
OUTPUT_FILE = 'scan_alist.txt'

def get_alist_list(base_url, path="/"):
    """调用 AList V3 API 获取文件列表"""
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    payload = {"path": path, "password": "", "page": 1, "per_page": 0}
    try:
        # AList 通常不需要特殊 header 即可访问公开目录
        resp = requests.post(api_url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except Exception as e:
        print(f"Error accessing {base_url} at {path}: {e}")
    return []

def scan_recursive(base_url, current_path, files_by_ext):
    """递归扫描目录"""
    items = get_alist_list(base_url, current_path)
    if not items:
        return

    for item in items:
        # 拼接完整路径
        full_path = os.path.join(current_path, item['name']).replace("\\", "/")
        download_url = f"{base_url.rstrip('/')}/d{full_path}" # AList 默认下载前缀

        if item.get('is_dir'):
            print(f"Scanning dir: {full_path}")
            scan_recursive(base_url, full_path, files_by_ext)
        else:
            # 按扩展名分类
            _, ext = os.path.splitext(item['name'])
            ext = ext.lower() if ext else ".no_ext"
            if ext not in files_by_ext:
                files_by_ext[ext] = []
            files_by_ext[ext].append(f"{item['name']} | {download_url}")

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        return

    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip().startswith('http')]

    all_results = {}

    for url in urls:
        print(f"Starting scan for: {url}")
        scan_recursive(url, "/", all_results)

    # 写入结果
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for ext in sorted(all_results.keys()):
            f.write(f"\n--- Extension: {ext} ---\n")
            for line in all_results[ext]:
                f.write(line + "\n")

if __name__ == "__main__":
    main()
