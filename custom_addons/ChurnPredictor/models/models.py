# -*- coding: utf-8 -*-
import base64
from odoo import models, fields, api

class ChurnPrediction(models.Model):
    """
    Model này dùng để lưu trữ kết quả của mỗi lần dự đoán churn.
    Mỗi bản ghi (record) trong model này tương ứng với một lần chạy dự đoán
    cho một khách hàng tại một thời điểm cụ thể.
    """
    _name = 'churn.prediction'
    _description = 'Customer Churn Prediction Result'
    _order = 'prediction_date desc' # Sắp xếp mặc định theo ngày dự đoán mới nhất

    # --- Các trường (Fields) chính của Model ---

    # Mối quan hệ Many2one: Mỗi kết quả dự đoán thuộc về MỘT khách hàng.
    # 'res.partner' là model mặc định của Odoo để quản lý liên hệ (khách hàng, nhà cung cấp...).
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade', # Nếu khách hàng bị xóa, kết quả dự đoán liên quan cũng bị xóa.
        help="The customer for whom the prediction was made."
    )

    # Ngày và giờ thực hiện dự đoán. Mặc định là thời điểm tạo bản ghi.
    prediction_date = fields.Datetime(
        string='Prediction Date',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        help="Date and time when the prediction was generated."
    )

    # Kết quả dự đoán (dạng lựa chọn).
    prediction_result = fields.Selection(
        [
            ('churn', 'Churn'),
            ('no_churn', 'No Churn')
        ],
        string='Prediction Result',
        required=False,
        help="The outcome predicted by the model (Churn or No Churn)."
    )

    # Xác suất khách hàng sẽ rời bỏ (từ 0.0 đến 100.0).
    probability = fields.Float(
        string='Churn Probability (%)',
        digits=(16, 2), # Hiển thị với 2 chữ số thập phân.
        help="The probability (from 0 to 100) that the customer will churn, as calculated by the model."
    )

    # Trường HTML để lưu và hiển thị biểu đồ giải thích từ SHAP.
    # Chúng ta sẽ lưu trực tiếp mã HTML của biểu đồ vào đây.
    shap_html = fields.Binary(
        string='Prediction Explanation (SHAP Data)',
        readonly=True
    )

    # Thêm một trường để hiển thị tên khách hàng cho tiện lợi
    # related='customer_id.name' sẽ tự động lấy giá trị từ trường 'name' của model 'res.partner'
    customer_name = fields.Char(
        string="Customer Name",
        related='customer_id.name',
        readonly=True,
        store=True # Lưu vào DB để có thể tìm kiếm/nhóm theo tên
    )
    
    churn_rate = fields.Float(
        string="Churn Rate",
        compute='_compute_churn_rate',
        store=True, # store=True là bắt buộc để có thể group by và tính toán trên view
        group_operator='avg', # Chỉ định cách Odoo tổng hợp trường này
    )    
    
    customer_state_id = fields.Many2one(
        'res.country.state', 
        string='Customer State',
        related='customer_id.state_id',
        store=True, # Bắt buộc phải có store=True để có thể group_by
        readonly=True,
    )
    
    probability_level = fields.Selection(
        [
            ('low', 'Low Risk (0-30%)'),
            ('medium', 'Medium Risk (30-70%)'),
            ('high', 'High Risk (70-100%)')
        ],
        string="Probability Level",
        compute='_compute_probability_level',
        store=True, # Bắt buộc phải có store=True để có thể group_by
    )
    
    is_high_risk = fields.Integer(
        string="Is High Risk",
        compute='_compute_is_high_risk',
        store=True, # Bắt buộc để có thể tính toán trên view
        default=0,
    )

    @api.depends('probability_level')
    def _compute_is_high_risk(self):
        """
        Gán giá trị 1 nếu là 'high', ngược lại là 0.
        Việc tính tổng (sum) của trường này sẽ cho ra số khách hàng nguy cơ cao.
        """
        for record in self:
            if record.probability_level == 'high':
                record.is_high_risk = 1
            else:
                record.is_high_risk = 0

    @api.depends('probability')
    def _compute_probability_level(self):
        """
        Tự động phân loại mức độ rủi ro dựa trên xác suất churn.
        """
        for record in self:
            if record.probability < 30:
                record.probability_level = 'low'
            elif record.probability < 70:
                record.probability_level = 'medium'
            else:
                record.probability_level = 'high'

    @api.depends('prediction_result')
    def _compute_churn_rate(self):
        """
        Trường này trả về 100 nếu là churn, 0 nếu không.
        Khi tính trung bình (avg) trên view, nó sẽ ra đúng tỷ lệ %.
        """
        for record in self:
            if record.prediction_result == 'churn':
                record.churn_rate = 100.0
            else:
                record.churn_rate = 0.0