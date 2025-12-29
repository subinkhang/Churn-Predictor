# -*- coding: utf-8 -*-
import os
import json
import shutil
import sys
import time
import logging
import subprocess
from datetime import datetime
import ssl
import urllib3

_logger = logging.getLogger(__name__)

# Cấu hình
DATASET_SLUG = 'subinkhang/olist-merged-dataset-2016-2017'
KERNEL_SLUG = 'subinkhang/churn-predictor-4'
NOTEBOOK_FILE_NAME = "churn-predictor-4.ipynb"

def _ultimate_ssl_patch_for_faketime():
    """
    GIẢI PHÁP DỨT ĐIỂM: Ghi đè (monkey-patch) trực tiếp vào tầng 'urllib3',
    thư viện mạng mà hầu hết các thư viện Python (bao gồm cả Kaggle) sử dụng.
    Cách này ép buộc mọi kết nối HTTPS bỏ qua việc xác minh SSL.
    """
    try:
        # Lưu lại phương thức __init__ gốc của HTTPSConnectionPool
        original_init = urllib3.connectionpool.HTTPSConnectionPool.__init__

        def new_init(self, *args, **kwargs):
            # Ép buộc các tham số bỏ qua SSL
            kwargs['assert_hostname'] = False
            kwargs['cert_reqs'] = 'CERT_NONE'
            _logger.critical("!!! MONKEY-PATCH APPLIED: Forcing SSL verification OFF at urllib3 level.")
            # Gọi lại phương thức __init__ gốc với các tham số đã bị sửa đổi
            original_init(self, *args, **kwargs)

        # Thay thế phương thức __init__ gốc bằng phương thức mới của chúng ta
        urllib3.connectionpool.HTTPSConnectionPool.__init__ = new_init
        
        _logger.critical("!!! CẢNH BÁO: ĐÃ VÔ HIỆU HÓA XÁC MINH SSL TRÊN TOÀN CỤC (URLLIB3) !!!")
        _logger.critical("!!! Chỉ sử dụng cho môi trường DEV với FAKETIME. KHÔNG DÙNG CHO PRODUCTION. !!!")
        return True
    except Exception as e:
        _logger.error(f"Không thể áp dụng SSL monkey-patch cuối cùng: {e}")
        return False

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
    Xác thực và CẤU HÌNH BỎ QUA SSL một cách trực tiếp.
    """
    # 1. Set biến môi trường (vẫn giữ để đảm bảo)
    os.environ['KAGGLE_USERNAME'] = creds['username']
    os.environ['KAGGLE_KEY'] = creds['key']
    
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()

        # ======================================================
        # === PHẦN SỬA LỖI SSL QUAN TRỌNG NHẤT ===
        # ======================================================
        # Can thiệp trực tiếp vào đối tượng client của API
        # để tắt việc xác minh SSL cho tất cả các request sau này.
        if hasattr(api, '_ApiClient__client'):
            # Tên thuộc tính có thể thay đổi giữa các phiên bản, 
            # nên chúng ta kiểm tra cả hai trường hợp phổ biến
            api._ApiClient__client.configuration.verify_ssl = False
            _logger.info("✅✅✅ Đã tắt xác minh SSL trực tiếp trên Kaggle API client.")
        elif hasattr(api, 'api_client'):
            api.api_client.configuration.verify_ssl = False
            _logger.info("✅✅✅ Đã tắt xác minh SSL trực tiếp trên Kaggle api_client.")
        else:
            _logger.warning("Không thể tự động tắt SSL. Thư viện Kaggle có thể đã thay đổi.")
        # ======================================================

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
    
    # ==========================================================================
    # === PHẦN MỚI ĐƯỢC THÊM VÀO (AN TOÀN, KHÔNG ẢNH HƯỞNG CODE CŨ) ===
    # ==========================================================================
    # Mục tiêu: Trích xuất [VERSION] từ tên file đầu vào, ví dụ: 'raw_2018_...' -> '2018'
    # Điều này cần thiết để đặt tên cho file features output sau này.
    version_tag = 'unknown' # Giá trị mặc định nếu không trích xuất được
    try:
        filename = os.path.basename(csv_file_path)
        # Tách tên file theo dấu '_'. Ví dụ: 'raw_2018_20251210100000.csv'
        # -> ['raw', '2018', '20251210100000.csv']
        parts = filename.split('_')
        if len(parts) >= 2 and parts[0] == 'raw':
            version_tag = parts[1]
            _logger.info(f"Đã trích xuất Version Tag từ tên file: '{version_tag}'")
    except Exception as e:
        _logger.warning(f"Không thể trích xuất version tag từ tên file '{filename}': {e}")
    # ==========================================================================
    # === KẾT THÚC PHẦN MỚI ===
    # ==========================================================================


    # ==========================================================================
    # === TOÀN BỘ CODE CŨ CỦA BẠN - ĐƯỢC GIỮ NGUYÊN 100% ===
    # ==========================================================================
    
    # 1. Lấy credentials từ file của bạn
    creds = get_kaggle_creds(config_dir)
    
    # 2. Xác thực API
    api = authenticate_kaggle_programmatically(creds)
    _logger.info("✅ Authenticated successfully via Environment Variables")

    dataset_dir, kernel_dir = _prepare_temp_dir(temp_dir)
    file_name = os.path.basename(csv_file_path)

    # PHẦN 1: DATASET (Tuân thủ tài liệu: Update a Dataset)
    _logger.info("1. Downloading current dataset files...")
    try:
        api.dataset_download_files(DATASET_SLUG, path=dataset_dir, unzip=True)
        for f in os.listdir(dataset_dir):
            if f.endswith('.zip'): os.remove(os.path.join(dataset_dir, f))
    except Exception as e:
        _logger.warning(f"Download warning (Normal if first upload): {e}")

    shutil.copy(csv_file_path, os.path.join(dataset_dir, file_name))
    _logger.info(f"   -> Added file: {file_name}")
    
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(dataset_dir, 'trigger_info.json'), 'w', encoding='utf-8') as f:
        json.dump({"run_id": run_id, "file": file_name}, f)

    meta_data = {
        "title": "Olist Merged Dataset 2016-2017",
        "id": DATASET_SLUG,
        "licenses": [{"name": "CC0-1.0"}]
    }
    with open(os.path.join(dataset_dir, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    _logger.info("2. Creating new dataset version...")
    try:
        api.dataset_create_version(
            folder=dataset_dir,
            version_notes=f'Odoo Update: {run_id}',
            dir_mode='zip',
            quiet=True
        )
        _logger.info(">>> DATASET UPLOAD SUCCESS")
    except Exception as e:
        _logger.error(f"DATASET UPLOAD FAILED: {e}")
        raise e

    # PHẦN 2: NOTEBOOK (Tuân thủ tài liệu: Push a Notebook)
    time.sleep(5)
    _logger.info("3. Handling Notebook...")
    
    try:
        api.kernels_pull(KERNEL_SLUG, path=kernel_dir, metadata=False)
    except: pass

    nb_path = os.path.join(kernel_dir, NOTEBOOK_FILE_NAME)
    if not os.path.exists(nb_path):
        candidates = [f for f in os.listdir(kernel_dir) if f.endswith('.ipynb')]
        if candidates: os.rename(os.path.join(kernel_dir, candidates[0]), nb_path)
    
    if os.path.exists(nb_path): _fix_notebook_encoding(nb_path)

    k_meta = {
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
        json.dump(k_meta, f, indent=4)

    _logger.info("4. Pushing Kernel to Trigger Run...")
    try:
        api.kernels_push(folder=kernel_dir)
        _logger.info(">>> KERNEL TRIGGER SUCCESS")
    except Exception as e:
        _logger.error(f"KERNEL TRIGGER FAILED: {e}")
        raise e
    
    # ==========================================================================
    # === THAY ĐỔI CUỐI CÙNG: TRẢ VỀ CẢ 2 GIÁ TRỊ ===
    # ==========================================================================
    # Thay vì: return run_id
    return run_id, version_tag

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
    
def check_and_download_if_ready(run_id, ml_assets_dir, data_to_import_dir=None, version_tag=None):
    """
    (ĐÃ SỬA) Hàm kiểm tra, tải output, và xử lý cả model lẫn file features.
    - Các tham số data_to_import_dir và version_tag giờ là tùy chọn.
    """
    KERNEL_SLUG = 'subinkhang/churn-predictor-4' 
    MODEL_FILENAME = 'churn_model.joblib'
    FEATURES_FILENAME = 'super-merged.csv'

    # === BẮT ĐẦU PHẦN SỬA LỖI ===
    # 1. Nếu version_tag không được cung cấp, dùng giá trị mặc định
    if version_tag is None:
        version_tag = 'latest'
        _logger.info(f"Tham số 'version_tag' không được cung cấp, sử dụng giá trị mặc định: '{version_tag}'")

    # 2. Nếu data_to_import_dir không được cung cấp, tự suy ra đường dẫn
    if data_to_import_dir is None:
        # Đường dẫn ml_assets_dir là .../ChurnPredictor/models/ml_assets
        # Chúng ta cần đi lên 2 cấp để có được thư mục gốc của module
        module_root = os.path.dirname(os.path.dirname(ml_assets_dir))
        data_to_import_dir = os.path.join(module_root, 'data_to_import')
        _logger.info(f"Tham số 'data_to_import_dir' không được cung cấp, tự suy ra đường dẫn: {data_to_import_dir}")
        # Đảm bảo thư mục tồn tại
        if not os.path.exists(data_to_import_dir):
            os.makedirs(data_to_import_dir, exist_ok=True)
    # === KẾT THÚC PHẦN SỬA LỖI ===

    try:
        # 1. Xác định đường dẫn thư mục config
        module_root = os.path.dirname(os.path.dirname(ml_assets_dir))
        config_dir = os.path.join(module_root, 'config')

        # 2. Đọc file kaggle.json
        creds = get_kaggle_creds(config_dir)

        # 3. Gọi hàm xác thực đầy đủ (quan trọng nhất)
        api = authenticate_kaggle_programmatically(creds)
        _logger.info("✅ Authenticated successfully for status check.")
        
    except Exception as e:
        return {'status': 'error', 'message': f"Auth Error during status check: {str(e)}"}

    try:
        kernel_status = api.kernels_status(KERNEL_SLUG)
        raw_status = str(kernel_status)
        status_lower = raw_status.lower()
        _logger.info(f"KAGGLE STATUS RAW: {raw_status}")

        if 'complete' in status_lower:
            # Tạo thư mục tạm để chứa output tải về
            # (Sử dụng run_id, nếu là 'latest' thì cũng không sao)
            temp_download_dir = os.path.join(ml_assets_dir, f"temp_download_{run_id.replace(':', '').replace(' ', '_')}")
            if os.path.exists(temp_download_dir): shutil.rmtree(temp_download_dir)
            os.makedirs(temp_download_dir, exist_ok=True)

            _logger.info(f"Status is COMPLETE. Downloading all outputs to: {temp_download_dir}")
            
            try:
                api.kernels_output(KERNEL_SLUG, path=temp_download_dir)
            except Exception as download_err:
                shutil.rmtree(temp_download_dir)
                return {'status': 'error', 'message': f"Download Failed: {download_err}"}

            # Khởi tạo kết quả trả về
            result = {'status': 'done', 'message': ''}
            
            # --- XỬ LÝ FILE MODEL (.joblib) ---
            model_src_path = os.path.join(temp_download_dir, MODEL_FILENAME)
            if os.path.exists(model_src_path):
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_dest_dir = os.path.join(ml_assets_dir, timestamp_str)
                os.makedirs(model_dest_dir, exist_ok=True)
                
                for f in os.listdir(temp_download_dir):
                    if f.endswith('.joblib') or f.endswith('.pkl'):
                        shutil.move(os.path.join(temp_download_dir, f), model_dest_dir)
                
                # Sửa lỗi ở đây: Trả về model_file_path thay vì file_path
                result['model_file_path'] = os.path.join(model_dest_dir, MODEL_FILENAME)
                result['message'] += 'Model downloaded successfully. '
                _logger.info(f"✅ Model moved to: {model_dest_dir}")
            else:
                result['status'] = 'error'
                result['message'] += 'Kernel finished but model file not found! '

            # --- XỬ LÝ FILE FEATURES (super-merged.csv) ---
            features_src_path = os.path.join(temp_download_dir, FEATURES_FILENAME)
            if os.path.exists(features_src_path):
                timestamp_str_file = datetime.now().strftime("%Y%m%d%H%M%S")
                new_filename = f"features_{version_tag}_{timestamp_str_file}.csv"
                features_dest_path = os.path.join(data_to_import_dir, new_filename)
                
                shutil.move(features_src_path, features_dest_path)
                
                result['features_file_path'] = features_dest_path
                result['message'] += 'Features file downloaded successfully.'
                _logger.info(f"✅ Features file moved to: {features_dest_path}")
            else:
                result['message'] += 'Warning: Features file (super-merged.csv) not found in output.'
                _logger.warning(f"⚠️ Không tìm thấy file '{FEATURES_FILENAME}' trong output của Kaggle.")

            shutil.rmtree(temp_download_dir)
            
            return result
                
        elif 'error' in status_lower:
            return {'status': 'error', 'message': f'Kernel Failed: {raw_status}'}
            
        else:
            return {'status': 'running', 'message': f'Status: {raw_status}'}
            
    except Exception as e:
        return {'status': 'error', 'message': f"API Error: {str(e)}"}

# def check_and_download_if_ready(run_id, ml_assets_dir, data_to_import_dir, version_tag):
#     """
#     Hàm kiểm tra, tải output, và xử lý cả model lẫn file features.
#     """
#     KERNEL_SLUG = 'subinkhang/churn-predictor-4' 
#     MODEL_FILENAME = 'churn_model.joblib'
#     FEATURES_FILENAME = 'super-merged.csv' # Tên file output từ Kaggle
    
