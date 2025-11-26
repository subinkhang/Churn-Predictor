# Tên file: import_script.py
# Script này được thiết kế để chạy bên trong Odoo shell.
# Cách chạy: docker-compose exec odoo odoo-bin shell -d ChurnPredictor_v2 < import_script.py

import logging
import pandas as pd
import os
import time
import gc

# Odoo shell sẽ cung cấp sẵn biến 'env'
# from odoo import api, fields, models, _ (không cần thiết khi chạy trong shell)

_logger = logging.getLogger(__name__)

# --- CÁC BIẾN TOÀN CỤC VÀ HÀM HELPER ---
DATA_DIR = '/mnt/extra-addons/ChurnPredictor/data_to_import' # Đường dẫn bên trong container
BATCH_SIZE = 500

def import_data(env):
    """Hàm chính điều phối toàn bộ quá trình import."""
    
    _logger.info("======================================================")
    _logger.info("BẮT ĐẦU QUÁ TRÌNH IMPORT DỮ LIỆU BẰNG ODOO SHELL")
    _logger.info("======================================================")

    # Thứ tự import rất quan trọng
    # import_products(env)
    # import_customers(env)
    # import_orders(env)
    # import_order_lines(env)
    # import_reviews_and_payments(env)
    import_customer_features(env)
    
    _logger.info("--- TOÀN BỘ QUÁ TRÌNH IMPORT ĐÃ HOÀN TẤT ---")

def import_products(env):
    filepath = os.path.join(DATA_DIR, 'products_to_import.csv')
    _logger.info(f"--- Bắt đầu import Sản phẩm từ '{filepath}' ---")
    try:
        df = pd.read_csv(filepath)
        df.dropna(subset=['x_kaggle_id'], inplace=True)
        df.drop_duplicates(subset=['x_kaggle_id'], inplace=True, keep='first')
        if 'name' not in df.columns:
            df['name'] = "Product " + df['x_kaggle_id'].str[:8]
        df.fillna(0, inplace=True) # Điền 0 cho tất cả các NaN còn lại
        
        all_kaggle_ids = df['x_kaggle_id'].tolist()
        _logger.info(f"Tổng số sản phẩm duy nhất cần xử lý: {len(all_kaggle_ids)}")

        existing_products = env['product.template'].search_read([('x_kaggle_id', 'in', all_kaggle_ids)], ['x_kaggle_id'])
        existing_kaggle_ids = {p['x_kaggle_id'] for p in existing_products}
        _logger.info(f"Tìm thấy {len(existing_kaggle_ids)} sản phẩm đã tồn tại.")

        df_to_create = df[~df['x_kaggle_id'].isin(existing_kaggle_ids)]
        
        if not df_to_create.empty:
            _logger.info(f"Chuẩn bị tạo mới {len(df_to_create)} sản phẩm...")
            vals_list = df_to_create.to_dict('records')
            
            created_count = 0
            for i in range(0, len(vals_list), BATCH_SIZE):
                batch_vals = vals_list[i:i + BATCH_SIZE]
                clean_batch_vals = [{'name': v.get('name'), 'x_kaggle_id': v.get('x_kaggle_id'), 'weight': v.get('weight', 0.0), 'type': 'product'} for v in batch_vals]
                
                _logger.info(f"Đang tạo lô sản phẩm từ {i} đến {i + len(clean_batch_vals)}...")
                try:
                    env['product.template'].create(clean_batch_vals)
                    env.cr.commit() # <<< QUAN TRỌNG: Commit giao dịch sau mỗi lô
                    created_count += len(clean_batch_vals)
                    _logger.info(f"  => Thành công! Đã commit {created_count} sản phẩm.")
                    time.sleep(0.5) # Nghỉ ngắn để giảm tải I/O
                except Exception as e:
                    _logger.error(f"LỖI khi tạo lô sản phẩm bắt đầu từ index {i}: {e}", exc_info=True)
                    env.cr.rollback() # Hủy bỏ lô bị lỗi
                    break
        
        _logger.info(f"--- Hoàn thành import Sản phẩm. ---")
    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong import_products: {e}", exc_info=True)

