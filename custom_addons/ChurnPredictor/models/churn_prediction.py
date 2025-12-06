# -*- coding: utf-8 -*-
import base64
import logging
import os
import pickle
import io

import pandas as pd
import xgboost
import joblib
import shap

from odoo import models, fields, api
from odoo.modules import get_module_resource
from datetime import datetime

_logger = logging.getLogger(__name__)

# --- BIẾN TOÀN CỤC ĐỂ LƯU MODEL (CHỈ LOAD 1 LẦN) ---
_model = None
_model_columns = None
_explainer = None

def _load_model_and_columns():
    global _model, _model_columns, _explainer
    
    # if _model is not None: return # Bỏ cache để luôn load mới nhất

    try:
        # 1. Tìm folder mới nhất
        current_dir = os.path.dirname(os.path.abspath(__file__))
        ml_assets_dir = os.path.join(current_dir, 'ml_assets')
        
        subfolders = [f for f in os.listdir(ml_assets_dir) if os.path.isdir(os.path.join(ml_assets_dir, f))]
        
        if subfolders:
            latest_version = sorted(subfolders)[-1]
            model_path = os.path.join(ml_assets_dir, latest_version, 'churn_model.joblib')
            _logger.info(f"Loading Model Version: {latest_version}")
        else:
            # Fallback
            model_path = os.path.join(ml_assets_dir, 'churn_model.joblib')

        if not os.path.exists(model_path):
            _logger.error(f"Model file not found: {model_path}")
            return

        # 2. Load Model
        _model = joblib.load(model_path)
        
        # 3. [FIX] Lấy danh sách cột trực tiếp từ Model
        # XGBoost lưu feature names trong thuộc tính feature_names_in_ (sklearn API)
        if hasattr(_model, 'feature_names_in_'):
            _model_columns = _model.feature_names_in_.tolist()
            _logger.info(f"Loaded {_len(_model_columns)} features directly from model.")
        else:
            # Fallback nếu model không có thuộc tính này (hiếm gặp với xgboost mới)
            _logger.warning("Model does not have feature_names_in_. Trying to load from pkl...")
            columns_path = os.path.join(os.path.dirname(model_path), 'model_columns.pkl')
            if not os.path.exists(columns_path):
                 columns_path = os.path.join(ml_assets_dir, 'model_columns.pkl')
            
            if os.path.exists(columns_path):
                with open(columns_path, 'rb') as f:
                    _model_columns = pickle.load(f)
            else:
                _logger.error("Cannot find feature names source!")
                return

        # 4. Init SHAP
        _explainer = shap.TreeExplainer(_model)
        _logger.info("Model & Explainer loaded successfully.")

    except Exception as e:
        _logger.error(f"Error loading model: {e}", exc_info=True)
        _model = None

