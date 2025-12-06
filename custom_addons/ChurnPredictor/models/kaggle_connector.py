# -*- coding: utf-8 -*-
import os
import json
import shutil
import sys
import time
import logging
import subprocess
from datetime import datetime

_logger = logging.getLogger(__name__)

# Cấu hình
DATASET_SLUG = 'subinkhang/olist-merged-dataset-2016-2017'
KERNEL_SLUG = 'subinkhang/churn-predictor-4'
NOTEBOOK_FILE_NAME = "churn-predictor-4.ipynb"

def get_kaggle_creds(config_dir):
    """Đọc credentials từ file JSON của bạn"""
    source_key_path = os.path.join(config_dir, 'kaggle.json')
    if not os.path.exists(source_key_path):
        source_key_path = os.path.join(os.path.dirname(config_dir), 'config', 'kaggle.json')
    
    if not os.path.exists(source_key_path):
        raise Exception(f"Không tìm thấy file key tại: {config_dir}")

    with open(source_key_path, 'r') as f:
        return json.load(f)

def authenticate_kaggle_programmatically(creds):
    """
    Xác thực chuẩn theo tài liệu: Provide credentials at runtime.
    Bypass việc đọc file config mặc định (nguyên nhân gây lỗi 401 trên Docker).
    """
    # 1. Set biến môi trường (Kaggle Client sẽ ưu tiên đọc cái này trước file)
    os.environ['KAGGLE_USERNAME'] = creds['username']
    os.environ['KAGGLE_KEY'] = creds['key']
    
    # 2. Import và khởi tạo
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate() # Nó sẽ đọc từ os.environ
        return api
    except ImportError:
        raise Exception("Chưa cài thư viện kaggle. Chạy: pip install kaggle")
    except Exception as e:
        raise Exception(f"Lỗi xác thực Kaggle: {e}")

def _prepare_temp_dir(base_temp_dir):
    dataset_dir = os.path.join(base_temp_dir, 'dataset_upload')
    kernel_dir = os.path.join(base_temp_dir, 'kernel_trigger')
    
    if os.path.exists(dataset_dir): shutil.rmtree(dataset_dir)
    if os.path.exists(kernel_dir): shutil.rmtree(kernel_dir)
    
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(kernel_dir, exist_ok=True)
    return dataset_dir, kernel_dir

def _fix_notebook_encoding(notebook_path):
    """Fix lỗi charmap trên Windows khi upload notebook"""
    try:
        with open(notebook_path, 'r', encoding='utf-8') as f: content = json.load(f)
        with open(notebook_path, 'w', encoding='utf-8') as f: json.dump(content, f, indent=4, ensure_ascii=True)
    except: pass

