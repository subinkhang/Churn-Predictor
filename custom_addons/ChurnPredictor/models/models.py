# -*- coding: utf-8 -*-

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
    shap_html = fields.Html(
        string='Prediction Explanation (SHAP)',
        readonly=True,
        help="The SHAP force plot visualization explaining the prediction."
    )

    # Thêm một trường để hiển thị tên khách hàng cho tiện lợi
    # related='customer_id.name' sẽ tự động lấy giá trị từ trường 'name' của model 'res.partner'
    customer_name = fields.Char(
        string="Customer Name",
        related='customer_id.name',
        readonly=True,
        store=True # Lưu vào DB để có thể tìm kiếm/nhóm theo tên
    )