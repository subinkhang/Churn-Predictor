# -*- coding: utf-8 -*-
from odoo import models, fields, api
import os
import base64
from datetime import datetime
from odoo.modules import get_module_resource

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
    
    @api.model
    def action_save_uploaded_data(self, filename, file_content):
        """
        Hàm nhận file upload và lưu vào thư mục upload_data trong module
        """
        # 1. Xác định đường dẫn thư mục 'upload_data' bên trong Container
        # Hàm này sẽ trả về đường dẫn tới thư mục gốc của module ChurnPredictor
        module_path = get_module_resource('ChurnPredictor')
        
        if not module_path:
            # Fallback nếu không tìm thấy resource (ít khi xảy ra)
            module_path = os.path.dirname(os.path.dirname(__file__))

        folder_path = os.path.join(module_path, 'upload_data')

        # 2. Tạo thư mục nếu chưa tồn tại
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        # 3. Xử lý tên file (Thêm Timestamp)
        # Tách tên và đuôi file (VD: 'data.csv' -> 'data' và '.csv')
        name_only, extension = os.path.splitext(filename)
        
        # Lấy thời gian hiện tại: NămThángNgày_GiờPhútGiây
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Tạo tên mới: data_20251128_103000.csv
        new_filename = f"{name_only}_{timestamp}{extension}"
        
        file_path = os.path.join(folder_path, new_filename)
        
        try:
            data = base64.b64decode(file_content)
            with open(file_path, 'wb') as f:
                f.write(data)
            
            print(f"==== FILE SAVED: {file_path} ====")
            
            # Trả về tên file mới để Javascript hiển thị cho user biết
            return {'status': 'success', 'path': new_filename} 
        except Exception as e:
            return {'status': 'error', 'message': str(e)}