def import_customers(env):
    filepath = os.path.join(DATA_DIR, 'customers_to_import.csv')
    _logger.info(f"--- Bắt đầu import/cập nhật Khách hàng từ '{filepath}' ---")
    try:
        df = pd.read_csv(filepath)
        df.dropna(subset=['x_unique_id'], inplace=True)
        df.drop_duplicates(subset=['x_unique_id'], inplace=True, keep='first')
        df = df.where(pd.notnull(df), None)
        
        all_unique_ids = df['x_unique_id'].tolist()
        _logger.info(f"Tổng số dòng trong CSV: {len(all_unique_ids)}")

        # 1. TẢI TOÀN BỘ KHÁCH HÀNG HIỆN CÓ ĐỂ PHÂN LOẠI
        # Lấy ID và x_unique_id để map
        _logger.info("Đang tải danh sách khách hàng hiện có từ Odoo...")
        existing_records = env['res.partner'].search_read([('x_unique_id', 'in', all_unique_ids)], ['id', 'x_unique_id'])
        
        # Tạo Dictionary để tra cứu nhanh: {'abc12345': partner_id_1, ...}
        existing_map = {r['x_unique_id']: r['id'] for r in existing_records}
        _logger.info(f"Tìm thấy {len(existing_map)} khách hàng đã tồn tại (sẽ CẬP NHẬT).")
        _logger.info(f"Số lượng khách hàng mới (sẽ TẠO MỚI): {len(all_unique_ids) - len(existing_map)}")

        # 2. CHUẨN BỊ DỮ LIỆU CHUNG
        brazil = env['res.country'].search([('code', '=', 'BR')], limit=1)
        brazil_id = brazil.id if brazil else env.ref('base.us').id
        states = env['res.country.state'].search_read([('country_id', '=', brazil_id)], ['code', 'id'])
        state_map = {s['code']: s['id'] for s in states}

        # 3. CHUYỂN DATAFRAME THÀNH LIST DICT
        vals_list = df.to_dict('records')

        create_batch = []
        updated_count = 0
        created_count = 0

        _logger.info(">>> BẮT ĐẦU QUÁ TRÌNH XỬ LÝ...")

        for i, v in enumerate(vals_list):
            # Hàm helper để map feature (dùng chung cho cả create và write)
            def get_feature_vals(row):
                return {
                    'x_is_imported_data': True,
                    
                    # Mapping Feature Store
                    'x_feat_payment_value_sum': float(row.get('payment_value_sum') or 0.0),
                    'x_feat_payment_value_mean': float(row.get('payment_value_mean') or 0.0),
                    'x_feat_payment_value_max': float(row.get('payment_value_max') or 0.0),
                    'x_feat_payment_value_min': float(row.get('payment_value_min') or 0.0),
                    
                    'x_feat_delivery_days_mean': float(row.get('delivery_days_mean') or 0.0),
                    'x_feat_delivery_days_max': float(row.get('delivery_days_max') or 0.0),
                    'x_feat_delivery_delay_days_mean': float(row.get('delivery_delay_days_mean') or 0.0),
                    'x_feat_delivery_delay_days_max': float(row.get('delivery_delay_days_max') or 0.0),
                    
                    'x_feat_review_score_mean': float(row.get('review_score_mean') or 0.0),
                    'x_feat_review_score_min': float(row.get('review_score_min') or 0.0),
                    'x_feat_review_score_std': float(row.get('review_score_std') or 0.0),
                    
                    'x_feat_num_items_sum': float(row.get('num_items_sum') or 0.0),
                    'x_feat_num_items_mean': float(row.get('num_items_mean') or 0.0),
                    'x_feat_frequency': int(float(row.get('frequency') or 0)),
                    'x_feat_recency': int(float(row.get('recency') or 0)),
                    
                    'x_feat_payment_type_last': str(row.get('payment_type_last') or ''),
                    'x_feat_customer_state_last': str(row.get('customer_state_last') or ''),
                    'x_feat_product_category_name_english_last': str(row.get('product_category_name_english_last') or ''),
                }

            unique_id = v.get('x_unique_id')
            partner_id = existing_map.get(unique_id)

            # --- TRƯỜNG HỢP 1: UPDATE (ĐÃ CÓ) ---
            if partner_id:
                # Chỉ update các trường feature, không sửa tên/địa chỉ để tránh conflict dữ liệu cũ
                update_vals = get_feature_vals(v)
                try:
                    # Update từng bản ghi (Write không hỗ trợ batch create-like hiệu quả)
                    env['res.partner'].browse(partner_id).write(update_vals)
                    updated_count += 1
                except Exception as e:
                    _logger.error(f"Lỗi update Partner ID {partner_id}: {e}")

                # Commit mỗi 1000 bản ghi update để tránh quá tải RAM
                if updated_count % 1000 == 0:
                    env.cr.commit()
                    _logger.info(f"   -> Đã cập nhật {updated_count} khách hàng...")

            # --- TRƯỜNG HỢP 2: CREATE (CHƯA CÓ) ---
            else:
                create_vals = {
                    'name': f"Customer {str(unique_id)[:8]}",
                    'x_unique_id': unique_id,
                    'city': v.get('city'),
                    'zip': v.get('zip'),
                    'country_id': brazil_id,
                    'state_id': state_map.get(v.get('state_code')),
                    **get_feature_vals(v) # Merge thêm feature
                }
                create_batch.append(create_vals)

            # Xử lý lô tạo mới (Batch Create)
            if len(create_batch) >= BATCH_SIZE:
                try:
                    env['res.partner'].create(create_batch)
                    env.cr.commit()
                    created_count += len(create_batch)
                    _logger.info(f"   -> Đã tạo mới {created_count} khách hàng...")
                except Exception as e:
                    _logger.error(f"Lỗi tạo lô mới: {e}")
                    env.cr.rollback()
                finally:
                    create_batch = [] # Reset batch

        # Xử lý lô create còn sót lại
        if create_batch:
            try:
                env['res.partner'].create(create_batch)
                env.cr.commit()
                created_count += len(create_batch)
            except Exception as e:
                 _logger.error(f"Lỗi tạo lô cuối: {e}")

        # Commit lần cuối cho phần update
        env.cr.commit()

        _logger.info(f"--- HOÀN TẤT: Cập nhật {updated_count} | Tạo mới {created_count} ---")

    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong import_customers: {e}", exc_info=True)