#     try:
#         from kaggle.api.kaggle_api_extended import KaggleApi
#         api = KaggleApi()
#         api.authenticate()
#     except Exception as e:
#         return {'status': 'error', 'message': f"Auth Error: {str(e)}"}

#     try:
#         kernel_status = api.kernels_status(KERNEL_SLUG)
#         raw_status = str(kernel_status)
#         status_lower = raw_status.lower()
#         _logger.info(f"KAGGLE STATUS RAW: {raw_status}")

#         if 'complete' in status_lower:
#             # Tạo thư mục tạm để chứa output tải về
#             temp_download_dir = os.path.join(ml_assets_dir, f"temp_download_{run_id.replace(':', '').replace(' ', '_')}")
#             if os.path.exists(temp_download_dir): shutil.rmtree(temp_download_dir)
#             os.makedirs(temp_download_dir, exist_ok=True)

#             _logger.info(f"Status is COMPLETE. Downloading all outputs to: {temp_download_dir}")
            
#             try:
#                 api.kernels_output(KERNEL_SLUG, path=temp_download_dir)
#             except Exception as download_err:
#                 shutil.rmtree(temp_download_dir)
#                 return {'status': 'error', 'message': f"Download Failed: {download_err}"}

#             # Khởi tạo kết quả trả về
#             result = {'status': 'done', 'message': ''}
            
