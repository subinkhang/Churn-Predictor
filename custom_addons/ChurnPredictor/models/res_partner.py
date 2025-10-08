# -*- coding: utf-8 -*-

import os
import joblib
import pickle
import pandas as pd
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_predict_churn(self):
        """
        Phương thức này được gọi khi người dùng bấm nút "Predict Churn".
        Nó sẽ thực hiện toàn bộ quy trình: tải model, chuẩn bị dữ liệu,
        dự đoán và lưu kết quả.
        """
        _logger.info("Bắt đầu quy trình dự đoán churn cho khách hàng: %s", self.name)

        # --- BƯỚC 1: TẢI MODEL VÀ CÁC "TÀI SẢN" ML ---
        try:
            # Xác định đường dẫn tuyệt đối đến các file ML bên trong module Odoo
            # __file__ là đường dẫn của file Python hiện tại (res_partner.py)
            # os.path.dirname(__file__) sẽ trỏ đến thư mục 'models'
            base_path = os.path.dirname(__file__)
            model_path = os.path.join(base_path, 'ml_assets', 'churn_model.joblib')
            columns_path = os.path.join(base_path, 'ml_assets', 'model_columns.pkl')

            # Tải mô hình đã huấn luyện
            model = joblib.load(model_path)
            _logger.info("Tải thành công model từ: %s", model_path)

            # Tải danh sách các cột mà mô hình đã được huấn luyện trên đó
            with open(columns_path, 'rb') as f:
                model_columns = pickle.load(f)
            _logger.info("Tải thành công %d cột model từ: %s", len(model_columns), columns_path)

        except FileNotFoundError as e:
            _logger.error("Lỗi không tìm thấy file model: %s", e)
            raise UserError(_("Không thể tìm thấy file model hoặc file cột. Vui lòng kiểm tra lại đường dẫn trong module."))
        except Exception as e:
            _logger.error("Lỗi khi tải model: %s", e)
            raise UserError(_("Đã xảy ra lỗi khi tải các tài sản Machine Learning: %s", str(e)))

        # --- BƯỚC 2: THU THẬP VÀ TẠO FEATURE CHO KHÁCH HÀNG HIỆN TẠI ---
        # self ở đây là bản ghi (record) của khách hàng đang được xem (ví dụ: một khách hàng cụ thể)
        customer_data = []
        for customer in self: # Vòng lặp này để xử lý nếu người dùng chọn nhiều khách hàng trong list view
            # Lấy các đơn hàng đã bán (sale.order) của khách hàng này
            # Chúng ta chỉ lấy các đơn đã xác nhận (state in ['sale', 'done'])
            orders = self.env['sale.order'].search([
                ('partner_id', '=', customer.id),
                ('state', 'in', ['sale', 'done'])
            ])

            if not orders:
                _logger.warning("Khách hàng %s không có đơn hàng nào, bỏ qua dự đoán.", customer.name)
                continue

            # **TÁI TẠO FEATURE ENGINEERING (PHIÊN BẢN ĐƠN GIẢN)**
            # Đây là lúc bạn sẽ tái tạo lại các bước đã làm trong Colab.
            # Ví dụ này sẽ tạo các feature cơ bản. Bạn cần mở rộng nó để khớp với notebook của mình.

            # Đặc trưng Monetary
            payment_values = orders.mapped('amount_total')
            payment_value_sum = sum(payment_values)
            payment_value_mean = payment_value_sum / len(payment_values) if payment_values else 0
            
            # Đặc trưng Frequency (Tần suất)
            frequency = len(orders)

            # Đặc trưng Recency (Lần mua cuối) - cần tính toán phức tạp hơn, tạm thời để là 0
            recency = 0 # Bạn cần logic để tính toán recency ở đây

            # Đặc trưng về hành vi (ví dụ: điểm review trung bình)
            # Giả sử bạn có một model để lưu review, ở đây ta dùng giá trị giả định
            review_score_mean = 4.5 
            
            # Tạo một dictionary chứa dữ liệu thô
            raw_data = {
                'payment_value_sum': payment_value_sum,
                'payment_value_mean': payment_value_mean,
                'frequency': frequency,
                'recency': recency,
                'review_score_mean': review_score_mean,
                # Thêm các đặc trưng khác bạn đã dùng trong Colab ở đây...
                # Ví dụ: 'customer_state_last_SP': 1 nếu state là SP, 0 nếu không.
                # 'product_category_name_english_last_...': ...
            }
            customer_data.append(raw_data)

        if not customer_data:
            raise UserError(_("Không có khách hàng nào hợp lệ để dự đoán."))

        # Chuyển dữ liệu thô thành DataFrame của Pandas
        input_df = pd.DataFrame(customer_data)
        _logger.info("DataFrame đầu vào thô:\n%s", input_df.head())

        # --- BƯỚC 3: CHUẨN HÓA DATAFRAME ĐẦU VÀO ---
        # Đảm bảo DataFrame đầu vào có chính xác các cột và đúng thứ tự như khi huấn luyện model
        # Tạo một DataFrame rỗng với các cột của model
        final_input_df = pd.DataFrame(columns=model_columns)
        
        # Điền dữ liệu từ input_df vào final_input_df
        # Các cột có trong input_df sẽ được giữ lại, các cột không có sẽ là NaN
        final_input_df = pd.concat([final_input_df, input_df], ignore_index=True)
        
        # Điền các giá trị thiếu (NaN) bằng 0. 
        # Đây là một giả định quan trọng, có nghĩa là nếu một đặc trưng (ví dụ: một one-hot column)
        # không được tạo ra cho khách hàng này, giá trị của nó sẽ là 0.
        final_input_df.fillna(0, inplace=True)
        
        # Chỉ giữ lại các cột mà model đã biết
        final_input_df = final_input_df[model_columns]
        
        _logger.info("DataFrame đầu vào cuối cùng cho model:\n%s", final_input_df.head())

        # --- BƯỚC 4: THỰC HIỆN DỰ ĐOÁN ---
        try:
            predictions = model.predict(final_input_df)
            probabilities = model.predict_proba(final_input_df)[:, 1] # Lấy xác suất của lớp 'churn' (lớp 1)
        except Exception as e:
            _logger.error("Lỗi khi dự đoán: %s", e)
            raise UserError(_("Đã xảy ra lỗi trong quá trình dự đoán của mô hình: %s", str(e)))

        # --- BƯỚC 5: LƯU KẾT QUẢ VÀO ODOO ---
        prediction_model = self.env['churn.prediction']
        for i, customer in enumerate(self):
            if customer.id not in [order.partner_id.id for order in orders]:
                continue # Bỏ qua nếu khách hàng không có trong danh sách xử lý

            prediction_value = predictions[i]
            probability_value = probabilities[i] * 100 # Chuyển sang phần trăm

            # Tạo bản ghi mới trong model churn.prediction
            prediction_model.create({
                'customer_id': customer.id,
                'prediction_result': 'churn' if prediction_value == 1 else 'no_churn',
                'probability': probability_value,
                # Tạm thời để trống SHAP, sẽ làm ở bước sau
                'shap_html': '<p>SHAP explanation will be generated here.</p>',
            })
            _logger.info(
                "Đã lưu kết quả dự đoán cho khách hàng %s: Result=%s, Probability=%.2f%%",
                customer.name, 'churn' if prediction_value == 1 else 'no_churn', probability_value
            )

        # --- BƯỚC 6: TRẢ VỀ MỘT ACTION ĐỂ HIỂN THỊ KẾT QUẢ (TÙY CHỌN NHƯNG RẤT HAY) ---
        # Action này sẽ tự động mở danh sách các kết quả dự đoán vừa được tạo.
        return {
            'name': _('Churn Prediction Results'),
            'type': 'ir.actions.act_window',
            'res_model': 'churn.prediction',
            'view_mode': 'tree,form',
            'domain': [('customer_id', 'in', self.ids)], # Chỉ hiển thị kết quả cho các khách hàng đã chọn
            'target': 'current',
        }