def import_orders(env):
    filepath = os.path.join(DATA_DIR, 'orders_to_import.csv')
    _logger.info(f"--- Bắt đầu import Đơn hàng từ '{filepath}' ---")
    
    try:
        df = pd.read_csv(filepath)
        # Làm sạch dữ liệu
        df.dropna(subset=['x_kaggle_id', 'customer_unique_id'], inplace=True)
        df.drop_duplicates(subset=['x_kaggle_id'], inplace=True, keep='first')
        df = df.where(pd.notnull(df), None)
        
        all_kaggle_ids = df['x_kaggle_id'].tolist()
        _logger.info(f"Tổng số đơn hàng cần xử lý: {len(all_kaggle_ids)}")

        # 1. KIỂM TRA ĐƠN HÀNG ĐÃ TỒN TẠI
        existing_orders = env['sale.order'].search_read([('x_kaggle_id', 'in', all_kaggle_ids)], ['x_kaggle_id'])
        existing_ids = {o['x_kaggle_id'] for o in existing_orders}
        _logger.info(f"Tìm thấy {len(existing_ids)} đơn hàng đã tồn tại.")

        df_to_create = df[~df['x_kaggle_id'].isin(existing_ids)]
        
        if df_to_create.empty:
            _logger.info("Không có đơn hàng mới nào để import.")
            return

        # 2. TẢI TRƯỚC MAPPING KHÁCH HÀNG (Bước quan trọng để tăng tốc)
        # Lấy danh sách tất cả unique_id khách hàng cần dùng
        required_customer_ids = df_to_create['customer_unique_id'].unique().tolist()
        _logger.info(f"Đang tải thông tin của {len(required_customer_ids)} khách hàng để liên kết...")
        
        # Search một lần lấy hết ID
        # Lưu ý: Nếu số lượng quá lớn (>50k), có thể chia nhỏ search, nhưng với 96k thì Odoo vẫn chịu được
        partners = env['res.partner'].search_read(
            [('x_unique_id', 'in', required_customer_ids)], 
            ['id', 'x_unique_id']
        )
        # Tạo Dictionary: {'abc1234': 56, ...}
        partner_map = {p['x_unique_id']: p['id'] for p in partners}
        _logger.info(f"Đã tải xong map của {len(partner_map)} khách hàng.")

        # 3. TẠO ĐƠN HÀNG THEO LÔ
        _logger.info(f"Chuẩn bị tạo mới {len(df_to_create)} đơn hàng...")
        vals_list = df_to_create.to_dict('records')
        
        created_count = 0
        skipped_count = 0
        
        for i in range(0, len(vals_list), BATCH_SIZE):
            batch_vals = vals_list[i:i + BATCH_SIZE]
            clean_batch_vals = []
            
            for v in batch_vals:
                customer_kaggle_id = v.get('customer_unique_id')
                odoo_partner_id = partner_map.get(customer_kaggle_id)
                
                if not odoo_partner_id:
                    # Nếu không tìm thấy khách hàng trong Odoo, bỏ qua đơn này
                    skipped_count += 1
                    continue

                vals = {
                    'x_kaggle_id': v.get('x_kaggle_id'),
                    'partner_id': odoo_partner_id,
                    'date_order': v.get('date_order'),
                    'state': 'sale', # Set trạng thái là Sale Order luôn
                    'x_churn_label': int(v.get('x_churn_label')) if v.get('x_churn_label') is not None else 0,
                    # Lưu ý: amount_total là field computed, ta không ghi trực tiếp được
                    # Ta sẽ import order_line sau, Odoo sẽ tự tính amount_total
                }
                clean_batch_vals.append(vals)

            if not clean_batch_vals:
                continue

            _logger.info(f"Đang tạo lô đơn hàng từ {i} đến {i + len(clean_batch_vals)}...")
            try:
                env['sale.order'].create(clean_batch_vals)
                env.cr.commit()
                created_count += len(clean_batch_vals)
                _logger.info(f"  => Thành công! Đã commit {created_count} đơn hàng.")
                time.sleep(0.5)
            except Exception as e:
                _logger.error(f"LỖI khi tạo lô đơn hàng bắt đầu từ index {i}: {e}", exc_info=True)
                env.cr.rollback()
                # Cơ chế thử lại từng cái (Fallback)
                for single_val in clean_batch_vals:
                    try:
                        env['sale.order'].create(single_val)
                        env.cr.commit()
                    except Exception as single_e:
                        _logger.error(f"    => Lỗi đơn hàng ID '{single_val.get('x_kaggle_id')}': {single_e}")
                        env.cr.rollback()
                # Break sau khi xử lý lỗi để bạn kiểm tra log, hoặc bỏ break để chạy tiếp
                # break 

        _logger.info(f"--- Hoàn thành import Đơn hàng. ---")
        if skipped_count > 0:
            _logger.warning(f"Đã bỏ qua {skipped_count} đơn hàng do không tìm thấy Khách hàng tương ứng.")

    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong import_orders: {e}", exc_info=True)