def run_kaggle_pipeline(csv_file_path, config_dir, temp_dir):
    _logger.info(f"--- KAGGLE PIPELINE START (OFFICIAL API MODE) ---")
    
    # 1. Lấy credentials từ file của bạn
    creds = get_kaggle_creds(config_dir)
    
    # 2. Xác thực API
    api = authenticate_kaggle_programmatically(creds)
    _logger.info("✅ Authenticated successfully via Environment Variables")

    dataset_dir, kernel_dir = _prepare_temp_dir(temp_dir)
    file_name = os.path.basename(csv_file_path)

    # ==========================================================================
    # PHẦN 1: DATASET (Tuân thủ tài liệu: Update a Dataset)
    # ==========================================================================
    _logger.info("1. Downloading current dataset files...")
    try:
        # Tải file cũ về để bảo toàn dữ liệu (Append mode)
        api.dataset_download_files(DATASET_SLUG, path=dataset_dir, unzip=True)
        # Dọn dẹp file zip thừa
        for f in os.listdir(dataset_dir):
            if f.endswith('.zip'): os.remove(os.path.join(dataset_dir, f))
    except Exception as e:
        _logger.warning(f"Download warning (Normal if first upload): {e}")

    # Copy file mới vào
    shutil.copy(csv_file_path, os.path.join(dataset_dir, file_name))
    _logger.info(f"   -> Added file: {file_name}")
    
    # Tạo Trigger Info (JSON)
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(dataset_dir, 'trigger_info.json'), 'w', encoding='utf-8') as f:
        json.dump({"run_id": run_id, "file": file_name}, f)

    # Tạo Metadata (dataset-metadata.json) - BẮT BUỘC THEO TÀI LIỆU
    # "Make sure the id field in dataset-metadata.json points to your dataset"
    meta_data = {
        "title": "Olist Merged Dataset 2016-2017",
        "id": DATASET_SLUG,
        "licenses": [{"name": "CC0-1.0"}]
    }
    with open(os.path.join(dataset_dir, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    # Upload Version Mới
    _logger.info("2. Creating new dataset version...")
    try:
        # Hàm chuẩn của thư viện: dataset_create_version
        # Tương đương lệnh CLI: kaggle datasets version -p /path -m "message"
        api.dataset_create_version(
            folder=dataset_dir,
            version_notes=f'Odoo Update: {run_id}',
            dir_mode='zip', # Nén lại upload cho nhanh và ổn định
            quiet=True
        )
        _logger.info(">>> DATASET UPLOAD SUCCESS")
    except Exception as e:
        # Nếu lỗi này xảy ra, 99% là do mạng hoặc server Kaggle quá tải tạm thời
        _logger.error(f"DATASET UPLOAD FAILED: {e}")
        raise e

    # ==========================================================================
    # PHẦN 2: NOTEBOOK (Tuân thủ tài liệu: Push a Notebook)
    # ==========================================================================
    time.sleep(5) # Đợi server xử lý dataset
    _logger.info("3. Handling Notebook...")
    
    try:
        # Tải code notebook hiện tại về
        # Tương đương: kaggle kernels pull [KERNEL] -p /path -m
        api.kernels_pull(KERNEL_SLUG, path=kernel_dir, metadata=False)
    except: pass

    # Đảm bảo file notebook tồn tại và đúng tên
    nb_path = os.path.join(kernel_dir, NOTEBOOK_FILE_NAME)
    if not os.path.exists(nb_path):
         candidates = [f for f in os.listdir(kernel_dir) if f.endswith('.ipynb')]
         if candidates: os.rename(os.path.join(kernel_dir, candidates[0]), nb_path)
    
    # Fix encoding cho Windows
    if os.path.exists(nb_path): _fix_notebook_encoding(nb_path)

    # Tạo Metadata Kernel (kernel-metadata.json) - BẮT BUỘC
    # "Make sure the id field in kernel-metadata.json points to your Notebook"
    k_meta = {
        "id": KERNEL_SLUG, 
        "title": "Churn Predictor 4", 
        "code_file": NOTEBOOK_FILE_NAME,
        "language": "python", 
        "kernel_type": "notebook", 
        "is_private": "false",
        "enable_gpu": "true", 
        "enable_internet": "true",
        "dataset_sources": [DATASET_SLUG], # Link với dataset vừa up
        "kernel_sources": []
    }
    with open(os.path.join(kernel_dir, 'kernel-metadata.json'), 'w', encoding='utf-8') as f: 
        json.dump(k_meta, f, indent=4)

    # Push Kernel (Trigger Run)
    # Tương đương: kaggle kernels push -p /path
    _logger.info("4. Pushing Kernel to Trigger Run...")
    try:
        api.kernels_push(folder=kernel_dir)
        _logger.info(">>> KERNEL TRIGGER SUCCESS")
    except Exception as e:
        _logger.error(f"KERNEL TRIGGER FAILED: {e}")
        raise e
    
    return run_id

def download_model_output(run_id, output_dir):
    """
    Hàm tải file churn_model.joblib từ Kaggle về Odoo.
    1. Đợi kernel chạy xong (status: complete).
    2. Tải file về folder ml_assets/{timestamp}/.
    """
    # Cấu hình
    KERNEL_SLUG = 'subinkhang/churn-predictor-4' # Đảm bảo đúng slug
    MODEL_FILENAME = 'churn_model.joblib'
    
    # 1. Khởi tạo API (Lấy từ ENV đã set trước đó)
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
    except:
        _logger.error("Kaggle Auth failed during download.")
        return False

    _logger.info(f"--- WAITING FOR KERNEL TO FINISH (RunID: {run_id}) ---")
    
    # 2. Vòng lặp kiểm tra trạng thái (Polling)
    # Chờ tối đa 10 phút (60 * 10 giây)
    max_retries = 60
    for i in range(max_retries):
        status = api.kernels_status(KERNEL_SLUG)
        s_val = str(status).split(" ")[0] # Lấy status string
        
        _logger.info(f"   Kernel Status: {s_val} ({i}/{max_retries})")
        
        if s_val == 'complete':
            break # Chạy xong -> Tải về
        elif s_val == 'error':
            raise Exception("Kernel chạy bị lỗi trên Kaggle. Vui lòng kiểm tra log trên web.")
        
        time.sleep(10) # Đợi 10s check lại

    # 3. Tải file về
    _logger.info("--- DOWNLOADING MODEL ---")
    
    # Tạo folder timestamp: ml_assets/YYYYMMDD_HHMMSS/
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_dir = os.path.join(output_dir, timestamp_str)
    
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
        
    try:
        # Tải file output từ kernel
        api.kernels_output(KERNEL_SLUG, path=save_dir)
        
        # Kiểm tra file có về không
        downloaded_file = os.path.join(save_dir, MODEL_FILENAME)
        if os.path.exists(downloaded_file):
            _logger.info(f"✅ Model downloaded to: {downloaded_file}")
            return downloaded_file
        else:
            _logger.error(f"❌ Download xong nhưng không thấy file {MODEL_FILENAME}")
            return False
            
    except Exception as e:
        _logger.error(f"Download Error: {e}")
        return False

def check_and_download_if_ready(run_id, output_base_dir):
    """
    Hàm kiểm tra và tải file.
    FIXED: Xử lý trạng thái 'KernelWorkerStatus.COMPLETE'
    """
    KERNEL_SLUG = 'subinkhang/churn-predictor-4' 
    MODEL_FILENAME = 'churn_model.joblib'
    
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
    except Exception as e:
        return {'status': 'error', 'message': f"Auth Error: {str(e)}"}

    try:
        # 1. Lấy trạng thái
        kernel_status = api.kernels_status(KERNEL_SLUG)
        
        # Chuyển về chuỗi và chữ thường để so sánh cho chuẩn
        # Ví dụ: "KernelWorkerStatus.COMPLETE" -> "kernelworkerstatus.complete"
        raw_status = str(kernel_status)
        status_lower = raw_status.lower()

        _logger.info(f"KAGGLE STATUS RAW: {raw_status}")

        # 2. Kiểm tra Logic (Linh hoạt hơn)
        # Chỉ cần chứa chữ 'complete' là coi như xong
        if 'complete' in status_lower:
            
            # Tạo đường dẫn lưu
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_dir = os.path.join(output_base_dir, timestamp_str)
            
            if not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            _logger.info(f"Status is COMPLETE. Downloading output to: {save_dir}")
            
            # Tải Output
            try:
                api.kernels_output(KERNEL_SLUG, path=save_dir)
            except Exception as download_err:
                return {'status': 'error', 'message': f"Download Failed: {download_err}"}
            
            # Kiểm tra xem file joblib có về không
            joblib_path = os.path.join(save_dir, MODEL_FILENAME)
            
            if os.path.exists(joblib_path):
                # Xóa bớt các file rác không cần thiết (như log, script...)
                for f in os.listdir(save_dir):
                    if f != MODEL_FILENAME and f != "model_columns.pkl": # Giữ lại các file cần thiết
                        try:
                            os.remove(os.path.join(save_dir, f))
                        except: pass
                
                return {
                    'status': 'done', 
                    'message': 'Training Complete. Model Downloaded.', 
                    'file_path': joblib_path
                }
            else:
                # Kernel chạy xong nhưng không sinh ra file joblib
                # Có thể do code trong Notebook bị lỗi ở bước cuối
                files_found = os.listdir(save_dir)
                return {
                    'status': 'error', 
                    'message': f"Kaggle xong nhưng không thấy file .joblib! Chỉ thấy: {files_found}"
                }
                
        elif 'error' in status_lower:
            return {'status': 'error', 'message': f'Kernel Failed: {raw_status}'}
            
        else:
            # running, queued...
            return {'status': 'running', 'message': f'Status: {raw_status}'}
            
    except Exception as e:
        return {'status': 'error', 'message': f"API Error: {str(e)}"}