#             # --- XỬ LÝ FILE MODEL (.joblib) ---
#             model_src_path = os.path.join(temp_download_dir, MODEL_FILENAME)
#             if os.path.exists(model_src_path):
#                 # Tạo thư mục lưu model chính thức
#                 timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
#                 model_dest_dir = os.path.join(ml_assets_dir, timestamp_str)
#                 os.makedirs(model_dest_dir, exist_ok=True)
                
#                 # Di chuyển file model và các file liên quan (.pkl)
#                 for f in os.listdir(temp_download_dir):
#                     if f.endswith('.joblib') or f.endswith('.pkl'):
#                         shutil.move(os.path.join(temp_download_dir, f), model_dest_dir)
                
#                 result['model_file_path'] = os.path.join(model_dest_dir, MODEL_FILENAME)
#                 result['message'] += 'Model downloaded successfully. '
#                 _logger.info(f"✅ Model moved to: {model_dest_dir}")
#             else:
#                 result['status'] = 'error'
#                 result['message'] += 'Kernel finished but model file not found! '

#             # --- XỬ LÝ FILE FEATURES (super-merged.csv) ---
#             features_src_path = os.path.join(temp_download_dir, FEATURES_FILENAME)
#             if os.path.exists(features_src_path):
#                 # Tạo tên file mới theo định dạng
#                 timestamp_str_file = datetime.now().strftime("%Y%m%d%H%M%S")
#                 new_filename = f"features_{version_tag}_{timestamp_str_file}.csv"
#                 features_dest_path = os.path.join(data_to_import_dir, new_filename)
                
