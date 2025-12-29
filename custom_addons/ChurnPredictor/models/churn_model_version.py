# -*- coding: utf-8 -*-
import base64
import os
import json
import logging
from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError
from . import kaggle_connector 
from ..scripts import import_raw_data, import_features

_logger = logging.getLogger(__name__)

def _find_latest_file(directory, prefix):
    """
    Quét một thư mục và tìm file mới nhất dựa trên quy tắc đặt tên.
    """
    try:
        candidate_files = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith('.csv')]
        if not candidate_files:
            return None, None
        candidate_files.sort()
        latest_filename = candidate_files[-1]
        return latest_filename, os.path.join(directory, latest_filename)
    except FileNotFoundError:
        _logger.error(f"Thư mục không tồn tại để tìm file: {directory}")
        return None, None

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
    kaggle_run_id = fields.Char("Kaggle Run ID", readonly=True)
    kaggle_version_tag = fields.Char("Data Version Tag", readonly=True)
    
    @api.model
    def action_save_uploaded_data(self, file_name, base64_data):
        """
        BUTTON 1: LƯU FILE UPLOAD
        - [MỚI] Nếu là file raw data (tên chứa 'raw'), sẽ xử lý theo quy trình mới:
          + Đổi tên file theo định dạng chuẩn: raw_[VERSION]_[TIMESTAMP].csv
          + Lưu vào thư mục 'data_to_import'.
        - [CŨ] Nếu là file khác, giữ nguyên logic cũ (lưu vào 'dataset_history').
        """
        try:
            module_path = os.path.dirname(os.path.dirname(__file__))

            # --- BẮT ĐẦU LOGIC MỚI: KIỂM TRA VÀ XỬ LÝ FILE RAW DATA ---
            # Giả định file raw data có tên dạng: 'raw_2018.csv', 'raw_data_2019_final.csv', etc.
            if 'raw' in file_name.lower():
                _logger.info(f"--- [UPLOAD] Phát hiện file Raw Data: {file_name}. Xử lý theo quy trình mới. ---")
                
                # 1. Trích xuất version tag từ tên file
                # Ví dụ: 'raw_2018.csv' -> '2018'
                version_tag = 'unknown'
                try:
                    # Bỏ phần 'raw_' và phần '.csv'
                    base_name = os.path.splitext(file_name)[0]
                    version_tag = base_name.lower().replace('raw_', '').replace('raw', '')
                except:
                    pass
                
                # 2. Tạo tên file mới theo định dạng chuẩn
                timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S")
                new_filename = f"raw_{version_tag}_{timestamp_str}.csv"
                
                # 3. Xác định thư mục lưu trữ mới
                dest_dir = os.path.join(module_path, 'data_to_import')
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                
                saved_file_path = os.path.join(dest_dir, new_filename)
                
                # 4. Lưu file
                file_content = base64.b64decode(base64_data)
                with open(saved_file_path, "wb") as f:
                    f.write(file_content)
                
                _logger.info(f"File Raw Data đã được chuẩn hóa và lưu tại: {saved_file_path}")

                return {
                    'status': 'success', 
                    'message': f'File Raw Data đã được lưu thành công với tên: {new_filename}',
                    'file_path': saved_file_path,
                    'file_name': new_filename # Trả về tên file mới để JS có thể hiển thị
                }

            # --- KẾT THÚC LOGIC MỚI ---
            # Nếu file không phải là raw data, chạy logic cũ của bạn y hệt như trước
            else:
                _logger.info(f"--- [UPLOAD] SAVING FILE (LOGIC CŨ): {file_name} ---")
                history_root_dir = os.path.join(module_path, 'data', 'dataset_history')
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_dir = os.path.join(history_root_dir, timestamp_str)
                
                if not os.path.exists(version_dir):
                    os.makedirs(version_dir, exist_ok=True)

                file_content = base64.b64decode(base64_data)
                saved_file_path = os.path.join(version_dir, file_name)
                
                with open(saved_file_path, "wb") as f:
                    f.write(file_content)

                info = {
                    "version_id": timestamp_str,
                    "original_name": file_name,
                    "uploaded_at": str(datetime.now()),
                    "status": "uploaded_locally_pending_train"
                }
                with open(os.path.join(version_dir, 'info.json'), 'w', encoding='utf-8') as f:
                    json.dump(info, f, indent=4)

                _logger.info(f"File saved at: {saved_file_path}")

                return {
                    'status': 'success', 
                    'message': f'File saved successfully (Version {timestamp_str}). Ready to train.',
                    'file_path': saved_file_path,
                    'file_name': file_name # Trả về tên file gốc
                }

        except Exception as e:
            _logger.error(f"UPLOAD ERROR: {e}")
            return {'status': 'error', 'message': str(e)}

    def action_trigger_retrain(self):
        self.ensure_one()

        target_file = self.latest_csv_path
        
        if not target_file or not os.path.exists(target_file):
            module_path = os.path.dirname(os.path.dirname(__file__))
            sample_file = os.path.join(module_path, 'data', 'sample', 'olist_merged_2018_month_01.csv')
            if os.path.exists(sample_file):
                _logger.warning("No uploaded file found. Using sample file for training.")
                target_file = sample_file
            else:
                # Trả về lỗi dưới dạng dictionary để JS có thể xử lý
                raise UserError(_('No CSV file found to train! Please upload data first.'))

        try:
            _logger.info(f"--- [RETRAIN] TRIGGERING KAGGLE FOR: {target_file} ---")
            
            module_path = os.path.dirname(os.path.dirname(__file__))
            config_dir = os.path.join(module_path, 'config')
            temp_work_dir = os.path.join(module_path, 'temp_kaggle_process')

            self.write({
                'state': 'training',
                'training_log': f"Starting Kaggle Pipeline...\nFile: {os.path.basename(target_file)}\nWaiting for upload..."
            })
            self.env.cr.commit() # Commit để UI thấy trạng thái 'training' ngay lập tức

            # ======================================================
            # === SỬA ĐỔI TẠI ĐÂY: Nhận 2 giá trị trả về ===
            # ======================================================
            run_id, version_tag = kaggle_connector.run_kaggle_pipeline(
                csv_file_path=target_file,
                config_dir=config_dir,
                temp_dir=temp_work_dir 
            )
            # ======================================================
            
            # Cập nhật Log và LƯU LẠI cả 2 giá trị
            self.write({
                'training_log': f"--- KAGGLE RUNNING ---\nRun ID: {run_id}\nVersion Tag: {version_tag}\nNotebook is queued/running on Kaggle.",
                # === SỬA ĐỔI TẠI ĐÂY: Lưu lại cả 2 giá trị để hàm check_status có thể dùng ===
                'kaggle_run_id': run_id,
                'kaggle_version_tag': version_tag,
            })
            
            # Trả về cho JS để hiển thị thông báo
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Kaggle Triggered',
                    'message': f'Training started on Kaggle (Run ID: {run_id})',
                    'type': 'success',
                    'sticky': True # Giữ thông báo lâu hơn
                }
            }
            
        except Exception as e:
            _logger.error(f"RETRAIN ERROR: {e}", exc_info=True)
            self.write({'state': 'draft', 'training_log': f"Error: {str(e)}"})
            # Ném lỗi ra để JS có thể bắt và hiển thị
            raise UserError(_("Trigger failed: %s", e))
        
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

    # @api.model
    # def check_training_status(self, model_id):
    #     """
    #     HÀM ORCHESTRATOR (PHIÊN BẢN MẠNH MẼ NHẤT):
    #     - Xử lý download từ Kaggle.
    #     - Gọi pipeline import.
    #     - Cung cấp phản hồi chi tiết cho UI ở mỗi bước.
    #     """
    #     record = self.browse(model_id)
        
    #     module_path = os.path.dirname(os.path.dirname(__file__))
    #     ml_assets_dir = os.path.join(module_path, 'models', 'ml_assets')
    #     data_to_import_dir = os.path.join(module_path, 'data_to_import')

    #     # --- GIAI ĐOẠN 1: KẾT NỐI VÀ DOWNLOAD TỪ KAGGLE ---
    #     try:
    #         result = kaggle_connector.check_and_download_if_ready(
    #             run_id=record.kaggle_run_id,
    #             ml_assets_dir=ml_assets_dir,
    #             data_to_import_dir=data_to_import_dir,
    #             version_tag=record.kaggle_version_tag
    #         )
    #     except Exception as e:
    #         _logger.error(f"Lỗi khi gọi check_and_download: {e}", exc_info=True)
    #         return {'status': 'error', 'message': f'System Error during check: {e}'}

    #     # --- XỬ LÝ KẾT QUẢ TỪ KAGGLE ---
        
    #     # Trường hợp Kaggle đang chạy hoặc gặp lỗi
    #     if result.get('status') != 'done':
    #         if result.get('status') == 'error':
    #             record.write({'state': 'draft', 'training_log': record.training_log + f"\n[ERROR] {result.get('message')}"})
    #         return result # Trả về {status: 'running', ...} hoặc {status: 'error', ...}

    #     # Trường hợp KAGGLE ĐÃ CHẠY XONG (status == 'done')
    #     now_str = datetime.now().strftime("%H:%M:%S")
        
    #     # 1. Cập nhật log & trạng thái sau khi download
    #     download_message = result.get('message', 'Download completed successfully.')
    #     log_update = f"\n[{now_str}] ✅ {download_message}"
        
    #     update_vals = {
    #         'training_log': record.training_log + log_update
    #     }
    #     if result.get('model_file_path'):
    #         update_vals['model_path'] = result.get('model_file_path')
    #     record.write(update_vals)
    #     self.env.cr.commit()

    #     # --- GIAI ĐOẠN 2: KÍCH HOẠT PIPELINE IMPORT ---
    #     import_log = ""
    #     final_status = 'done' # Giả định thành công
    #     try:
    #         log_update = f"\n[{datetime.now().strftime('%H:%M:%S')}] ⏳ Starting internal data import pipeline..."
    #         record.write({'training_log': record.training_log + log_update})
    #         self.env.cr.commit()

    #         # Gọi "siêu hàm" import, nó sẽ tự xử lý và ném lỗi nếu thất bại
    #         self.env['churn.admin.tools'].action_run_full_import_pipeline()
            
    #         import_log = f"\n[{datetime.now().strftime('%H:%M:%S')}] ✅ Data import pipeline finished successfully."

    #     except Exception as e:
    #         _logger.error("--- MAIN PIPELINE FAILED AT IMPORT STAGE ---: %s", e, exc_info=True)
    #         import_log = f"\n[{datetime.now().strftime('%H:%M:%S')}] ❌ ERROR: Data import failed. Error: {e}"
    #         final_status = 'error' # Đánh dấu là đã gặp lỗi
        
    #     # 3. Cập nhật log và trạng thái cuối cùng
    #     final_state = 'done' if final_status == 'done' else 'draft'
    #     record.write({
    #         'state': final_state,
    #         'training_log': record.training_log + import_log
    #     })
        
    #     # Trả về kết quả cuối cùng cho frontend
    #     return {
    #         'status': final_status, 
    #         'message': download_message + import_log.replace('\n', ' ')
    #     }
    
    @api.model
    def check_training_status(self, model_id):
        record = self.browse(model_id)
        
        module_path = os.path.dirname(os.path.dirname(__file__))
        ml_assets_dir = os.path.join(module_path, 'models', 'ml_assets')
        data_to_import_dir = os.path.join(module_path, 'data_to_import')

        result = kaggle_connector.check_and_download_if_ready(
            run_id=record.kaggle_run_id,
            ml_assets_dir=ml_assets_dir,
            data_to_import_dir=data_to_import_dir,
            version_tag=record.kaggle_version_tag
        )
        
        if result.get('status') == 'done':
            now_str = datetime.now().strftime("%H:%M:%S")
            
            update_vals = {
                'state': 'done',
                'training_log': record.training_log + f"\n[{now_str}] ✅ {result.get('message', 'Download completed.')}"
            }
            
            # === ĐÂY LÀ DÒNG CODE ĐÚNG ===
            # Nó phải tìm khóa 'model_file_path'
            if result.get('model_file_path'):
                update_vals['model_path'] = result.get('model_file_path')
            # =============================
            
            record.write(update_vals)
            return {'status': 'done', 'message': result.get('message', 'Successfully updated model.')}
            
        elif result.get('status') == 'error':
            record.write({'state': 'draft', 'training_log': record.training_log + f"\n[ERROR] {result.get('message')}"})
            return {'status': 'error', 'message': result.get('message')}
            
        else: # status == 'running'
            return {'status': 'running', 'message': result.get('message')}
