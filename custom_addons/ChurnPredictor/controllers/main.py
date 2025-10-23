# Thêm import base64 ở đầu file
import base64
from odoo import http
from odoo.http import request
from werkzeug.wrappers import Response

class ShapPlotController(http.Controller):
    # Chúng ta sẽ thêm csp="" VÀ tự tay ghi đè header để đảm bảo 100%
    @http.route('/churn_predictor/shap_plot/<int:prediction_id>', type='http', auth='user', website=False, csrf=False, csp="")
    def show_shap_plot(self, prediction_id, **kw):
        prediction = request.env['churn.prediction'].sudo().browse(prediction_id)
        
        if not prediction.exists() or not prediction.shap_html:
            return Response("SHAP data not found.", status=404)
        
        try:
            # Lấy dữ liệu Base64 từ trường Binary
            base64_bytes = prediction.shap_html
            # Giải mã về lại chuỗi HTML+JS gốc
            final_html = base64.b64decode(base64_bytes).decode('utf-8')

        except Exception as e:
            return Response(f"Failed to decode SHAP data. Error: {e}", status=500)
        
        # Tạo một đối tượng Response với nội dung đã giải mã
        response = Response(final_html, mimetype='text/html')
        
        # === MỆNH LỆNH CUỐI CÙNG ===
        # Dòng này ghi đè lên mọi chính sách bảo mật khác.
        # Nó ra lệnh cho trình duyệt: "Tại trang này, cho phép chạy script từ chính nó
        # VÀ cho phép chạy script được viết trực tiếp trong mã HTML ('unsafe-inline')."
        response.headers['Content-Security-Policy'] = "script-src 'self' 'unsafe-inline'"
        
        return response