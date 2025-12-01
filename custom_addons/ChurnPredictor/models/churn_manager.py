import base64
import os
import json
import subprocess
import shutil
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.modules.module import get_module_resource

class ChurnDataset(models.Model):
    _name = 'churn.dataset'
    _description = 'Quản lý Dataset và Huấn luyện Churn Model'

    name = fields.Char(string='Tên đợt dữ liệu', required=True, default='New Batch')
    csv_file = fields.Binary(string='File CSV (Đã merge)')
    file_name = fields.Char(string='Tên file')
    state = fields.Selection([
        ('draft', 'Mới'),
        ('training', 'Đang xử lý'),
        ('done', 'Hoàn tất')
    ], default='draft')

    # --- CẤU HÌNH KAGGLE ---
    KAGGLE_USERNAME = 'your_kaggle_username'
    DATASET_SLUG = 'your_username/your-dataset-slug'
    KERNEL_SLUG = 'your_username/your-notebook-slug'
    
    # --- ĐƯỜNG DẪN TẠM THỜI ---
    TEMP_DIR = '/tmp/odoo_kaggle_churn'

    def _get_module_paths(self):
        """
        Hàm tiện ích để lấy đường dẫn tuyệt đối đến các folder trong module
        """
        # Lấy đường dẫn của file hiện tại (churn_manager.py)
        current_file_path = os.path.realpath(__file__)
        # Đi ngược lên 2 cấp để về thư mục gốc của module (churn_prediction/)
        # models/ -> churn_prediction/
        module_root_path = os.path.dirname(os.path.dirname(current_file_path))
        
        return {
            'root': module_root_path,
            'config': os.path.join(module_root_path, 'config'),
            'sample_data': os.path.join(module_root_path, 'data', 'sample', 'olist_merged_2018_month_01.csv')
        }

    @api.onchange('name') # Hoặc dùng nút bấm test riêng
    def _load_sample_csv_for_testing(self):
        """
        Hàm hỗ trợ dev: Tự động load file CSV test vào trường Binary
        nếu người dùng chưa upload gì cả.
        """
        if not self.csv_file:
            paths = self._get_module_paths()
            sample_path = paths['sample_data']
            
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as f:
                    file_content = f.read()
                    self.csv_file = base64.b64encode(file_content)
                    self.file_name = 'olist_merged_2018_month_01.csv'
                    # print(f"Đã load file mẫu từ: {sample_path}")

    def action_trigger_kaggle_pipeline(self):
        self.ensure_one()
        
        # 1. LẤY ĐƯỜNG DẪN CONFIG TỪ SOURCE CODE
        paths = self._get_module_paths()
        kaggle_config_dir = paths['config']
        kaggle_json_path = os.path.join(kaggle_config_dir, 'kaggle.json')

        # Kiểm tra xem file json có tồn tại không (phòng trường hợp quên copy vào server)
        if not os.path.exists(kaggle_json_path):
            raise UserError(_(
                "Không tìm thấy file xác thực 'kaggle.json'. \n"
                "Vui lòng đặt file này vào thư mục: %s"
            ) % kaggle_config_dir)

        # Thiết lập biến môi trường để thư viện Kaggle nhận diện
        os.environ['KAGGLE_CONFIG_DIR'] = kaggle_config_dir
        
        # 2. Chuẩn bị thư mục tạm
        dataset_dir = os.path.join(self.TEMP_DIR, 'dataset')
        kernel_dir = os.path.join(self.TEMP_DIR, 'kernel')
        
        if os.path.exists(self.TEMP_DIR):
            shutil.rmtree(self.TEMP_DIR)
        os.makedirs(dataset_dir)
        os.makedirs(kernel_dir)

        try:
            # Nếu chưa có file, thử load file mẫu (cho mục đích test)
            if not self.csv_file:
                self._load_sample_csv_for_testing()
                if not self.csv_file:
                    raise UserError("Vui lòng upload file CSV hoặc cung cấp file mẫu.")

            # --- BƯỚC 3: UPLOAD DATASET ---
            self._upload_dataset_to_kaggle(dataset_dir)
            
            # --- BƯỚC 4: TRIGGER KERNEL ---
            self._trigger_kaggle_kernel(kernel_dir)

            self.state = 'training'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': 'Đã đẩy dữ liệu lên Kaggle và kích hoạt Notebook.',
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(f"Lỗi Kaggle Pipeline: {str(e)}")

    def _upload_dataset_to_kaggle(self, folder_path):
        """Xử lý logic tạo version mới cho Dataset"""
        
        # 1. Lưu file từ Odoo Binary xuống ổ cứng
        if not self.csv_file:
            raise UserError("Vui lòng upload file CSV trước.")
            
        file_content = base64.b64decode(self.csv_file)
        # Lưu ý: Nên lưu với tên file cố định hoặc theo quy tắc để Notebook dễ đọc
        # Ví dụ: new_batch_data.csv
        save_path = os.path.join(folder_path, self.file_name or 'olist_merged_2018_month_01.csv')
        
        with open(save_path, 'wb') as f:
            f.write(file_content)

        # 2. Tạo file metadata.json cho Dataset
        # Đây là file bắt buộc để Kaggle biết upload vào dataset nào
        meta_data = {
            "title": "Olist Churn Dataset", # Tên hiển thị
            "id": self.DATASET_SLUG,
            "licenses": [{"name": "CC0-1.0"}]
        }
        
        with open(os.path.join(folder_path, 'dataset-metadata.json'), 'w') as f:
            json.dump(meta_data, f)

        # 3. Gọi lệnh Kaggle CLI để upload
        # Lệnh: kaggle datasets version -p /path -m "Message"
        cmd = [
            'kaggle', 'datasets', 'version',
            '-p', folder_path,
            '-m', f'Update from Odoo: {self.name}',
            '--dir-mode', 'zip' # Nén lại cho gọn
        ]
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise Exception(f"Dataset Upload Failed: {process.stderr}")
        
        print(">>> Dataset uploaded successfully.")

    def _trigger_kaggle_kernel(self, folder_path):
        """
        Xử lý logic Push Kernel để kích hoạt chạy lại.
        Thực chất là tải code notebook về, tạo metadata, và push ngược lại.
        """
        
        # 1. Tạo file metadata.json cho Kernel
        # Để chạy lại, ta chỉ cần push lại kernel.
        # Kernel trên Kaggle phải được tạo trước và link với Dataset ở trên.
        
        kernel_slug_parts = self.KERNEL_SLUG.split('/') # [username, slug]
        
        meta_data = {
            "id": self.KERNEL_SLUG,
            "title": "Olist Churn Prediction Notebook",
            "code_file": "churn_predictor.ipynb", # Tên file notebook
            "language": "python",
            "kernel_type": "notebook",
            "is_private": "true",
            "enable_gpu": "true", # Bật GPU nếu cần
            "enable_internet": "true",
            "dataset_sources": [self.DATASET_SLUG], # Quan trọng: Link với dataset vừa up
            "kernel_sources": []
        }
        
        with open(os.path.join(folder_path, 'kernel-metadata.json'), 'w') as f:
            json.dump(meta_data, f)
            
        # 2. Lấy nội dung Notebook (Source code)
        # Ở đây có 2 cách: 
        # C1: Pull notebook hiện tại từ Kaggle về (để đảm bảo code mới nhất).
        # C2: Lưu trữ file .ipynb ngay trong module Odoo và copy ra.
        # Dưới đây dùng C1 (Pull về).
        
        pull_cmd = ['kaggle', 'kernels', 'pull', self.KERNEL_SLUG, '-p', folder_path, '-m']
        pull_process = subprocess.run(pull_cmd, capture_output=True, text=True)
        
        if pull_process.returncode != 0:
             # Nếu pull lỗi (ví dụ lần đầu), bạn cần có file .ipynb gốc trong code Odoo để copy vào folder_path
             raise Exception(f"Kernel Pull Failed: {pull_process.stderr}")

        # 3. Push Kernel (Hành động này sẽ Trigger "Run All" trên Kaggle)
        push_cmd = ['kaggle', 'kernels', 'push', '-p', folder_path]
        push_process = subprocess.run(push_cmd, capture_output=True, text=True)
        
        if push_process.returncode != 0:
            raise Exception(f"Kernel Push (Trigger) Failed: {push_process.stderr}")
            
        print(">>> Kernel triggered successfully.")