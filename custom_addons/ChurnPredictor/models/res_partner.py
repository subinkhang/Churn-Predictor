import os
import joblib
import pickle
import pandas as pd
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import shap
import base64
from io import StringIO

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_predict_churn(self):
        """
        Phương thức này được gọi khi người dùng bấm nút "Predict Churn".
        Nó sẽ thực hiện toàn bộ quy trình: tải model, chuẩn bị dữ liệu,
        dự đoán, tính toán SHAP và lưu kết quả.
        """
        _logger.info("Bắt đầu quy trình dự đoán churn cho khách hàng: %s", self.name)

        # --- BƯỚC 1: TẢI MODEL VÀ CÁC "TÀI SẢN" ML ---
        try:
            base_path = os.path.dirname(__file__)
            model_path = os.path.join(base_path, 'ml_assets', 'churn_model.joblib')
            columns_path = os.path.join(base_path, 'ml_assets', 'model_columns.pkl')
            model = joblib.load(model_path)
            with open(columns_path, 'rb') as f:
                model_columns = pickle.load(f)
        except Exception as e:
            _logger.error("Lỗi khi tải model: %s", e)
            raise UserError(_("Đã xảy ra lỗi khi tải các tài sản Machine Learning: %s", str(e)))

        # --- BƯỚC 2: THU THẬP VÀ TẠO FEATURE CHO KHÁCH HÀNG HIỆN TẠI ---
        customer_data = []
        # Giữ lại map giữa customer_id và data row để xử lý sau này
        processed_customers = []
        
        for customer in self:
            orders = self.env['sale.order'].search([
                ('partner_id', '=', customer.id),
                ('state', 'in', ['sale', 'done'])
            ])
            if not orders:
                _logger.warning("Khách hàng %s không có đơn hàng nào, bỏ qua dự đoán.", customer.name)
                continue

            payment_values = orders.mapped('amount_total')
            payment_value_sum = sum(payment_values)
            payment_value_mean = payment_value_sum / len(payment_values) if payment_values else 0
            frequency = len(orders)
            recency = 0  # Cần logic hoàn thiện ở đây
            review_score_mean = 4.5 # Giả định

            raw_data = {
                'payment_value_sum': payment_value_sum,
                'payment_value_mean': payment_value_mean,
                'frequency': frequency,
                'recency': recency,
                'review_score_mean': review_score_mean,
            }
            customer_data.append(raw_data)
            processed_customers.append(customer) # Lưu lại customer đã được xử lý

        if not customer_data:
            raise UserError(_("Không có khách hàng nào hợp lệ để dự đoán."))

        input_df = pd.DataFrame(customer_data)
        
        # --- BƯỚC 3: CHUẨN HÓA DATAFRAME ĐẦU VÀO ---
        final_input_df = pd.DataFrame(columns=model_columns)
        final_input_df = pd.concat([final_input_df, input_df], ignore_index=True)
        final_input_df.fillna(0, inplace=True)
        final_input_df = final_input_df[model_columns]

        # === LOGGING MỚI ĐỂ DEBUG ===
        _logger.info("===== BẮT ĐẦU DEBUG DỮ LIỆU CHO SHAP =====")
        _logger.info("DataFrame Info:\n%s", final_input_df.info())
        _logger.info("DataFrame Head:\n%s", final_input_df.head().to_string())
        _logger.info("==========================================")

        # --- BƯỚC 4: THỰC HIỆN DỰ ĐÓAN ---
        try:
            predictions = model.predict(final_input_df)
            probabilities = model.predict_proba(final_input_df)[:, 1]
        except Exception as e:
            _logger.error("Lỗi khi dự đoán: %s", e)
            raise UserError(_("Đã xảy ra lỗi trong quá trình dự đoán của mô hình: %s", str(e)))

        # === BƯỚC 4.5: TÍNH TOÁN VÀ TẠO BIỂU ĐỒ SHAP === (PHẦN CẬP NHẬT)
        shap_html_outputs = []
        try:
            _logger.info("Bắt đầu tính toán SHAP values.")
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(final_input_df)

            for i in range(len(final_input_df)):
                plot = shap.force_plot(
                    explainer.expected_value,
                    shap_values[i],
                    final_input_df.iloc[i],
                    show=False,
                    matplotlib=False
                )

                # === THAY ĐỔI 2: Dùng StringIO() thay vì io.BytesIO() ===
                # Đây là một "file văn bản" trong bộ nhớ.
                with StringIO() as buffer:
                    shap.save_html(buffer, plot)
                    # getvalue() của StringIO trả về một chuỗi string, không cần decode nữa.
                    html_content = buffer.getvalue()
                
                shap_html_outputs.append(html_content)

            _logger.info("Hoàn thành tính toán và tạo %d biểu đồ SHAP.", len(shap_html_outputs))
            for idx, html_content in enumerate(shap_html_outputs):
                out_path = os.path.join(base_path, f'shap_plot_{idx}.html')
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                _logger.info("SHAP HTML saved to %s", out_path)

        except Exception as e:
            _logger.error("LỖI CHI TIẾT KHI TẠO BIỂU ĐỒ SHAP: %s", repr(e))
            raise UserError(_("Đã xảy ra lỗi trong quá trình tính toán giải thích SHAP. Chi tiết: %s", repr(e)))

        # --- BƯỚC 5: LƯU KẾT QUẢ VÀO ODOO ---
        prediction_model = self.env['churn.prediction']
        records_to_show = self.env['churn.prediction']

        for i, customer in enumerate(processed_customers):
            prediction_value = predictions[i]
            probability_value = probabilities[i] * 100
            
            # Lấy mã HTML của SHAP cho khách hàng tương ứng
            shap_html_content = shap_html_outputs[i]

            # Tạo bản ghi mới
            encoded_shap_html_bytes = base64.b64encode(shap_html_content.encode('utf-8'))

            # Lưu chuỗi ĐÃ ĐƯỢC MÃ HÓA vào database
            new_prediction = prediction_model.create({
                'customer_id': customer.id,
                'prediction_result': 'churn' if prediction_value == 1 else 'no_churn',
                'probability': probability_value,
                'shap_html': encoded_shap_html_bytes, # <<<--- LƯU DỮ LIỆU ĐÃ MÃ HÓA
            })
            records_to_show += new_prediction
            _logger.info(
                "Đã lưu kết quả dự đoán cho khách hàng %s: Result=%s, Probability=%.2f%%",
                customer.name, 'churn' if prediction_value == 1 else 'no_churn', probability_value
            )

        # --- BƯỚC 6: TRẢ VỀ MỘT ACTION ĐỂ HIỂN THỊ KẾT QUẢ ---
        # if len(records_to_show) == 1:
        #     # Nếu chỉ có 1 kết quả, mở thẳng form view
        #     return {
        #         'name': _('Churn Prediction Result'),
        #         'type': 'ir.actions.act_window',
        #         'res_model': 'churn.prediction',
        #         'res_id': records_to_show.id,
        #         'view_mode': 'form',
        #         'target': 'current',
        #     }
        # else:
        #     # Nếu có nhiều kết quả, mở tree view
        #     return {
        #         'name': _('Churn Prediction Results'),
        #         'type': 'ir.actions.act_window',
        #         'res_model': 'churn.prediction',
        #         'view_mode': 'tree,form',
        #         'domain': [('id', 'in', records_to_show.ids)],
        #         'target': 'current',
        #     }
        if not records_to_show:
            return # Không làm gì nếu không có kết quả

        # Thay vì trả về một act_window để mở form view,
        # chúng ta trả về một client action để mở ứng dụng SPA.
        return {
            'name': 'Churn Prediction Result',
            'type': 'ir.actions.client',
            'tag': 'churn_prediction_spa_action_tag', # Tag của SPA chúng ta đã định nghĩa
            'target': 'current',
            'context': {
                # Gửi ID của bản ghi mới tạo đến cho SPA
                'active_id': records_to_show[0].id,
            },
        }