class ChurnPrediction(models.Model):
    _inherit = 'churn.prediction' # Kế thừa từ model bạn đã định nghĩa

    @api.model
    def _get_customer_features(self, customer):
        """
        Đây là hàm cốt lõi, thực hiện Feature Engineering cho một khách hàng.
        Input: customer (bản ghi res.partner)
        Output: DataFrame Pandas với một hàng, chứa đầy đủ feature cho mô hình.
        """
        _load_model_and_columns()
        if not _model_columns:
            _logger.error("Model columns are not loaded. Cannot generate features.")
            return None

        # 1. Tạo DataFrame mẫu với cấu trúc chuẩn
        features_df = pd.DataFrame(0, index=[0], columns=_model_columns)

        # 2. Truy vấn dữ liệu Odoo
        orders = self.env['sale.order'].search([
            ('partner_id', '=', customer.id),
            ('state', 'in', ['sale', 'done'])
        ], order='date_order desc')

        if not orders:
            # Nếu khách hàng không có đơn hàng nào, trả về DataFrame với các giá trị mặc định (0)
            # Ngoại trừ recency, ta gán một giá trị lớn
            features_df.loc[0, 'recency'] = 999 
            return features_df

        # --- TÍNH TOÁN CÁC FEATURE ---

        # Recency & Frequency
        features_df.loc[0, 'frequency'] = len(orders)
        last_order_date = orders[0].date_order.date()
        features_df.loc[0, 'recency'] = (fields.Date.today() - last_order_date).days

        # Monetary Features
        amounts = orders.mapped('amount_total')
        features_df.loc[0, 'payment_value_sum'] = sum(amounts)
        features_df.loc[0, 'payment_value_mean'] = sum(amounts) / len(amounts) if amounts else 0.0
        features_df.loc[0, 'payment_value_max'] = max(amounts) if amounts else 0.0
        features_df.loc[0, 'payment_value_min'] = min(amounts) if amounts else 0.0

        # Num Items Sum
        order_lines = self.env['sale.order.line'].search([('order_id', 'in', orders.ids)])
        features_df.loc[0, 'num_items_sum'] = sum(order_lines.mapped('product_uom_qty'))

        # Delivery & Review Features (Sử dụng giá trị mặc định từ notebook vì model Odoo chưa có)
        # GHI CHÚ: Đây là điểm cần cải thiện trong tương lai nếu bạn thêm các module này vào Odoo.
        features_df.loc[0, 'delivery_days_mean'] = 0.0 # Cần logic tính từ stock.picking
        features_df.loc[0, 'delivery_delay_days_mean'] = 0.0 # Cần logic tính từ stock.picking và commitment_date
        features_df.loc[0, 'review_score_mean'] = 5.0 # Giá trị median từ notebook
        features_df.loc[0, 'review_score_min'] = 5.0 # Giá trị median từ notebook

        # Last Transaction Features (One-Hot Encoded)
        last_order = orders[0]

        # Customer State Last
        if last_order.partner_shipping_id.state_id:
            state_code = last_order.partner_shipping_id.state_id.code
            state_col = f"customer_state_last_{state_code}"
            if state_col in features_df.columns:
                features_df.loc[0, state_col] = 1

        # Product Category Last
        if last_order.order_line:
            # Lấy danh mục của sản phẩm đầu tiên trong đơn hàng cuối
            category_name = last_order.order_line[0].product_id.categ_id.name or ''
            # Chuẩn hóa tên: 'Bed, Bath & Table' -> 'bed_bath_table'
            sanitized_name = category_name.lower().replace(', ', '_').replace(' & ', '_').replace(' ', '_')
            cat_col = f"product_category_name_english_last_{sanitized_name}"
            if cat_col in features_df.columns:
                features_df.loc[0, cat_col] = 1
        
        # Payment Type Last
        # Logic này giả định bạn dùng module 'payment' và có 'payment.transaction'
        last_tx = self.env['payment.transaction'].search([
            ('sale_order_ids', 'in', last_order.id)
        ], limit=1, order='id desc')
        if last_tx and last_tx.payment_method_id:
            payment_name = last_tx.payment_method_id.name or ''
            sanitized_payment = payment_name.lower().replace(' ', '_')
            pay_col = f"payment_type_last_{sanitized_payment}"
            if pay_col in features_df.columns:
                features_df.loc[0, pay_col] = 1
        
        # BERT features sẽ giữ nguyên giá trị 0 vì chúng ta đã đơn giản hóa chúng.

        return features_df

    @api.model
    def run_prediction_for_customer(self, customer_id):
        """
        Hàm chính để chạy toàn bộ quy trình dự đoán cho một khách hàng.
        """
        _load_model_and_columns()
        if not all([_model, _model_columns, _explainer]):
            _logger.error("Model/columns/explainer not available. Prediction aborted.")
            return False

        customer = self.env['res.partner'].browse(customer_id)
        if not customer.exists():
            _logger.warning(f"Customer with ID {customer_id} not found.")
            return False

        _logger.info(f"Running churn prediction for customer: {customer.name} (ID: {customer_id})")

        # 1. Lấy features
        features_df = self._get_customer_features(customer)
        if features_df is None:
            return False
            
        # Đảm bảo các cột boolean được chuyển thành int 0/1
        bool_cols = features_df.select_dtypes(include='bool').columns
        features_df[bool_cols] = features_df[bool_cols].astype(int)

        # 2. Thực hiện dự đoán
        try:
            # predict_proba trả về [[prob_no_churn, prob_churn]]
            probability_churn = _model.predict_proba(features_df)[0][1] * 100
            prediction_raw = _model.predict(features_df)[0]
            prediction_result = 'churn' if prediction_raw == 1 else 'no_churn'
        except Exception as e:
            _logger.error(f"Error during model prediction: {e}", exc_info=True)
            return False

        # 3. Tạo giải thích bằng SHAP
        shap_html_base64 = False
        try:
            shap_values = _explainer.shap_values(features_df)
            
            # Sử dụng io.BytesIO để lưu plot vào bộ nhớ thay vì file
            shap_plot_buffer = io.BytesIO()
            
            # shap.force_plot cần matplotlib.pyplot, chúng ta sẽ lưu nó
            # Javascript=False sẽ render HTML tĩnh
            p = shap.force_plot(
                _explainer.expected_value, shap_values[0,:], features_df.iloc[0,:],
                show=False, matplotlib=False
            )
            
            # Lưu plot HTML vào buffer
            shap.save_html(shap_plot_buffer, p)
            shap_plot_buffer.seek(0) # Đưa con trỏ về đầu file
            
            # Mã hóa base64 để lưu vào trường Binary
            shap_html_base64 = base64.b64encode(shap_plot_buffer.read())

        except Exception as e:
            _logger.error(f"Error generating SHAP explanation: {e}", exc_info=True)

        # 4. Lưu kết quả vào Odoo
        prediction_record = self.create({
            'customer_id': customer.id,
            'prediction_result': prediction_result,
            'probability': probability_churn,
            'shap_html': shap_html_base64,
        })
        
        _logger.info(f"Prediction complete. Record created with ID: {prediction_record.id}")

        return prediction_record.id