def import_order_lines(env):
    filepath = os.path.join(DATA_DIR, 'order_lines_to_import.csv')
    _logger.info(f"--- Bắt đầu import Dòng Đơn Hàng từ '{filepath}' ---")
    
    try:
        # Đọc file CSV theo từng chunk (lô) vì file này thường rất lớn
        # Chúng ta không đọc hết vào RAM một lúc
        chunk_size = 2000 # Đọc 2000 dòng mỗi lần từ CSV
        csv_iterator = pd.read_csv(filepath, chunksize=chunk_size)
        
        # 1. TẢI TRƯỚC MAPPING (SẢN PHẨM VÀ ĐƠN HÀNG)
        # Vì chúng ta không thể biết trước ID nào sẽ dùng khi đọc chunk,
        # nên cách tốt nhất là load toàn bộ map nếu bộ nhớ cho phép.
        # Với 30k sản phẩm và 96k đơn hàng, việc này hoàn toàn khả thi.
        
        _logger.info("Đang tải mapping Sản phẩm (Product)...")
        products = env['product.product'].search_read([], ['id', 'product_tmpl_id'])
        # Cần map từ kaggle_id của template -> product.product id
        # Bước này hơi phức tạp: Kaggle ID nằm ở template, nhưng order_line cần product.product
        templates = env['product.template'].search_read([], ['id', 'x_kaggle_id'])
        tmpl_map = {t['id']: t['x_kaggle_id'] for t in templates if t['x_kaggle_id']}
        
        # Map cuối cùng: {'kaggle_id': odoo_product_id}
        product_map = {}
        for p in products:
            k_id = tmpl_map.get(p['product_tmpl_id'][0])
            if k_id:
                product_map[k_id] = p['id']
        _logger.info(f"Đã map được {len(product_map)} sản phẩm.")

        _logger.info("Đang tải mapping Đơn hàng (Sale Order)...")
        orders = env['sale.order'].search_read([], ['id', 'x_kaggle_id'])
        order_map = {o['x_kaggle_id']: o['id'] for o in orders if o['x_kaggle_id']}
        _logger.info(f"Đã map được {len(order_map)} đơn hàng.")

        # 2. XỬ LÝ TỪNG CHUNK
        total_lines_created = 0
        
        for chunk_idx, df in enumerate(csv_iterator):
            df = df.where(pd.notnull(df), None)
            vals_list = []
            
            for index, row in df.iterrows():
                kaggle_order_id = row.get('order_id')
                kaggle_product_id = row.get('product_id')
                
                odoo_order_id = order_map.get(kaggle_order_id)
                odoo_product_id = product_map.get(kaggle_product_id)
                
                if not odoo_order_id or not odoo_product_id:
                    # Bỏ qua nếu không tìm thấy đơn hàng hoặc sản phẩm tương ứng
                    continue

                vals = {
                    'order_id': odoo_order_id,
                    'product_id': odoo_product_id,
                    'product_uom_qty': row.get('product_uom_qty', 1.0),
                    'price_unit': row.get('price_unit', 0.0),
                    'sequence': int(row.get('sequence')) if row.get('sequence') else 10,
                    # Không cần import price_subtotal, Odoo tự tính
                }
                vals_list.append(vals)

            # Tạo hàng loạt cho chunk này
            if vals_list:
                try:
                    env['sale.order.line'].create(vals_list)
                    env.cr.commit() # Commit sau mỗi chunk
                    total_lines_created += len(vals_list)
                    _logger.info(f"  => Chunk {chunk_idx+1}: Đã tạo {len(vals_list)} dòng. Tổng cộng: {total_lines_created}")
                except Exception as e:
                    _logger.error(f"LỖI khi tạo Chunk {chunk_idx+1}: {e}", exc_info=True)
                    env.cr.rollback()
                    # Fallback: Thử tạo từng dòng (tương tự các hàm trước)
                    for v in vals_list:
                        try:
                            env['sale.order.line'].create(v)
                            env.cr.commit()
                        except Exception:
                            env.cr.rollback()

        _logger.info(f"--- Hoàn thành import Dòng Đơn Hàng. Tổng cộng {total_lines_created} dòng. ---")

    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong import_order_lines: {e}", exc_info=True)

