# custom_addons/ChurnPredictor/models/rating_rating.py

from odoo import models, fields

class RatingRating(models.Model):
    """
    Kế thừa model Rating để thêm các trường cần thiết.
    """
    _inherit = 'rating.rating'

    # Thêm trường để lưu thông tin 'có bình luận hay không'
    x_has_review_text = fields.Boolean(string="Has Review Text", readonly=True)