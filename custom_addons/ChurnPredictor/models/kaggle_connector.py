import os
import json
import shutil
import sys
import time
import subprocess
from datetime import datetime

# Cấu hình tĩnh (Hoặc có thể truyền vào)
KAGGLE_USERNAME = 'subinkhang'
DATASET_SLUG = 'subinkhang/olist-merged-dataset-2016-2017'
KERNEL_SLUG = 'subinkhang/churn-predictor-4'
NOTEBOOK_FILE_NAME = "churn-predictor-4.ipynb"
# Dùng đường dẫn tương đối hoặc lấy từ config Odoo
# Ở đây ta sẽ nhận đường dẫn temp từ hàm gọi

def init_kaggle_api(config_dir):
    """Khởi tạo API với đường dẫn config cụ thể"""
    os.environ['KAGGLE_CONFIG_DIR'] = config_dir
    os.environ['PYTHONUTF8'] = '1'
    
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        return api
    except ImportError:
        raise Exception("Thư viện 'kaggle' chưa được cài đặt.")
    except Exception as e:
        raise Exception(f"Lỗi xác thực Kaggle: {str(e)}")

def run_pipeline(csv_file_path, config_dir, temp_dir):
    """
    Hàm chính để chạy toàn bộ quy trình:
    1. Upload CSV
    2. Trigger Kernel
    """
    
    # 1. Setup
    api = init_kaggle_api(config_dir)
    
    # Chuẩn bị folder upload tạm
    upload_dir = os.path.join(temp_dir, 'dataset_upload')
    kernel_dir = os.path.join(temp_dir, 'kernel_trigger')
    
    if os.path.exists(upload_dir): shutil.rmtree(upload_dir)
    if os.path.exists(kernel_dir): shutil.rmtree(kernel_dir)
    os.makedirs(upload_dir)
    os.makedirs(kernel_dir)

    # 2. Upload Logic (Append Mode)
    print(f"--- Bắt đầu xử lý file: {csv_file_path}")
    
    # Tải metadata cũ (nếu cần) hoặc tạo mới
    # Ở đây ta làm tắt: Tải hết về rồi chèn file mới vào
    try:
        api.dataset_download_files(DATASET_SLUG, path=upload_dir, unzip=True)
        # Xóa zip thừa
        for f in os.listdir(upload_dir):
            if f.endswith('.zip'): os.remove(os.path.join(upload_dir, f))
    except:
        pass # Chấp nhận nếu dataset trống

    # Copy file CSV mới vào
    file_name = os.path.basename(csv_file_path)
    target_csv = os.path.join(upload_dir, file_name)
    shutil.copy(csv_file_path, target_csv)

    # Tạo trigger_info.json
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trigger_info = {
        "run_id": run_id,
        "triggered_by": "Odoo Admin Dashboard",
        "new_file": file_name
    }
    with open(os.path.join(upload_dir, 'trigger_info.json'), 'w', encoding='utf-8') as f:
        json.dump(trigger_info, f, indent=4)

    # Tạo dataset-metadata.json
    meta_data = {
        "title": "Olist Merged Dataset 2016-2017",
        "id": DATASET_SLUG,
        "licenses": [{"name": "CC0-1.0"}]
    }
    with open(os.path.join(upload_dir, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    # Upload
    api.dataset_create_version(
        folder=upload_dir,
        version_notes=f'Odoo Upload: {run_id}',
        dir_mode='zip',
        quiet=True
    )
    print(">>> Upload thành công.")

    # 3. Trigger Kernel Logic
    # (Đợi 5s để server Kaggle đồng bộ)
    time.sleep(5)
    
    # Pull code về
    try:
        api.kernels_pull(KERNEL_SLUG, path=kernel_dir, metadata=True)
    except: pass # Nếu chưa có thì thôi

    # Đảm bảo có file notebook (để không lỗi)
    nb_path = os.path.join(kernel_dir, NOTEBOOK_FILE_NAME)
    if not os.path.exists(nb_path):
        # Tìm file .ipynb bất kỳ đổi tên
        found = [f for f in os.listdir(kernel_dir) if f.endswith('.ipynb')]
        if found:
            os.rename(os.path.join(kernel_dir, found[0]), nb_path)
    
    # Fix encoding (như cũ)
    try:
        with open(nb_path, 'r', encoding='utf-8') as f: content = json.load(f)
        with open(nb_path, 'w', encoding='utf-8') as f: json.dump(content, f, indent=4, ensure_ascii=True)
    except: pass

    # Push kernel
    api.kernels_push(folder=kernel_dir)
    print(">>> Trigger Notebook thành công.")
    
    return run_id