def import_reviews_and_payments(env):
    # --- CHUẨN BỊ DỮ LIỆU CHUNG (MAPPING) BẰNG SQL ---
    _logger.info("Đang tải mapping Đơn hàng (Sale Order) bằng SQL...")
    
    query = "SELECT x_kaggle_id, id, partner_id FROM sale_order WHERE x_kaggle_id IS NOT NULL"
    env.cr.execute(query)
    orders_data = env.cr.fetchall()
    
    order_map = {row[0]: row[1] for row in orders_data}
    order_partner_map = {row[0]: row[2] for row in orders_data if row[2]}
    del orders_data
    
    _logger.info(f"Đã map được {len(order_map)} đơn hàng.")

    # ==========================================================================
    # PHẦN 1: IMPORT REVIEWS (ĐÁNH GIÁ)
    # ==========================================================================
    filepath_rev = os.path.join(DATA_DIR, 'reviews_to_import.csv')
    _logger.info(f"--- Bắt đầu import Đánh giá từ '{filepath_rev}' ---")
    
    try:
        chunk_size = 2000
        csv_iterator = pd.read_csv(filepath_rev, chunksize=chunk_size)
        total_rev_created = 0
        
        for chunk in csv_iterator:
            chunk = chunk.where(pd.notnull(chunk), None)
            vals_list = []
            
            for index, row in chunk.iterrows():
                kaggle_order_id = row.get('order_id')
                odoo_order_id = order_map.get(kaggle_order_id)
                partner_id = order_partner_map.get(kaggle_order_id)
                
                if not odoo_order_id or not partner_id: 
                    continue 

                # Xử lý rating an toàn
                raw_rating = row.get('rating')
                rating_val = 0.0
                try:
                    if raw_rating is not None:
                        rating_val = float(raw_rating)
                        rating_val = max(0.0, min(5.0, rating_val)) # Kẹp giữa 0 và 5
                except (ValueError, TypeError):
                    rating_val = 0.0

                vals = {
                    'res_model': 'sale.order',
                    'res_id': odoo_order_id,
                    'res_name': kaggle_order_id,
                    'rating': rating_val,
                    'feedback': row.get('feedback', ''),
                    'consumed': True,
                    'partner_id': partner_id,
                    'x_has_review_text': bool(row.get('x_has_review_text'))
                }
                vals_list.append(vals)

            if vals_list:
                try:
                    env['rating.rating'].create(vals_list)
                    env.cr.commit()
                    total_rev_created += len(vals_list)
                    _logger.info(f"  => Reviews: Đã tạo {total_rev_created} bản ghi.")
                except Exception as e:
                    # Log chi tiết hơn về lỗi
                    _logger.error(f"Lỗi import Review: {str(e)}")
                    env.cr.rollback()
        
        _logger.info("--- Hoàn thành import Reviews ---")

    except FileNotFoundError:
        _logger.error(f"Không tìm thấy file: {filepath_rev}")
    except Exception as e:
        _logger.error(f"Lỗi trong phần Reviews: {e}", exc_info=True)


    # ==========================================================================
    # PHẦN 2: IMPORT PAYMENTS (THANH TOÁN)
    # ==========================================================================
    filepath_pay = os.path.join(DATA_DIR, 'payments_to_import.csv')
    _logger.info(f"--- Bắt đầu import Thanh toán từ '{filepath_pay}' ---")

    try:
        # 1. Chuẩn bị Provider, Method và Currency
        provider = env['payment.provider'].search([], limit=1)
        if not provider:
            provider = env['payment.provider'].create({'name': 'Import Data Provider', 'state': 'test'})
        else:
            provider = provider[0]

        payment_method = env['payment.method'].search([], limit=1)
        if not payment_method:
             payment_method = env['payment.method'].search([('code', '=', 'unknown')], limit=1)
             if not payment_method:
                 payment_method = env['payment.method'].create({'name': 'Import Method', 'code': 'import_method'})
        else:
            payment_method = payment_method[0]

        currency = env.ref('base.BRL', raise_if_not_found=False)
        if not currency:
            currency = env.ref('base.USD')
        
        # 2. Lấy danh sách Reference đã tồn tại để tránh trùng lặp
        _logger.info("Đang kiểm tra các thanh toán đã tồn tại...")
        # Lấy tất cả reference bắt đầu bằng "PAY-" để tối ưu query
        existing_refs_query = "SELECT reference FROM payment_transaction WHERE reference LIKE 'PAY-%'"
        env.cr.execute(existing_refs_query)
        existing_refs = {row[0] for row in env.cr.fetchall()}
        _logger.info(f"Tìm thấy {len(existing_refs)} thanh toán đã có trong hệ thống.")

        # 3. Xử lý CSV và Tạo mới
        chunk_size = 2000
        csv_iterator_pay = pd.read_csv(filepath_pay, chunksize=chunk_size)
        total_pay_created = 0

        for chunk in csv_iterator_pay:
            chunk = chunk.where(pd.notnull(chunk), None)
            vals_list = []
            
            for index, row in chunk.iterrows():
                kaggle_order_id = row.get('order_id')
                odoo_order_id = order_map.get(kaggle_order_id)
                partner_id = order_partner_map.get(kaggle_order_id)

                if not odoo_order_id: continue

                seq = row.get('sequence', 0)
                reference = f"PAY-{kaggle_order_id}-{seq}"

                # KIỂM TRA: Nếu reference đã tồn tại thì bỏ qua ngay
                if reference in existing_refs:
                    continue

                vals = {
                    'provider_id': provider.id,
                    'payment_method_id': payment_method.id,
                    'reference': reference,
                    'amount': float(row.get('amount', 0)),
                    'currency_id': currency.id,
                    'partner_id': partner_id,
                    'sale_order_ids': [(6, 0, [odoo_order_id])],
                    'state': 'done',
                    'provider_reference': str(row.get('payment_type', 'unknown')) 
                }
                vals_list.append(vals)
                # Thêm vào set để tránh trùng lặp ngay trong chính file CSV (nếu có)
                existing_refs.add(reference)

            if vals_list:
                try:
                    env['payment.transaction'].create(vals_list)
                    env.cr.commit()
                    total_pay_created += len(vals_list)
                    _logger.info(f"  => Payments: Đã tạo {total_pay_created} bản ghi.")
                except Exception as e:
                    _logger.error(f"Lỗi import Payment lô hiện tại: {str(e)}")
                    env.cr.rollback()

        _logger.info("--- Hoàn thành import Thanh toán ---")

    except FileNotFoundError:
        _logger.error(f"Không tìm thấy file: {filepath_pay}")
    except Exception as e:
        _logger.error(f"Lỗi trong phần Payments: {e}", exc_info=True)
        
