# custom_addons/ChurnPredictor/models/product_template.py

from odoo import models, fields

class ProductTemplate(models.Model):
    """
    Kế thừa model Product Template để thêm trường tham chiếu.
    """
    _inherit = 'product.template'

    # Thêm trường để lưu product_id từ dataset Kaggle
    x_kaggle_id = fields.Char(string="Kaggle Product ID", index=True, readonly=True)