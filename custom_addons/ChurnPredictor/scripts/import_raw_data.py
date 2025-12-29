import os
import pandas as pd
import gc
import logging
from odoo.tools import config

_logger = logging.getLogger(__name__)

# --- CÁC HÀM PHỤ TRỢ ĐỂ TỐI ƯU HÓA ---

def _find_or_create_related(env, model_name, name_map, cache):
    """Hàm tìm hoặc tạo các bản ghi liên quan đơn giản (như state, country)."""
    ids_to_find = [name for name, code in name_map.items() if code not in cache]
    if ids_to_find:
        found_records = env[model_name].search([('code', 'in', ids_to_find)])
        for rec in found_records:
            cache[rec.code] = rec.id
    
    for name, code in name_map.items():
        if code not in cache:
            try:
                new_rec = env[model_name].create({'name': name, 'code': code})
                cache[code] = new_rec.id
                _logger.info(f"Tạo mới {model_name}: {name}")
            except Exception as e:
                _logger.warning(f"Không thể tạo {model_name} '{name}': {e}")
                cache[code] = False
    return cache

def _prepare_partners(env, chunk_df):
    """Tìm hoặc chuẩn bị dữ liệu để tạo khách hàng mới theo lô."""
    unique_customers = chunk_df.drop_duplicates(subset=['customer_unique_id'])
    unique_ids = unique_customers['customer_unique_id'].tolist()
    
    existing_partners = env['res.partner'].search_read(
        [('x_unique_id', 'in', unique_ids)], ['id', 'x_unique_id']
    )
    partner_map = {p['x_unique_id']: p['id'] for p in existing_partners}
    
    partners_to_create = []
    for _, row in unique_customers.iterrows():
        uid = row['customer_unique_id']
        if uid not in partner_map:
            partners_to_create.append({
                'name': f"Customer {uid[:8]}", # Tên tạm thời
                'x_unique_id': uid,
                'city': row.get('customer_city'),
                'zip': row.get('customer_zip_code_prefix'),
                # Cần tìm state_id và country_id, sẽ xử lý sau
            })
            
    return partner_map, partners_to_create, unique_customers

def _prepare_products(env, chunk_df):
    """Tìm hoặc chuẩn bị dữ liệu để tạo sản phẩm mới theo lô."""
    unique_products = chunk_df.drop_duplicates(subset=['product_id'])
    product_ids = unique_products['product_id'].tolist()

    existing_products = env['product.product'].search_read(
        [('default_code', 'in', product_ids)], ['id', 'default_code']
    )
    product_map = {p['default_code']: p['id'] for p in existing_products}
    
    products_to_create = []
    for _, row in unique_products.iterrows():
        pid = row['product_id']
        if pid not in product_map:
            products_to_create.append({
                'name': row.get('product_category_name_english', f"Product {pid[:8]}"),
                'default_code': pid,
                'type': 'product', # Kiểu sản phẩm kho
                'sale_ok': True,
                'purchase_ok': True,
            })
            
    return product_map, products_to_create


# --- HÀM IMPORT CHÍNH ---