#                 # Di chuyển và đổi tên file
#                 shutil.move(features_src_path, features_dest_path)
                
#                 result['features_file_path'] = features_dest_path
#                 result['message'] += 'Features file downloaded successfully.'
#                 _logger.info(f"✅ Features file moved to: {features_dest_path}")
#             else:
#                 # Không coi đây là lỗi nghiêm trọng, chỉ là cảnh báo
#                 result['message'] += 'Warning: Features file (super-merged.csv) not found in output.'
#                 _logger.warning(f"⚠️ Không tìm thấy file '{FEATURES_FILENAME}' trong output của Kaggle.")

#             # Dọn dẹp thư mục tạm
#             shutil.rmtree(temp_download_dir)
            
#             return result
                
#         elif 'error' in status_lower:
#             return {'status': 'error', 'message': f'Kernel Failed: {raw_status}'}
            
#         else:
#             return {'status': 'running', 'message': f'Status: {raw_status}'}
            
#     except Exception as e:
#         return {'status': 'error', 'message': f"API Error: {str(e)}"}

# def _disable_ssl_verify_for_faketime():
#     """
#     MONKEY-PATCH: Vô hiệu hóa kiểm tra SSL trên toàn cục.
#     Đây là giải pháp mạnh tay để giải quyết lỗi CERTIFICATE_VERIFY_FAILED khi dùng FAKETIME.
#     """
#     try:
#         # Tạo một context SSL "không an toàn" (không kiểm tra gì cả)
#         unverified_context = ssl._create_unverified_context()
#         # Ghi đè context mặc định của thư viện ssl
#         ssl._create_default_https_context = lambda: unverified_context
#         _logger.warning("!!! SSL CERTIFICATE VERIFICATION GLOBALLY DISABLED !!! This is for FAKETIME development mode ONLY.")
#     except AttributeError:
#         # Python phiên bản cũ có thể không có _create_unverified_context
#         # Bỏ qua nếu không thực hiện được
#         _logger.warning("Could not apply SSL monkey-patch. SSL errors may occur.")