def import_customer_features(env):
    """
    Hàm này đọc file 'customer_features_store.csv' THEO TỪNG CHUNK (LÔ)
    để tránh lỗi tràn bộ nhớ (OOM) do file chứa quá nhiều cột vector BERT.
    """
    filename = 'customer_features_store.csv'
    filepath = os.path.join(DATA_DIR, filename)
    
    _logger.info(f"========================================================")
    _logger.info(f"BẮT ĐẦU CẬP NHẬT FEATURE STORE (CHUNKING MODE)")
    _logger.info(f"File: {filename}")
    _logger.info(f"========================================================")
    
    if not os.path.exists(filepath):
        _logger.error(f"LỖI: Không tìm thấy file '{filepath}'.")
        return

    try:
        # Cấu hình đọc từng lô nhỏ (ví dụ 500 dòng một lần)
        # File có BERT rất nặng nên 500 dòng là an toàn cho RAM
        chunk_size = 500 
        
        # Tạo iterator để đọc file
        csv_iterator = pd.read_csv(filepath, chunksize=chunk_size)
        
        total_updated = 0
        
        for chunk_idx, df in enumerate(csv_iterator):
            _logger.info(f"--- Đang xử lý Chunk {chunk_idx + 1} (Dòng {chunk_idx * chunk_size} -> {(chunk_idx + 1) * chunk_size}) ---")
            
            # 1. Xử lý dữ liệu trong chunk này
            df.fillna(0, inplace=True)
            
            # Lấy danh sách ID trong lô hiện tại
            current_ids = df['x_unique_id'].astype(str).tolist()
            
            # 2. Tìm khách hàng trong Odoo (Chỉ tìm những người có trong lô này)
            partners = env['res.partner'].search_read(
                [('x_unique_id', 'in', current_ids)], 
                ['id', 'x_unique_id']
            )
            partner_map = {p['x_unique_id']: p['id'] for p in partners}
            
            # 3. Duyệt và Update
            records = df.to_dict('records')
            chunk_updates = 0
            
            for row in records:
                unique_id = str(row.get('x_unique_id'))
                partner_id = partner_map.get(unique_id)
                
                if not partner_id:
                    continue
                    
                vals = {
                    'x_is_imported_data': True,
                    
                    # Payment
                    'x_feat_payment_value_sum': float(row.get('payment_value_sum', 0)),
                    'x_feat_payment_value_mean': float(row.get('payment_value_mean', 0)),
                    'x_feat_payment_value_max': float(row.get('payment_value_max', 0)),
                    'x_feat_payment_value_min': float(row.get('payment_value_min', 0)),

                    # Delivery
                    'x_feat_delivery_days_mean': float(row.get('delivery_days_mean', 0)),
                    'x_feat_delivery_days_max': float(row.get('delivery_days_max', 0)),
                    'x_feat_delivery_delay_days_mean': float(row.get('delivery_delay_days_mean', 0)),
                    'x_feat_delivery_delay_days_max': float(row.get('delivery_delay_days_max', 0)),

                    # Review
                    'x_feat_review_score_mean': float(row.get('review_score_mean', 0)),
                    'x_feat_review_score_min': float(row.get('review_score_min', 0)),
                    'x_feat_review_score_std': float(row.get('review_score_std', 0)),

                    # RFM & Items
                    'x_feat_num_items_sum': float(row.get('num_items_sum', 0)),
                    'x_feat_num_items_mean': float(row.get('num_items_mean', 0)),
                    'x_feat_frequency': int(float(row.get('frequency', 0))),
                    'x_feat_recency': int(float(row.get('recency', 0))),

                    # Categorical
                    'x_feat_payment_type_last': str(row.get('payment_type_last', '')),
                    'x_feat_customer_state_last': str(row.get('customer_state_last', '')),
                    'x_feat_product_category_name_english_last': str(row.get('product_category_name_english_last', '')),
                }
                
                try:
                    env['res.partner'].browse(partner_id).write(vals)
                    chunk_updates += 1
                    total_updated += 1
                except Exception:
                    pass
            
            # 4. Commit và giải phóng bộ nhớ sau mỗi Chunk
            env.cr.commit()
            _logger.info(f"   -> Đã commit {chunk_updates} khách hàng trong chunk này.")
            
            # Giải phóng RAM thủ công
            del df
            del records
            del partner_map
            del partners
            gc.collect() 

        _logger.info(f"========================================================")
        _logger.info(f"HOÀN TẤT! TỔNG CỘNG ĐÃ CẬP NHẬT: {total_updated} KHÁCH HÀNG")
        _logger.info(f"========================================================")

    except Exception as e:
        _logger.error(f"Lỗi trong quá trình import features: {e}", exc_info=True)

# --- ĐIỂM BẮT ĐẦU THỰC THI SCRIPT ---
# Code này sẽ tự động chạy khi được đưa vào odoo-bin shell
if 'env' in locals():
    import_data(env)