import os
import json
import shutil
import sys
import time
import zipfile
from datetime import datetime  # <--- MỚI: Dùng để lấy thời gian

# --- [FIX QUAN TRỌNG] ÉP BUỘC DÙNG UTF-8 ---
os.environ['PYTHONUTF8'] = '1'

try:
    from kaggle.api.kaggle_api_extended import KaggleApi
except ImportError:
    print("❌ Lỗi: Chưa cài thư viện kaggle. Vui lòng chạy: pip install kaggle")
    sys.exit(1)

# ==============================================================================
# CẤU HÌNH
# ==============================================================================
KAGGLE_USERNAME = 'subinkhang'
DATASET_SLUG = 'subinkhang/olist-merged-dataset-2016-2017'
KERNEL_SLUG = 'subinkhang/churn-predictor-4'
NOTEBOOK_FILE_NAME = "churn-predictor-4.ipynb"
TEMP_DIR = r'D:\ChurnPredictor\temp_kaggle_process'
SAMPLE_CSV_NAME = "olist_merged_2018_month_01.csv"

# ==============================================================================
# LOGIC
# ==============================================================================

def get_paths():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(current_dir, 'config')
    data_dir = os.path.join(current_dir, 'data', 'sample')
    return {
        'config': config_dir,
        'kaggle_json': os.path.join(config_dir, 'kaggle.json'),
        'sample_data': os.path.join(data_dir, SAMPLE_CSV_NAME)
    }

def init_kaggle_api(paths):
    if not os.path.exists(paths['kaggle_json']):
        print("❌ Lỗi: Không tìm thấy file kaggle.json!")
        sys.exit(1)
    os.environ['KAGGLE_CONFIG_DIR'] = paths['config']
    try:
        api = KaggleApi()
        api.authenticate()
        return api
    except Exception as e:
        print(f"❌ Lỗi xác thực: {e}")
        sys.exit(1)

def prepare_temp_dir():
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
        except: pass
    dataset_dir = os.path.join(TEMP_DIR, 'dataset')
    kernel_dir = os.path.join(TEMP_DIR, 'kernel')
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(kernel_dir, exist_ok=True)
    return dataset_dir, kernel_dir

def upload_dataset_with_trigger_info(api, dataset_dir, sample_file_path):
    print("[3] Bắt đầu Upload Dataset...")
    
    # 1. Tải dữ liệu cũ về để gộp
    print(f"   -> Đang tải dữ liệu hiện tại từ {DATASET_SLUG}...")
    try:
        api.dataset_download_files(DATASET_SLUG, path=dataset_dir, unzip=True)
    except: pass

    # Xóa file zip thừa
    for item in os.listdir(dataset_dir):
        if item.endswith(".zip"): os.remove(os.path.join(dataset_dir, item))

    # 2. Copy file CSV mới vào
    if not os.path.exists(sample_file_path):
        print(f"❌ LỖI: Không tìm thấy file CSV mới: {sample_file_path}")
        sys.exit(1)
    
    target_csv = os.path.join(dataset_dir, SAMPLE_CSV_NAME)
    shutil.copy(sample_file_path, target_csv)
    print(f"   -> Đã thêm file: {SAMPLE_CSV_NAME}")

    # =================================================================
    # [MỚI] TỰ ĐỘNG TẠO FILE TRIGGER INFO
    # =================================================================
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trigger_data = {
        "run_id": run_id,
        "triggered_by": "Local Script (Odoo)",
        "new_file_name": SAMPLE_CSV_NAME,
        "action": "append_and_retrain"
    }
    
    # Lưu file json này vào cùng thư mục dataset sắp upload
    trigger_file_path = os.path.join(dataset_dir, 'trigger_info.json')
    
    with open(trigger_file_path, 'w', encoding='utf-8') as f:
        json.dump(trigger_data, f, indent=4)
        
    print(f"   -> 🆔 Đã tạo file cấu hình chạy: Run ID [{run_id}]")
    # =================================================================

    # 3. Tạo metadata cho Dataset
    meta_data = {
        "title": "Olist Merged Dataset 2016-2017",
        "id": DATASET_SLUG,
        "licenses": [{"name": "CC0-1.0"}]
    }
    with open(os.path.join(dataset_dir, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    # 4. Upload lên Kaggle
    try:
        print("   -> Đang đồng bộ lên Kaggle...")
        api.dataset_create_version(
            folder=dataset_dir, 
            version_notes=f'Trigger Run ID: {run_id}', 
            dir_mode='zip', 
            quiet=False
        )
        print("✅ Upload Dataset thành công!")
    except Exception as e:
        print(f"❌ LỖI UPLOAD: {e}")
        sys.exit(1)

def fix_notebook_encoding_for_windows(notebook_path):
    try:
        with open(notebook_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=4, ensure_ascii=True)
    except: pass

def check_kernel_status(api):
    print("   -> 📡 Đang kiểm tra trạng thái Kernel...")
    try:
        # Lấy trạng thái
        status = api.kernels_status(KERNEL_SLUG)
        # status là object, ép kiểu về string hoặc truy cập thuộc tính
        # Lưu ý: Thư viện kaggle trả về object KernelStatus
        s_val = str(status).split(" ")[0] # Lấy từ đầu tiên (ví dụ: "running"...)
        
        print(f"   -> 🔥 Trạng thái trên Kaggle: {status}")
    except: 
        print("   -> (Không lấy được trạng thái chi tiết, nhưng lệnh đã gửi đi)")

def trigger_kernel(api, kernel_dir):
    print("[4] Bắt đầu Trigger Notebook...")
    
    try:
        api.kernels_pull(KERNEL_SLUG, path=kernel_dir, metadata=False)
    except: pass 
    
    downloaded_notebook = os.path.join(kernel_dir, NOTEBOOK_FILE_NAME)
    slug_name = KERNEL_SLUG.split('/')[-1] + ".ipynb"
    possible_file = os.path.join(kernel_dir, slug_name)

    if not os.path.exists(downloaded_notebook):
        if os.path.exists(possible_file):
            os.rename(possible_file, downloaded_notebook)
        else:
            files = [f for f in os.listdir(kernel_dir) if f.endswith('.ipynb')]
            if files: os.rename(os.path.join(kernel_dir, files[0]), downloaded_notebook)

    fix_notebook_encoding_for_windows(downloaded_notebook)

    meta_data = {
        "id": KERNEL_SLUG,
        "title": "Churn Predictor 4",
        "code_file": NOTEBOOK_FILE_NAME,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": "false",
        "enable_gpu": "true",
        "enable_internet": "true",
        "dataset_sources": [DATASET_SLUG],
        "kernel_sources": []
    }
    
    with open(os.path.join(kernel_dir, 'kernel-metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    print("   -> Đang kích hoạt chạy lại (Push)...")
    try:
        api.kernels_push(folder=kernel_dir)
        print("✅ Lệnh Push thành công.")
        
        time.sleep(3)
        check_kernel_status(api)
        
    except Exception as e:
        print(f"❌ LỖI TRIGGER: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("--- START PYTHON API TEST (AUTO JSON CREATION) ---")
    paths = get_paths()
    api = init_kaggle_api(paths)
    d_dir, k_dir = prepare_temp_dir()
    
    # Gọi hàm mới đã tích hợp tạo file json
    upload_dataset_with_trigger_info(api, d_dir, paths['sample_data'])
    
    print("⏳ Đợi 10 giây để Kaggle xử lý dataset...")
    time.sleep(10)
    
    trigger_kernel(api, k_dir)
    print("\n--- HOÀN TẤT ---")