def import_raw_data(env, filename, chunk_size=2000): # Thay filepath thành filename
    """
    Import dữ liệu giao dịch thô từ TÊN FILE theo từng lô (chunk).
    """
    # XÂY DỰNG ĐƯỜNG DẪN BÊN TRONG ODOO
    # /mnt/extra-addons là đường dẫn được mount trong docker-compose.yml
    module_path = '/mnt/extra-addons/ChurnPredictor'
    filepath = os.path.join(module_path, 'data_to_import', filename)
    
    _logger.info("========================================================")
    _logger.info(f"BẮT ĐẦU IMPORT DỮ LIỆU THÔ (RAW DATA)")
    _logger.info(f"Đang xử lý file: {filepath}")
    _logger.info("========================================================")

    if not os.path.exists(filepath):
        _logger.error(f"LỖI: Không tìm thấy file '{filepath}'.")
        return

    # Cache cho các bản ghi liên quan để giảm truy vấn
    state_cache = {}
    country_cache = {'BR': env.ref('base.br').id} # Mặc định là Brazil

    total_orders_created = 0
    
    try:
        # Đọc file theo từng lô, ép kiểu các cột ID thành chuỗi
        csv_iterator = pd.read_csv(filepath, chunksize=chunk_size, dtype={
            'order_id': str, 'customer_id': str, 'product_id': str, 
            'seller_id': str, 'review_id': str, 'customer_unique_id': str
        })

        for chunk_idx, chunk_df in enumerate(csv_iterator):
            _logger.info(f"--- Đang xử lý Chunk {chunk_idx + 1} ---")
            chunk_df.fillna('', inplace=True)

            # 1. XỬ LÝ KHÁCH HÀNG (res.partner)
            partner_map, partners_to_create_vals, unique_customers_df = _prepare_partners(env, chunk_df)
            if partners_to_create_vals:
                # Tìm state cho các khách hàng mới
                states_to_find = {row['customer_state']: row['customer_state'] for _, row in unique_customers_df.iterrows() if row.get('customer_state')}
                state_cache = _find_or_create_related(env, 'res.country.state', states_to_find, state_cache)
                
                for vals in partners_to_create_vals:
                    state_code = unique_customers_df[unique_customers_df['x_unique_id'] == vals['x_unique_id']].iloc[0]['customer_state']
                    vals['state_id'] = state_cache.get(state_code)
                    vals['country_id'] = country_cache['BR']
                
                new_partners = env['res.partner'].create(partners_to_create_vals)
                for p in new_partners:
                    partner_map[p.x_unique_id] = p.id
                _logger.info(f"   -> Đã tạo {len(new_partners)} khách hàng mới.")

            # 2. XỬ LÝ SẢN PHẨM (product.product)
            product_map, products_to_create_vals = _prepare_products(env, chunk_df)
            if products_to_create_vals:
                new_products = env['product.product'].create(products_to_create_vals)
                for p in new_products:
                    product_map[p.default_code] = p.id
                _logger.info(f"   -> Đã tạo {len(new_products)} sản phẩm mới.")

            # 3. XỬ LÝ ĐƠN HÀNG (sale.order & sale.order.line)
            # Tìm các đơn hàng trong chunk này đã tồn tại trong Odoo
            order_ids_in_chunk = chunk_df['order_id'].unique().tolist()
            existing_orders = env['sale.order'].search_read(
                [('x_external_order_id', 'in', order_ids_in_chunk)],
                ['x_external_order_id']
            )
            existing_order_set = {so['x_external_order_id'] for so in existing_orders}
            
            # Nhóm theo order_id để xử lý từng đơn hàng
            orders_grouped = chunk_df.groupby('order_id')
            orders_created_in_chunk = 0
            
            for order_id, order_df in orders_grouped:
                if order_id in existing_order_set:
                    continue # Bỏ qua đơn hàng đã tồn tại

                header = order_df.iloc[0]
                customer_uid = header['customer_unique_id']
                partner_id = partner_map.get(customer_uid)

                if not partner_id:
                    _logger.warning(f"Bỏ qua đơn hàng {order_id} vì không tìm thấy khách hàng {customer_uid}.")
                    continue
                
                # Tạo sale.order header
                order_vals = {
                    'partner_id': partner_id,
                    'x_external_order_id': order_id,
                    'date_order': pd.to_datetime(header['order_purchase_timestamp'], errors='coerce') or fields.Datetime.now(),
                    'state': 'sale', # Mặc định là sale order
                }
                new_order = env['sale.order'].create(order_vals)
                
                # Tạo sale.order.line
                lines_to_create = []
                for _, line_row in order_df.iterrows():
                    product_pid = line_row['product_id']
                    product_id = product_map.get(product_pid)
                    if not product_id:
                        _logger.warning(f"Bỏ qua dòng sản phẩm {product_pid} trong đơn {order_id} vì không tìm thấy sản phẩm.")
                        continue
                        
                    lines_to_create.append({
                        'order_id': new_order.id,
                        'product_id': product_id,
                        'product_uom_qty': float(line_row.get('order_item_id', 1.0)),
                        'price_unit': float(line_row.get('price', 0.0)),
                    })
                
                if lines_to_create:
                    env['sale.order.line'].create(lines_to_create)

                orders_created_in_chunk += 1
            
            total_orders_created += orders_created_in_chunk
            _logger.info(f"   -> Đã tạo {orders_created_in_chunk} đơn hàng mới.")

            # Commit sau mỗi chunk để lưu tiến trình và giải phóng bộ nhớ
            env.cr.commit()
            _logger.info(f"--- Commit Chunk {chunk_idx + 1} thành công ---")
            gc.collect()

        _logger.info("========================================================")
        _logger.info(f"HOÀN TẤT! TỔNG CỘNG ĐÃ TẠO MỚI: {total_orders_created} ĐƠN HÀNG")
        _logger.info("========================================================")

    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong quá trình import dữ liệu thô: {e}", exc_info=True)
        env.cr.rollback()