# def _monkey_patch_ssl_for_faketime():
#     """
#     GIẢI PHÁP DỨT ĐIỂM: Vô hiệu hóa kiểm tra SSL trên TOÀN CỤC.
#     Hàm này được gọi một lần duy nhất khi module khởi động.
#     """
#     try:
#         # 1. Vô hiệu hóa các cảnh báo về kết nối không an toàn
#         urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
#         # 2. Tạo một context SSL "giả" (không kiểm tra gì cả)
#         unverified_context = ssl._create_unverified_context()
        
#         # 3. Ghi đè (monkey-patch) hàm tạo context mặc định của thư viện ssl
#         # Bất kỳ thư viện nào (requests, kaggle-api) gọi kết nối HTTPS sau đây
#         # đều sẽ dùng context "giả" này.
#         ssl._create_default_https_context = lambda: unverified_context
        
#         _logger.critical("!!! CẢNH BÁO: ĐÃ VÔ HIỆU HÓA XÁC MINH SSL TRÊN TOÀN CỤC !!!")
#         _logger.critical("!!! Chỉ sử dụng cho môi trường DEV với FAKETIME. KHÔNG DÙNG CHO PRODUCTION. !!!")
#         return True
#     except Exception as e:
#         _logger.error(f"Không thể áp dụng SSL monkey-patch: {e}")
#         return False
