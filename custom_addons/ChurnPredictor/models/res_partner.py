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
from datetime import timedelta
import re

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    prediction_count = fields.Integer(compute='_compute_prediction_count')
    
    account_type = fields.Selection(
        [
            ('buyer', 'Buyer'),
            ('supplier', 'Supplier')
        ],
        string='Account Type',
        default='buyer',
        help="Phân loại khách hàng là người mua hay nhà cung cấp."
    )

    def action_predict_churn(self):
        """
        Phương thức này được gọi khi người dùng bấm nút "Predict Churn".
        Nó sẽ thực hiện toàn bộ quy trình: tải model, chuẩn bị dữ liệu,
        dự đoán, tính toán SHAP và lưu kết quả.
        """
        _logger.info("Bắt đầu quy trình dự đoán churn cho khách hàng: %s", self.mapped('name'))

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
        processed_customers = []
        
        for customer in self:
            orders = self.env['sale.order'].search([
                ('partner_id', '=', customer.id),
                ('state', 'in', ['sale', 'done'])
            ], order='date_order asc')
            
            if not orders:
                _logger.warning("Khách hàng %s không có đơn hàng nào, bỏ qua dự đoán.", customer.name)
                continue

            # Truy vấn các bản ghi liên quan
            order_lines = orders.mapped('order_line')
            reviews = self.env['rating.rating'].search([('res_model', '=', 'sale.order'), ('res_id', 'in', orders.ids), ('rating', '!=', 0)])
            pickings = orders.mapped('picking_ids').filtered(lambda p: p.state == 'done')
            last_order = orders[-1]

            # Tính toán các feature
            payment_values = orders.mapped('amount_total')
            payment_value_sum = sum(payment_values)
            payment_value_mean = payment_value_sum / len(payment_values) if payment_values else 0
            payment_value_max = max(payment_values) if payment_values else 0
            frequency = len(orders)
            recency = (fields.Datetime.now() - last_order.date_order).days
            num_items_sum = sum(order_lines.mapped('product_uom_qty'))
            
            review_scores = reviews.mapped('rating')
            review_score_mean = sum(review_scores) / len(review_scores) if review_scores else 0
            review_score_min = min(review_scores) if review_scores else 0

            delivery_delays = []
            delivery_days_list = []
            for pick in pickings:
                if pick.sale_id.date_order and pick.date_done:
                    days = (pick.date_done - pick.sale_id.date_order).total_seconds() / (24 * 3600)
                    delivery_days_list.append(days)
                if pick.scheduled_date and pick.date_done:
                    delay = (pick.date_done - pick.scheduled_date).total_seconds() / (24 * 3600)
                    delivery_delays.append(max(0, delay))
            
            delivery_days_mean = sum(delivery_days_list) / len(delivery_days_list) if delivery_days_list else 0
            delivery_delay_days_mean = sum(delivery_delays) / len(delivery_delays) if delivery_delays else 0

            # Xử lý feature phân loại
            payment_type_last = last_order.transaction_ids and last_order.transaction_ids[0].provider_id.code or ''
            customer_state_last = customer.state_id.code or ''
            category_name_last = ''
            if last_order.order_line:
                category = last_order.order_line[0].product_id.categ_id
                if category:
                    leaf_category_name = category.display_name.split(' / ')[-1].strip()
                    category_name_last = re.sub(r'\\s+', '_', leaf_category_name).lower()
            
            raw_data = {
                'payment_value_sum': payment_value_sum, 'payment_value_mean': payment_value_mean, 'payment_value_max': payment_value_max,
                'frequency': frequency, 'recency': recency,
                'review_score_mean': review_score_mean, 'review_score_min': review_score_min,
                'delivery_days_mean': delivery_days_mean, 'delivery_delay_days_mean': delivery_delay_days_mean,
                'num_items_sum': num_items_sum,
                'payment_type_last': payment_type_last, 'customer_state_last': customer_state_last,
                'product_category_name_english_last': category_name_last,
            }
            customer_data.append(raw_data)
            processed_customers.append(customer)

        if not customer_data:
            raise UserError(_("Không có khách hàng nào hợp lệ để dự đoán."))

        # --- BƯỚC 3: TẠO VÀ XỬ LÝ DATAFRAME ---
        input_df = pd.DataFrame(customer_data)
        
        # 3.1: Ép kiểu các cột số để đảm bảo đúng định dạng
        numeric_cols_to_force = [
            'payment_value_sum', 'payment_value_mean', 'payment_value_max',
            'frequency', 'recency', 'review_score_mean', 'review_score_min',
            'delivery_days_mean', 'delivery_delay_days_mean',
            'num_items_sum'
        ]
        for col in numeric_cols_to_force:
            if col in input_df.columns:
                input_df[col] = pd.to_numeric(input_df[col], errors='coerce').fillna(0)
        
        # 3.2: One-Hot Encoding
        categorical_feature_prefixes = ['payment_type_last', 'customer_state_last', 'product_category_name_english_last']
        cols_to_encode = [prefix for prefix in categorical_feature_prefixes if prefix in input_df.columns]
        if cols_to_encode:
            input_df_encoded = pd.get_dummies(input_df, columns=cols_to_encode, prefix=cols_to_encode, dtype=float)
        else:
            input_df_encoded = input_df
            
        # 3.3: Căn chỉnh DataFrame để khớp với mô hình
        final_input_df = pd.DataFrame(columns=model_columns)
        final_input_df = pd.concat([final_input_df, input_df_encoded], ignore_index=True)
        final_input_df.fillna(0, inplace=True)
        # Ép kiểu toàn bộ sang float để đảm bảo
        final_input_df = final_input_df.astype(float) 
        final_input_df = final_input_df[model_columns]

        _logger.info("DataFrame cuối cùng trước khi dự đoán (shape: %s):\n%s", final_input_df.shape, final_input_df.head().to_string())

        # --- BƯỚC 4 & 5: DỰ ĐOÁN, SHAP, LƯU KẾT QUẢ ---
        try:
            predictions = model.predict(final_input_df)
            probabilities = model.predict_proba(final_input_df)[:, 1]
        except Exception as e:
            _logger.error("Lỗi khi dự đoán: %s", e, exc_info=True)
            _logger.error("Dtypes của final_input_df ngay trước khi lỗi:\n%s", final_input_df.dtypes)
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
            
        # 1. Tạo một thông báo thành công
        if records_to_show:
            message = f"Successfully created {len(records_to_show)} prediction(s)."
        else:
            message = "No valid orders found for this customer to make a prediction."

        _logger.info(">>>>> CHUẨN BỊ TRẢ VỀ THÔNG BÁO: %s <<<<<", message)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': { 'title': 'Churn Prediction', 'message': message, 'type': 'success', 'sticky': False }
        }

    def _compute_prediction_count(self):
        for partner in self:
            partner.prediction_count = self.env['churn.prediction'].search_count(
                [('customer_id', '=', partner.id)]
            )

    # === THÊM PHƯƠNG THỨC ACTION CHO NÚT BẤM ===
    def action_view_churn_predictions(self):
        self.ensure_one()
        return {
            'name': 'Churn Predictions',
            'type': 'ir.actions.act_window',
            'res_model': 'churn.prediction',
            'view_mode': 'tree,graph,pivot',
            'domain': [('customer_id', '=', self.id)],
        }
        
    def action_view_customer_dashboard(self):
        """
        Trả về một client action để mở dashboard OWL chi tiết cho khách hàng này.
        """
        self.ensure_one()
        # Trả về một dictionary định nghĩa client action
        return {
            'type': 'ir.actions.client',
            # 'tag' phải khớp với tag đã đăng ký trong file customer_dashboard.js
            'tag': 'churn_predictor.customer_dashboard',
            'name': _('Churn Detail: %s', self.name),
            # 'context' được dùng để truyền ID của khách hàng hiện tại
            # vào component OWL thông qua props.action.context
            'context': {'active_id': self.id},
        }
        
        
    @api.model
    def _cron_predict_churn(self):
        _logger.info("===== BẮT ĐẦU CRON JOB DỰ ĐOÁN CHURN HÀNG NGÀY =====")
        start_time = fields.Datetime.now()
        
        customers_processed_count = 0
        high_risk_predictions_list = []

        # 1. Tìm các khách hàng mục tiêu
        time_threshold = start_time - timedelta(hours=24)
        recent_orders = self.env['sale.order'].search([
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', time_threshold),
        ])
        customers_to_predict = recent_orders.mapped('partner_id')
        customers_processed_count = len(customers_to_predict)

        if not customers_to_predict:
            _logger.info("Không tìm thấy khách hàng nào có đơn hàng mới trong 24h qua.")
        else:
            _logger.info(f"Tìm thấy {customers_processed_count} khách hàng cần dự đoán: {[p.name for p in customers_to_predict]}")
            # 2. Gọi logic dự đoán
            try:
                customers_to_predict.action_predict_churn()
                _logger.info("Hoàn thành việc tạo dự đoán cho các khách hàng mục tiêu.")
            except Exception as e:
                _logger.error(f"Lỗi xảy ra trong quá trình dự đoán của cron job: {e}", exc_info=True)
            
            # 3. Tạo cảnh báo và thu thập thông tin khách hàng nguy cơ cao
            prediction_threshold = start_time - timedelta(minutes=1)
            high_risk_predictions = self.env['churn.prediction'].search([
                ('create_date', '>=', prediction_threshold), ('is_high_risk', '=', 1),
                ('customer_id', 'in', customers_to_predict.ids)
            ])
            high_risk_predictions_list = high_risk_predictions

            if high_risk_predictions:
                _logger.info(f"Phát hiện {len(high_risk_predictions)} khách hàng nguy cơ cao. Bắt đầu tạo cảnh báo Activity.")
                activity_type_todo_id = self.env.ref('mail.mail_activity_data_todo').id
                for pred in high_risk_predictions:
                    customer = pred.customer_id
                    if customer.user_id:
                        self.env['mail.activity'].create({
                            'res_id': customer.id, 'res_model_id': self.env.ref('base.model_res_partner').id,
                            'activity_type_id': activity_type_todo_id, 'summary': 'Nguy cơ Churn cao!',
                            'note': f"<p>Khách hàng <a href='/web#id={customer.id}&model=res.partner&view_type=form' style='font-weight:bold;'>{customer.name}</a> "
                                    f"được dự đoán có nguy cơ churn cao với xác suất là <strong>{pred.probability:.2f}%</strong>.</p>"
                                    f"<p>Vui lòng liên hệ và chăm sóc khách hàng này ngay.</p>",
                            'user_id': customer.user_id.id,
                        })
        # ==============================================================================
        # === PHẦN 4 ĐÃ ĐƯỢC SỬA LỖI DỨT ĐIỂM: RENDER THỦ CÔNG ===
        # ==============================================================================
        try:
            _logger.info("Chuẩn bị gửi email báo cáo tóm tắt.")
            recipient_email = self.env['ir.config_parameter'].sudo().get_param('churn_predictor.recipient_email')
            
            if not recipient_email:
                _logger.warning("Chưa cấu hình email người nhận (churn_predictor.recipient_email). Sẽ không gửi email báo cáo.")
                return

            template = self.env.ref('ChurnPredictor.email_template_churn_cron_summary')
            
            high_risk_details_for_email = [{
                'id': pred.customer_id.id, 'name': pred.customer_id.name,
                'probability': pred.probability,
                'salesperson': pred.customer_id.user_id.name if pred.customer_id.user_id else None
            } for pred in high_risk_predictions_list]
            
            # Lấy chuỗi tên các khách hàng đã xử lý
            processed_customer_names_str = ', '.join(customers_to_predict.mapped('name'))

            # === XÂY DỰNG CHUỖI HTML HOÀN CHỈNH TRONG PYTHON ===
            
            # 1. Xây dựng bảng chi tiết khách hàng nguy cơ cao
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            high_risk_table_html = ''
            if high_risk_details_for_email:
                table_rows = []
                for customer in high_risk_details_for_email:
                    # Link đến form xem chi tiết khách hàng
                    customer_form_url = f"{base_url}/web?#id={customer.get('id')}&model=res.partner&view_type=form"
                    # Link đến dashboard chi tiết của khách hàng
                    customer_dashboard_url = f"{base_url}/web?#action=churn_predictor.customer_dashboard&amp;active_id={customer.get('id')}&amp;cids=1"
                    
                    row = f"""
                        <tr>
                            <td style="padding: 8px;">
                                <a href="{customer_form_url}">{customer.get('name')}</a>
                            </td>
                            <td style="padding: 8px; text-align: center;">{customer.get('probability'):.2f} %</td>
                            <td style="padding: 8px;">{customer.get('salesperson') or 'N/A'}</td>
                            <td style="padding: 8px; text-align: center;">
                                <a href="{customer_dashboard_url}" style="color: #0d6efd; text-decoration: underline;">View Dashboard</a>
                            </td>
                        </tr>
                    """
                    table_rows.append(row)

                high_risk_table_html = f"""
                    <h3 style="margin-top: 20px;">Chi tiết các khách hàng có nguy cơ cao:</h3>
                    <table border="1" style="border-collapse: collapse; width: 100%;">
                        <thead style="background-color: #f2f2f2;">
                            <tr>
                                <th style="padding: 8px;">Tên Khách Hàng</th>
                                <th style="padding: 8px;">Xác suất Churn (%)</th>
                                <th style="padding: 8px;">Nhân viên phụ trách</th>
                                <th style="padding: 8px;">Hành động</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(table_rows)}
                        </tbody>
                    </table>
                """
            
            # 2. Xây dựng button dashboard tổng quan
            overview_dashboard_url = f"{base_url}/web?#action=970&amp;cids=1&amp;menu_id=740"
            overview_button_html = f"""
                <div style="text-align: center; margin-top: 30px; margin-bottom: 30px;">
                    <a href="{overview_dashboard_url}" 
                       style="background-color: #0d6efd; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-size: 16px; font-weight: bold;">
                        View Overview Dashboard
                    </a>
                </div>
            """
            
            # Cập nhật context
            render_context = {
                'start_time': start_time,
                'end_time': fields.Datetime.now(),
                'customers_processed': customers_processed_count,
                'high_risk_found': len(high_risk_predictions_list),
                'processed_customer_names': processed_customer_names_str,
                'high_risk_table_html': high_risk_table_html,
                'overview_button_html': overview_button_html,
            }
            
            # Lấy ID của một đối tượng partner bất kỳ để làm tham chiếu render
            res_id = self.env.user.partner_id.id or self.env.ref('base.main_partner').id
            
            # Sử dụng phương thức _render_template để render thủ công
            rendered_subject = template.with_context(**render_context)._render_template(template.subject, 'res.partner', [res_id])[res_id]
            rendered_body = template.with_context(**render_context)._render_template(template.body_html, 'res.partner', [res_id])[res_id]

            # Xây dựng dictionary giá trị cho email
            mail_values = {
                'subject': rendered_subject,
                'body_html': rendered_body,
                'email_to': recipient_email,
                'email_from': template.email_from,
                'author_id': self.env.user.partner_id.id,
                'auto_delete': True, # Tự động xóa email khỏi hàng đợi sau khi gửi
            }
            
            # Tạo và gửi email ngay lập tức
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
            
            _logger.info(f"Đã gửi thành công email báo cáo tóm tắt đến {recipient_email}.")

        except Exception as e:
            _logger.error(f"Lỗi khi gửi email báo cáo cron job: {e}", exc_info=True)
        finally:
            _logger.info("===== KẾT THÚC CRON JOB DỰ ĐOÁN CHURN HÀNG NGÀY =====")