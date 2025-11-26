# custom_addons/ChurnPredictor/models/sale_order.py

from odoo import models, fields

class SaleOrder(models.Model):
    """
    Kế thừa model Sale Order để thêm các trường cần thiết cho việc import
    và phân tích dữ liệu lịch sử.
    """
    _inherit = 'sale.order'

    # Thêm trường để lưu order_id gốc từ dataset Kaggle
    x_kaggle_id = fields.Char(string="Kaggle Order ID", index=True, readonly=True)

    # Thêm trường để lưu nhãn churn lịch sử (đã được tính trong notebook)
    x_churn_label = fields.Integer(string="Historical Churn Label", readonly=True)