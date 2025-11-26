from calendar import month_abbr
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
from dateutil.relativedelta import relativedelta
import json

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
    
    x_churn_risk_level = fields.Selection(
        [
            ('low', 'Low Risk'),
            ('medium', 'Medium Risk'),
            ('high', 'High Risk'),
        ],
        string="Churn Risk Level",
        default=False, # Không có giá trị mặc định khi mới tạo
        index=True, # Thêm index để truy vấn nhanh hơn
        help="The latest churn risk assessment for this customer."
    )
    
    x_unique_id = fields.Char(string="Unique Customer ID", index=True, readonly=True)

    # 1. NHÓM THANH TOÁN (PAYMENT)
    x_feat_payment_value_sum = fields.Float(string="Feat: Payment Value Sum", default=0.0)
    x_feat_payment_value_mean = fields.Float(string="Feat: Payment Value Mean", default=0.0)
    x_feat_payment_value_max = fields.Float(string="Feat: Payment Value Max", default=0.0)
    x_feat_payment_value_min = fields.Float(string="Feat: Payment Value Min", default=0.0)
    
    # 2. NHÓM GIAO HÀNG (DELIVERY)
    x_feat_delivery_days_mean = fields.Float(string="Feat: Delivery Days Mean", default=0.0)
    x_feat_delivery_days_max = fields.Float(string="Feat: Delivery Days Max", default=0.0)
    x_feat_delivery_delay_days_mean = fields.Float(string="Feat: Delivery Delay Mean", default=0.0)
    x_feat_delivery_delay_days_max = fields.Float(string="Feat: Delivery Delay Max", default=0.0)
    
    # 3. NHÓM ĐÁNH GIÁ (REVIEW)
    x_feat_review_score_mean = fields.Float(string="Feat: Review Score Mean", default=0.0)
    x_feat_review_score_min = fields.Float(string="Feat: Review Score Min", default=0.0)
    x_feat_review_score_std = fields.Float(string="Feat: Review Score Std", default=0.0)
    
    # 4. NHÓM SẢN PHẨM & TẦN SUẤT (ITEMS & RFM)
    x_feat_num_items_sum = fields.Float(string="Feat: Num Items Sum", default=0.0)
    x_feat_num_items_mean = fields.Float(string="Feat: Num Items Mean", default=0.0)
    x_feat_frequency = fields.Integer(string="Feat: Frequency", default=0)
    x_feat_recency = fields.Integer(string="Feat: Recency (Days)", default=0)
    
    # 5. NHÓM PHÂN LOẠI (CATEGORICAL - RAW VALUE)
    # Chiến thuật: Thay vì tạo 100 trường One-Hot (như x_feat_state_SP, x_feat_state_RJ...)
    # Ta chỉ cần lưu GIÁ TRỊ GỐC. Code Python khi chạy predict sẽ tự động One-Hot Encoding nó.
    # Điều này giúp bạn import CSV dễ hơn rất nhiều (chỉ cần map cột text vào đây).
    
    x_feat_payment_type_last = fields.Char(string="Feat: Last Payment Type", help="Ví dụ: credit_card, boleto...")
    x_feat_customer_state_last = fields.Char(string="Feat: Last Customer State", help="Ví dụ: SP, RJ, MG...")
    x_feat_product_category_name_english_last = fields.Char(string="Feat: Last Product Category", help="Ví dụ: health_beauty...")

    # 6. CỜ ĐÁNH DẤU (FLAG)
    # Dùng để code biết nên lấy dữ liệu từ các trường x_feat_ này hay tự tính toán
    x_is_imported_data = fields.Boolean(string="Is Imported Data", default=False)

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
            
            if customer.x_is_imported_data:
                _logger.info(f"Khách hàng {customer.name} dùng dữ liệu IMPORT (Feature Store)")
                
                # Lấy trực tiếp từ các trường x_feat_
                raw_data = {
                    # 1. Payment
                    'payment_value_sum': customer.x_feat_payment_value_sum,
                    'payment_value_mean': customer.x_feat_payment_value_mean,
                    'payment_value_max': customer.x_feat_payment_value_max,
                    'payment_value_min': customer.x_feat_payment_value_min, # <--- Đã thêm
                    
                    # 2. RFM
                    'frequency': customer.x_feat_frequency,
                    'recency': customer.x_feat_recency,
                    
                    # 3. Review
                    'review_score_mean': customer.x_feat_review_score_mean,
                    'review_score_min': customer.x_feat_review_score_min,
                    'review_score_std': customer.x_feat_review_score_std, # <--- Đã thêm
                    
                    # 4. Delivery (QUAN TRỌNG: Khắc phục lỗi 0.00)
                    'delivery_days_mean': customer.x_feat_delivery_days_mean,
                    'delivery_days_max': customer.x_feat_delivery_days_max, # <--- Đã thêm
                    'delivery_delay_days_mean': customer.x_feat_delivery_delay_days_mean,
                    'delivery_delay_days_max': customer.x_feat_delivery_delay_days_max, # <--- Đã thêm
                    
                    # 5. Items
                    'num_items_sum': customer.x_feat_num_items_sum,
                    'num_items_mean': customer.x_feat_num_items_mean, # <--- Đã thêm
                    
                    # 6. Categorical (Lấy giá trị chữ thô)
                    'payment_type_last': customer.x_feat_payment_type_last or '',
                    'customer_state_last': customer.x_feat_customer_state_last or '',
                    'product_category_name_english_last': customer.x_feat_product_category_name_english_last or '',
                }
            else:
                _logger.info(f"Khách hàng {customer.name} dùng dữ liệu TỰ TÍNH TOÁN (Real-time)")
                
                # Dùng các biến đã tính toán phía trên (logic cũ)
                raw_data = {
                    'payment_value_sum': payment_value_sum, 
                    'payment_value_mean': payment_value_mean, 
                    'payment_value_max': payment_value_max,
                    'frequency': frequency, 
                    'recency': recency,
                    'review_score_mean': review_score_mean, 
                    'review_score_min': review_score_min,
                    'delivery_days_mean': delivery_days_mean, 
                    'delivery_delay_days_mean': delivery_delay_days_mean,
                    'num_items_sum': num_items_sum,
                    'payment_type_last': payment_type_last, 
                    'customer_state_last': customer_state_last,
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

        # === BƯỚC 4.5: TÍNH TOÁN VÀ TẠO BIỂU ĐỒ SHAP ===
        shap_html_outputs = []
        # <<< CẬP NHẬT: Tạo list để chứa dữ liệu JSON >>>
        shap_json_outputs = []
        try:
            _logger.info("Bắt đầu tính toán SHAP values.")
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(final_input_df)
            
            # <<< CẬP NHẬT: Lấy tên các feature một lần >>>
            feature_names = final_input_df.columns.tolist()

            for i in range(len(final_input_df)):
                # --- Phần tạo biểu đồ HTML (giữ nguyên) ---
                plot = shap.force_plot(
                    explainer.expected_value,
                    shap_values[i],
                    final_input_df.iloc[i],
                    show=False,
                    matplotlib=False
                )
                with StringIO() as buffer:
                    shap.save_html(buffer, plot)
                    html_content = buffer.getvalue()
                shap_html_outputs.append(html_content)
                
                # --- <<< CẬP NHẬT: Trích xuất và lưu dữ liệu SHAP thô >>> ---
                shap_raw_data = {
                    "base_value": float(explainer.expected_value),
                    "shap_values": shap_values[i].tolist(),
                    "feature_names": feature_names,
                    "feature_values": final_input_df.iloc[i].tolist(),
                }
                # Chuyển đổi dictionary thành chuỗi JSON và thêm vào list
                shap_json_outputs.append(json.dumps(shap_raw_data))
                # ----------------------------------------------------------------

            _logger.info("Hoàn thành tính toán và tạo %d biểu đồ SHAP và %d bản ghi dữ liệu JSON.", len(shap_html_outputs), len(shap_json_outputs))

        except Exception as e:
            _logger.error("LỖI CHI TIẾT KHI TẠO BIỂU ĐỒ/DỮ LIỆU SHAP: %s", repr(e))
            raise UserError(_("Đã xảy ra lỗi trong quá trình tính toán giải thích SHAP. Chi tiết: %s", repr(e)))

        # --- BƯỚC 5: LƯU KẾT QUẢ VÀO ODOO ---
        prediction_model = self.env['churn.prediction']
        records_to_show = self.env['churn.prediction']

        for i, customer in enumerate(processed_customers):
            prediction_value = predictions[i]
            probability_value = probabilities[i] * 100
            
            shap_html_content = shap_html_outputs[i]
            shap_data_json_string = shap_json_outputs[i]

            _logger.info("--- [DEBUG] KIỂM TRA DỮ LIỆU TRƯỚC KHI GỌI .create() ---")
            _logger.info("Customer: %s", customer.name)
            _logger.info("Kiểu dữ liệu của biến shap_data_json_string: %s", type(shap_data_json_string))
            _logger.info("Độ dài chuỗi JSON: %d", len(shap_data_json_string) if isinstance(shap_data_json_string, str) else 0)
            
            # In ra 1000 ký tự đầu tiên để kiểm tra cấu trúc mà không làm ngập log
            _logger.info("Nội dung 1000 ký tự đầu của JSON string: \n%s", (shap_data_json_string[:1000] if isinstance(shap_data_json_string, str) else "Dữ liệu không phải chuỗi"))
            # ---------------------------------

            encoded_shap_html_bytes = base64.b64encode(shap_html_content.encode('utf-8'))

            # Lưu chuỗi ĐÃ ĐƯỢC MÃ HÓA vào database
            new_prediction = prediction_model.create({
                'customer_id': customer.id,
                'prediction_result': 'churn' if prediction_value == 1 else 'no_churn',
                'probability': probability_value,
                'shap_html': encoded_shap_html_bytes, # <<<--- LƯU DỮ LIỆU ĐÃ MÃ HÓA
                'shap_data_json': shap_data_json_string,
            })
            
            customer.write({
                'x_churn_risk_level': new_prediction.probability_level
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
        
    def write(self, vals):
        old_risk_levels = {
            partner: partner.x_churn_risk_level for partner in self
        }
        res = super(ResPartner, self).write(vals)

        if 'x_churn_risk_level' in vals:
            _logger.info("Phát hiện thay đổi trạng thái Churn Risk. Bắt đầu kiểm tra...")
            for partner in self:
                old_level = old_risk_levels.get(partner)
                new_level = partner.x_churn_risk_level
                
                if new_level == 'high' and old_level != 'high':
                # if new_level == 'high':
                    _logger.warning(
                        "!!! CẢNH BÁO: Khách hàng '%s' (ID: %d) vừa chuyển sang trạng thái NGUY CƠ CAO.",
                        partner.name, partner.id
                    )
                    
                    # === GỌI LOGIC GỬI EMAIL TỪ ĐÂY ===
                    try:
                        partner._send_high_risk_alert_email()
                    except Exception as e:
                        _logger.error(
                            "Lỗi khi gửi email cảnh báo nguy cơ cao cho khách hàng %s: %s",
                            partner.name, e
                        )
        return res

    def _send_high_risk_alert_email(self):
        """
        Phương thức được cập nhật để xây dựng HTML trong code và gửi đi,
        dựa trên kiến trúc mới.
        """
        self.ensure_one()

        if not self.user_id or not self.user_id.email:
            _logger.info("Bỏ qua gửi email cho KH '%s' vì không có Salesperson hoặc email.", self.name)
            return

        _logger.info("Chuẩn bị gửi email cảnh báo nguy cơ cao cho Salesperson của KH '%s'.", self.name)
        
        template = self.env.ref('ChurnPredictor.email_template_high_risk_alert')
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        # --- Xây dựng các chuỗi HTML trong Python ---
        
        # 1. Chi tiết thông tin khách hàng
        customer_details_html = f"""
            <div style="border: 1px solid #ccc; padding: 15px; margin: 15px 0; background-color: #f9f9f9;">
                <strong>Tên khách hàng:</strong> {self.name} <br/>
                <strong>Email:</strong> {self.email or 'N/A'} <br/>
                <strong>Số điện thoại:</strong> {self.phone or 'N/A'} <br/>
                <strong>Nhân viên phụ trách:</strong> {self.user_id.name or 'Chưa có'}
            </div>
        """
        
        # 2. Nút bấm hành động (link đến form khách hàng)
        customer_form_url = f"{base_url}/web#id={self.id}&model=res.partner&view_type=form"
        action_button_html = f"""
            <div style="text-align: center; margin: 20px 0;">
                <a href="{customer_form_url}"
                   style="display: inline-block; padding: 10px 20px; background-color: #d9534f; color: #fff; text-decoration: none; border-radius: 5px;">
                    Xem chi tiết Khách hàng
                </a>
            </div>
        """
        
        # --- Chuẩn bị context để render template ---
        render_context = {
            'recipient_email': self.user_id.email,
            'salesperson_name': self.user_id.name,
            'customer_details_html': customer_details_html,
            'action_button_html': action_button_html,
        }

        # Render và gửi email (sử dụng phương thức render thủ công đáng tin cậy)
        rendered_subject = template.with_context(**render_context)._render_template(template.subject, 'res.partner', [self.id])[self.id]
        rendered_body = template.with_context(**render_context)._render_template(template.body_html, 'res.partner', [self.id])[self.id]

        mail_values = {
            'subject': rendered_subject,
            'body_html': rendered_body,
            'email_to': self.user_id.email,
            'email_from': template.email_from,
            'author_id': self.env.user.partner_id.id,
            'auto_delete': True,
        }
        
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send()
        
        _logger.info("Đã đưa email cảnh báo cho KH '%s' vào hàng đợi để gửi đến %s.", self.name, self.user_id.email)

        
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
            
    @api.model
    def get_interaction_timeline_data(self, customer_id):
        """
        Tổng hợp dữ liệu tương tác của khách hàng từ các nguồn dữ liệu thật của Odoo:
        - res.partner: Ngày tạo tài khoản.
        - sale.order: Các đơn hàng đã xác nhận.
        - mail.message: Các ghi chú, email liên quan đến khách hàng.
        """
        partner = self.browse(customer_id)
        all_events = []
        
        # --- 1. LẤY DỮ LIỆU TỪ CÁC MODEL KHÁC NHAU ---

        # Sự kiện 1: Ngày tạo khách hàng
        if partner.create_date:
            all_events.append({
                'id': f'partner-{partner.id}',
                'date': partner.create_date,
                'title': 'Account Created',
                'type': 'system',
                'channel': 'Odoo',
                'icon': 'fa-user-plus',
                'description': f"Customer account for {partner.name} was created."
            })

        # Sự kiện 2: Các đơn hàng đã xác nhận (Sale or Done)
        sales_orders = self.env['sale.order'].search([
            ('partner_id', '=', customer_id),
            ('state', 'in', ['sale', 'done'])
        ])
        for order in sales_orders:
            all_events.append({
                'id': f'sale-{order.id}',
                'date': order.date_order,
                'title': f'Order {order.name} Confirmed',
                'type': 'payment',
                'channel': 'Sales',
                'icon': 'fa-shopping-cart',
                'description': f"Order {order.name} was confirmed for a total of {order.amount_total} {order.currency_id.symbol}."
            })
            
        # Sự kiện 3: Các tin nhắn, ghi chú, email liên quan
        messages = self.env['mail.message'].search([
            ('res_id', '=', customer_id),
            ('model', '=', 'res.partner'),
            ('message_type', '!=', 'notification') # Bỏ qua các tin nhắn hệ thống
        ])
        for msg in messages:
            # Rút gọn nội dung để hiển thị
            body_preview = (msg.body.strip('<p>').strip('</p>'))[:150] + '...' if len(msg.body) > 150 else (msg.body.strip('<p>').strip('</p>'))
            all_events.append({
                'id': f'msg-{msg.id}',
                'date': msg.date,
                'title': 'Communication Logged',
                'type': 'communication',
                'channel': 'Note/Email',
                'icon': 'fa-comments-o',
                'description': body_preview
            })

        # Sắp xếp tất cả các sự kiện theo ngày tháng (mới nhất lên đầu)
        # Chuyển đổi date object sang string ở bước này để đảm bảo tính nhất quán
        timeline_events_formatted = []
        for event in sorted(all_events, key=lambda e: e['date'], reverse=True):
            event['date_obj'] = event['date'] # Giữ lại object datetime để xử lý biểu đồ
            event['date'] = event['date'].strftime('%Y-%m-%d') # Chuyển thành chuỗi cho hiển thị
            timeline_events_formatted.append(event)
            
        # --- 2. CHUẨN BỊ DỮ LIỆU CHO BIỂU ĐỒ (6 THÁNG GẦN NHẤT) ---
        
        today = fields.Date.today()
        # Khởi tạo labels và values cho 6 tháng
        labels = []
        values = [0] * 6
        
        for i in range(5, -1, -1):
            # Lấy ngày của tháng tương ứng (ví dụ: 6 tháng trước, 5 tháng trước, ...)
            month_date = today - relativedelta(months=i)
            labels.append(month_abbr[month_date.month])

        # Đếm số lượng sự kiện trong mỗi tháng
        for event in all_events:
            event_date = event['date_obj']
            # Kiểm tra xem sự kiện có nằm trong khoảng 6 tháng gần đây không
            if today - relativedelta(months=6) < event_date.date() <= today:
                months_ago = (today.year - event_date.year) * 12 + (today.month - event_date.month)
                if 0 <= months_ago < 6:
                    # Index trong mảng values (0 = 5 tháng trước, ..., 5 = tháng này)
                    index = 5 - months_ago
                    values[index] += 1
                    
        chart_data = {
            'labels': labels,
            'values': values
        }

        # --- 3. TẠO CÁC INSIGHTS TỰ ĐỘNG ---
        
        insights = []
        # Insight 1: So sánh hoạt động tháng này và tháng trước
        last_30_days_count = sum(1 for e in all_events if e['date_obj'] > fields.Datetime.now() - timedelta(days=30))
        prev_30_days_count = sum(1 for e in all_events if fields.Datetime.now() - timedelta(days=60) < e['date_obj'] <= fields.Datetime.now() - timedelta(days=30))
        
        if prev_30_days_count > 0:
            percentage_change = ((last_30_days_count - prev_30_days_count) / prev_30_days_count) * 100
            if percentage_change >= 0:
                insights.append(f"Activity increased by {percentage_change:.0f}% in the last 30 days.")
            else:
                insights.append(f"Activity dropped by {abs(percentage_change):.0f}% in the last 30 days.")
        elif last_30_days_count > 0:
            insights.append("New activity recorded in the last 30 days.")
        
        # Insight 2: Thời gian từ lần mua hàng cuối cùng
        if sales_orders:
            last_order_date = max(order.date_order for order in sales_orders)
            days_since_last_order = (fields.Datetime.now() - last_order_date).days
            insights.append(f"Last purchase was {days_since_last_order} days ago.")
        else:
            insights.append("No purchase history found for this customer.")

        # --- 4. TRẢ VỀ KẾT QUẢ ---
        return {
            'timeline': timeline_events_formatted,
            'chart_data': chart_data,
            'insights': insights
        }