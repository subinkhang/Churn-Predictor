# File: custom_addons/ChurnPredictor/models/churn_admin_tools.py

import os
import logging
from odoo import models, api, _
from odoo.exceptions import UserError
from ..scripts import import_raw_data, import_features

_logger = logging.getLogger(__name__)

class ChurnAdminTools(models.TransientModel):
    _name = 'churn.admin.tools'
    _description = 'Churn Predictor Admin Tools'

    def _find_latest_file(self, prefix):
        """Hàm tìm file mới nhất trong thư mục data_to_import."""
        module_path = os.path.dirname(os.path.dirname(__file__))
        data_dir = os.path.join(module_path, 'data_to_import')
        
        try:
            candidate_files = [f for f in os.listdir(data_dir) if f.startswith(prefix) and f.endswith('.csv')]
            if not candidate_files:
                return None, None
            candidate_files.sort()
            latest_filename = candidate_files[-1]
            return latest_filename, os.path.join(data_dir, latest_filename)
        except FileNotFoundError:
            _logger.error(f"Thư mục không tồn tại để tìm file: {data_dir}")
            return None, None

    # Đây là "siêu hàm" mà chúng ta sẽ gọi
    def action_run_full_import_pipeline(self):
        """
        "SIÊU HÀM" IMPORT: Thực hiện toàn bộ quy trình import tuần tự.
        Được thiết kế để có thể gọi từ bất kỳ đâu.
        Ném ra Exception nếu có lỗi để nơi gọi có thể xử lý.
        """
        _logger.info("========================================================")
        _logger.info("=== BẮT ĐẦU QUY TRÌNH IMPORT DỮ LIỆU NỘI BỘ ===")
        
        # --- TÁC VỤ 1: IMPORT DỮ LIỆU THÔ ---
        _logger.info("--- TÁC VỤ 1: Tìm và xử lý file Dữ liệu Thô...")
        raw_filename, raw_filepath = self._find_latest_file('raw_')
        if not raw_filepath:
            raise UserError(_("Không tìm thấy file raw data (raw_*.csv) nào."))
        _logger.info(f"   -> Sẽ xử lý file: {raw_filename}")
        
        try:
            import_raw_data.import_raw_data(self.env, raw_filepath)
            _logger.info("   -> HOÀN TẤT: Import Raw Data thành công.")
        except Exception as e:
            _logger.error("   -> LỖI: Import Raw Data thất bại: %s", e, exc_info=True)
            raise # Ném lại lỗi để hàm gọi biết và xử lý

        # --- TÁC VỤ 2: IMPORT/UPDATE FEATURES ---
        _logger.info("--- TÁC VỤ 2: Tìm và xử lý file Features...")
        features_filename, features_filepath = self._find_latest_file('features_')
        if not features_filepath:
            raise UserError(_("Không tìm thấy file features (features_*.csv) nào."))
        _logger.info(f"   -> Sẽ xử lý file: {features_filename}")

        try:
            import_features.import_customer_features(self.env, features_filepath)
            _logger.info("   -> HOÀN TẤT: Import Features thành công.")
        except Exception as e:
            _logger.error("   -> LỖI: Import Features thất bại: %s", e, exc_info=True)
            raise

        _logger.info("=== QUY TRÌNH IMPORT NỘI BỘ HOÀN TẤT THÀNH CÔNG! ===")
        return True