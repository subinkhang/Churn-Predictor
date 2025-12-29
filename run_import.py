import xmlrpc.client
import os
from dotenv import load_dotenv

# Tải các biến môi trường từ file .env (nếu có)
load_dotenv()

# --- CẤU HÌNH KẾT NỐI ĐẾN ODOO (Giữ nguyên) ---
ODOO_URL = os.getenv('ODOO_URL', 'http://localhost:8069')
ODOO_DB = os.getenv('ODOO_DB', 'ChurnPredictor_v2')
ODOO_USER = os.getenv('ODOO_USER', 'admin')
ODOO_PASSWORD = os.getenv('ODOO_PASSWORD', 'admin')

# --- CẤU HÌNH THƯ MỤC DỮ LIỆU ---
DATA_DIR = './custom_addons/ChurnPredictor/data_to_import'

# ==============================================================================
# === CÁC HÀM TIỆN ÍCH (HELPER FUNCTIONS) ===
# ==============================================================================

def find_latest_file(directory, prefix):
    """
    Quét một thư mục và tìm file mới nhất dựa trên quy tắc đặt tên.
    Quy tắc: prefix_[VERSION]_[YYYYMMDDHHMMSS].csv
    
    Args:
        directory (str): Đường dẫn đến thư mục cần quét.
        prefix (str): Tiền tố của file (ví dụ: 'raw_' hoặc 'features_').

    Returns:
        str: Đường dẫn đầy đủ đến file mới nhất, hoặc None nếu không tìm thấy.
    """
    try:
        # Lọc ra các file phù hợp với tiền tố
        candidate_files = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith('.csv')]
        
        if not candidate_files:
            return None
        
        # Sắp xếp theo thứ tự chữ cái, file có timestamp lớn nhất sẽ ở cuối
        candidate_files.sort()
        latest_filename = candidate_files[-1]
        
        # Trả về đường dẫn đầy đủ
        return os.path.join(directory, latest_filename)
    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy thư mục: {directory}")
        return None

def execute_odoo_script(script_name, function_name, filename): # Thay *args thành filename
    """
    Kết nối và thực thi một script trên Odoo, chỉ truyền TÊN FILE.
    """
    try:
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
        if not uid:
            print("Lỗi xác thực Odoo.")
            return False

        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
        
        result = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, 'res.partner',
            'execute_script_from_python',
            # Truyền filename như một tham số duy nhất trong list
            [script_name, function_name, [filename]] 
        )
        
        print(f"Kết quả trả về từ Odoo: {result}")
        if isinstance(result, str) and result.startswith('Lỗi:'):
            return False
        return True

    except Exception as e:
        print(f"Đã xảy ra lỗi RPC: {e}")
        return False

if __name__ == '__main__':
    print("========================================================")
    print("=== BẮT ĐẦU QUY TRÌNH IMPORT DỮ LIỆU TỰ ĐỘNG ===")
    print("========================================================")

    # Tác vụ 1
    print("\n--- TÁC VỤ 1: Đang tìm và xử lý file Dữ liệu Thô mới nhất...")
    raw_filepath = find_latest_file(DATA_DIR, 'raw_')
    if not raw_filepath:
        print("LỖI: Không tìm thấy file raw data.")
        exit()

    # CHỈ LẤY TÊN FILE
    raw_filename = os.path.basename(raw_filepath)
    print(f"Đã tìm thấy file: {raw_filename}")
    success = execute_odoo_script('import_raw_data', 'import_raw_data', raw_filename)
    
    if not success:
        print("LỖI: Tác vụ 1 thất bại. Dừng quy trình.")
        exit()
    print("--- HOÀN TẤT TÁC VỤ 1 ---")

    # Tác vụ 2
    print("\n--- TÁC VỤ 2: Đang tìm và xử lý file Features mới nhất...")
    features_filepath = find_latest_file(DATA_DIR, 'features_')
    if not features_filepath:
        print("LỖI: Không tìm thấy file features.")
        exit()
        
    # CHỈ LẤY TÊN FILE
    features_filename = os.path.basename(features_filepath)
    print(f"Đã tìm thấy file: {features_filename}")
    success = execute_odoo_script('import_features', 'import_customer_features', features_filename)

    if not success:
        print("LỖI: Tác vụ 2 thất bại.")
        exit()
    print("--- HOÀN TẤT TÁC VỤ 2 ---")
    
    print("\n========================================================")
    print("=== QUY TRÌNH IMPORT HOÀN TẤT THÀNH CÔNG! ===")
    print("========================================================")
