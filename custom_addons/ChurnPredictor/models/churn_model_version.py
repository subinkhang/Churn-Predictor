# -*- coding: utf-8 -*-
import base64
import os
import json
import logging
from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError
from . import kaggle_connector 

_logger = logging.getLogger(__name__)

class ChurnModelVersion(models.Model):
    _name = 'churn.model.version'
    _description = 'Churn Model Version Control'
    _order = 'create_date desc'

    name = fields.Char(string='Version Name', required=True, default='New Model')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('training', 'Training'),
        ('done', 'Done'),
        ('active', 'Active')
    ], default='draft')

    # Hyperparameters
    learning_rate = fields.Float(default=0.1)
    n_estimators = fields.Integer(default=100)
    max_depth = fields.Integer(default=6)

    # Metrics (Kết quả)
    accuracy_score = fields.Float(readonly=True)
    f1_score = fields.Float(readonly=True)
    training_log = fields.Text(default="Ready to train...")

    # --- [MỚI] Fields hỗ trợ tách nút bấm ---
    latest_csv_path = fields.Char(string="Path to Latest CSV")
    latest_filename = fields.Char(string="File Name", readonly=True) 
    
    model_path = fields.Char(string="Model Path", readonly=True)
    
    @api.model
    def action_save_uploaded_data(self, file_name, base64_data):
        """
        BUTTON 1: CHỈ LƯU FILE (KHÔNG GỌI KAGGLE)
        Hàm này được gọi từ JS khi người dùng upload file.
        """
        try:
            _logger.info(f"--- [UPLOAD] SAVING FILE: {file_name} ---")

            # 1. Xác định đường dẫn
            module_path = os.path.dirname(os.path.dirname(__file__)) 
            history_root_dir = os.path.join(module_path, 'data', 'dataset_history')

            # 2. Tạo folder phiên bản (TIMESTAMP)
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            version_dir = os.path.join(history_root_dir, timestamp_str)
            
            if not os.path.exists(version_dir):
                os.makedirs(version_dir, exist_ok=True)

            # 3. Lưu file CSV
            file_content = base64.b64decode(base64_data)
            saved_file_path = os.path.join(version_dir, file_name)
            
            with open(saved_file_path, "wb") as f:
                f.write(file_content)

            # 4. Lưu Metadata
            info = {
                "version_id": timestamp_str,
                "original_name": file_name,
                "uploaded_at": str(datetime.now()),
                "status": "uploaded_locally_pending_train"
            }
            with open(os.path.join(version_dir, 'info.json'), 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4)

            _logger.info(f"File saved at: {saved_file_path}")

            # Trả về đường dẫn để JS update vào bản ghi
            return {
                'status': 'success', 
                'message': f'File saved successfully (Version {timestamp_str}). Ready to train.',
                'file_path': saved_file_path
            }

        except Exception as e:
            _logger.error(f"UPLOAD ERROR: {e}")
            return {'status': 'error', 'message': str(e)}

    def action_trigger_retrain(self):
        """
        BUTTON 2: GỌI KAGGLE (Dùng file đã lưu trong latest_csv_path)
        Hàm này được gọi khi người dùng bấm nút 'Retrain' trên giao diện.
        """
        self.ensure_one() # Đảm bảo đang thao tác trên 1 bản ghi cụ thể

        # Kiểm tra xem đã có file chưa
        target_file = self.latest_csv_path
        
        # Nếu chưa upload file mới, thử tìm file mẫu mặc định (cho mục đích demo/test)
        if not target_file or not os.path.exists(target_file):
             module_path = os.path.dirname(os.path.dirname(__file__))
             sample_file = os.path.join(module_path, 'data', 'sample', 'olist_merged_2018_month_01.csv')
             if os.path.exists(sample_file):
                 _logger.warning("No uploaded file found. Using sample file for training.")
                 target_file = sample_file
             else:
                 return {'status': 'error', 'message': 'No CSV file found to train! Please upload data first.'}

        try:
            _logger.info(f"--- [RETRAIN] TRIGGERING KAGGLE FOR: {target_file} ---")
            
            module_path = os.path.dirname(os.path.dirname(__file__))
            config_dir = os.path.join(module_path, 'config')
            temp_work_dir = os.path.join(module_path, 'temp_kaggle_process')

            # Cập nhật trạng thái UI
            self.write({
                'state': 'training',
                'training_log': f"Starting Kaggle Pipeline...\nFile: {os.path.basename(target_file)}\nWaiting for upload..."
            })

            # Gọi Connector (Hàm này có thể mất thời gian)
            run_id = kaggle_connector.run_kaggle_pipeline(
                csv_file_path=target_file,
                config_dir=config_dir,
                temp_dir=temp_work_dir 
            )
            
            # Cập nhật Log sau khi Trigger thành công
            self.write({
                'training_log': f"--- KAGGLE RUNNING ---\nRun ID: {run_id}\nNotebook is queued/running on Kaggle.\nCheck Kaggle UI for progress."
            })
            
            return {
                'status': 'success',
                'message': f'Training triggered on Kaggle (Run ID: {run_id})'
            }
            
        except Exception as e:
            _logger.error(f"RETRAIN ERROR: {e}")
            self.write({'state': 'draft', 'training_log': f"Error: {str(e)}"})
            return {'status': 'error', 'message': str(e)}
        
    def action_check_and_download(self):
        """
        Nút bấm mới: Kiểm tra xem Kaggle chạy xong chưa và tải về.
        """
        self.ensure_one()
        
        module_path = os.path.dirname(os.path.dirname(__file__))
        ml_assets_dir = os.path.join(module_path, 'models', 'ml_assets')
        
        # Gọi hàm download bên connector
        result_path = kaggle_connector.download_model_output(self.name, ml_assets_dir)
        
        if result_path:
            self.write({
                'state': 'done',
                'model_path': result_path,
                'training_log': self.training_log + f"\n[SUCCESS] Model downloaded: {result_path}"
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Thành công', 'message': 'Đã tải model về máy!', 'type': 'success'}
            }
        else:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Chưa xong', 'message': 'Kaggle đang chạy hoặc lỗi. Vui lòng thử lại sau.', 'type': 'warning'}
            }

    @api.model
    def check_training_status(self, model_id):
        record = self.browse(model_id)
        
        # ... (Các phần setup đường dẫn giữ nguyên) ...
        module_path = os.path.dirname(os.path.dirname(__file__))
        config_dir = os.path.join(module_path, 'config')
        ml_assets_dir = os.path.join(module_path, 'models', 'ml_assets')
        
        # Init API nếu cần
        try:
            kaggle_connector.init_kaggle_api_via_env(config_dir)
        except: pass

        # Gọi connector kiểm tra
        result = kaggle_connector.check_and_download_if_ready("latest", ml_assets_dir)
        
        # --- PHẦN CẦN SỬA LÀ Ở ĐÂY ---
        if result['status'] == 'done':
            # Lấy giờ hiện tại cho đẹp
            now_str = datetime.now().strftime("%H:%M:%S")
            
            record.write({
                'state': 'done',
                'model_path': result['file_path'],
                # SỬA DÒNG NÀY: Thay đường dẫn dài ngoằng bằng câu thông báo gọn gàng
                'training_log': record.training_log + f"\n[{now_str}] ✅ Successful, model đã được update."
            })
            
            # Cập nhật cả message trả về cho thông báo popup (notification)
            return {'status': 'done', 'message': 'Successful, model đã được update.'}
            
        elif result['status'] == 'error':
            record.write({'state': 'draft'})
            return {'status': 'error', 'message': result['message']}
            
        else:
            return {'status': 'running', 'message': result['message']}