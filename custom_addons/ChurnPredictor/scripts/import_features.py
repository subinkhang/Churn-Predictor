import os
import pandas as pd
import gc
import logging
import math

_logger = logging.getLogger(__name__)

# --- HÀM SO SÁNH ĐỂ KIỂM TRA THAY ĐỔI ---

def _compare_row_and_partner_data(csv_row, odoo_data, fields_to_check):
    """
    So sánh dữ liệu từ một dòng CSV với dữ liệu hiện có trong Odoo.
    Trả về True nếu có ít nhất một trường khác biệt.
    """
    for field_info in fields_to_check:
        odoo_field = field_info['odoo']
        csv_field = field_info['csv']
        dtype = field_info['type']
        
        csv_value = csv_row.get(csv_field)
        odoo_value = odoo_data.get(odoo_field)

        # Chuẩn hóa giá trị trước khi so sánh
        try:
            # Xử lý giá trị NaN từ pandas
            if pd.isna(csv_value):
                csv_value = None

            if dtype == 'float':
                # Đối với float, 0.0, None, False đều coi là giá trị rỗng
                csv_value = float(csv_value) if csv_value is not None else 0.0
                odoo_value = float(odoo_value) if odoo_value else 0.0
                # Dùng isclose để so sánh số thực, tránh lỗi sai số
                if not math.isclose(csv_value, odoo_value, rel_tol=1e-9):
                    return True # Có thay đổi
            elif dtype == 'int':
                csv_value = int(float(csv_value)) if csv_value is not None else 0
                odoo_value = int(odoo_value) if odoo_value else 0
                if csv_value != odoo_value:
                    return True # Có thay đổi
            else: # 'str'
                csv_value = str(csv_value).strip() if csv_value is not None else ''
                odoo_value = str(odoo_value).strip() if odoo_value else ''
                if csv_value != odoo_value:
                    return True # Có thay đổi
        except (ValueError, TypeError):
            # Nếu có lỗi ép kiểu, coi như chúng khác nhau để đảm bảo an toàn
            return True

    return False # Không có thay đổi nào


# --- HÀM IMPORT CHÍNH ---

def import_customer_features(env, filename, chunk_size=1000): # Thay filepath thành filename
    """
    Import/Update các feature từ TÊN FILE.
    """
    # XÂY DỰNG ĐƯỜNG DẪN BÊN TRONG ODOO
    module_path = '/mnt/extra-addons/ChurnPredictor'
    filepath = os.path.join(module_path, 'data_to_import', filename)
    
    _logger.info("========================================================")
    _logger.info(f"BẮT ĐẦU IMPORT/UPDATE FEATURE STORE (HIỆU SUẤT CAO)")
    _logger.info(f"Đang xử lý file: {filepath}")
    _logger.info("========================================================")

    if not os.path.exists(filepath):
        _logger.error(f"LỖI: Không tìm thấy file '{filepath}'.")
        return

    # Định nghĩa các trường cần import/so sánh và kiểu dữ liệu của chúng
    fields_map = [
        {'odoo': 'x_feat_payment_value_sum', 'csv': 'payment_value_sum', 'type': 'float'},
        {'odoo': 'x_feat_payment_value_mean', 'csv': 'payment_value_mean', 'type': 'float'},
        {'odoo': 'x_feat_payment_value_max', 'csv': 'payment_value_max', 'type': 'float'},
        {'odoo': 'x_feat_payment_value_min', 'csv': 'payment_value_min', 'type': 'float'},
        {'odoo': 'x_feat_delivery_days_mean', 'csv': 'delivery_days_mean', 'type': 'float'},
        {'odoo': 'x_feat_delivery_days_max', 'csv': 'delivery_days_max', 'type': 'float'},
        {'odoo': 'x_feat_delivery_delay_days_mean', 'csv': 'delivery_delay_days_mean', 'type': 'float'},
        {'odoo': 'x_feat_delivery_delay_days_max', 'csv': 'delivery_delay_days_max', 'type': 'float'},
        {'odoo': 'x_feat_review_score_mean', 'csv': 'review_score_mean', 'type': 'float'},
        {'odoo': 'x_feat_review_score_min', 'csv': 'review_score_min', 'type': 'float'},
        {'odoo': 'x_feat_review_score_std', 'csv': 'review_score_std', 'type': 'float'},
        {'odoo': 'x_feat_num_items_sum', 'csv': 'num_items_sum', 'type': 'float'},
        {'odoo': 'x_feat_num_items_mean', 'csv': 'num_items_mean', 'type': 'float'},
        {'odoo': 'x_feat_personal_avg_gap', 'csv': 'personal_avg_gap', 'type': 'float'},
        {'odoo': 'x_feat_category_avg_gap', 'csv': 'category_avg_gap', 'type': 'float'},
        {'odoo': 'x_feat_frequency', 'csv': 'frequency', 'type': 'int'},
        {'odoo': 'x_feat_recency', 'csv': 'recency', 'type': 'int'},
        {'odoo': 'x_feat_segment', 'csv': 'segment', 'type': 'int'},
        {'odoo': 'x_feat_payment_type_last', 'csv': 'payment_type_last', 'type': 'str'},
        {'odoo': 'x_feat_customer_state_last', 'csv': 'customer_state_last', 'type': 'str'},
        # Lưu ý: Cột trong CSV là 'product_category_name_english'
        {'odoo': 'x_feat_product_category_name_english_last', 'csv': 'product_category_name_english', 'type': 'str'},
    ]
    odoo_fields_to_read = ['id', 'x_unique_id'] + [f['odoo'] for f in fields_map]
    
    total_created = 0
    total_updated = 0
    total_skipped = 0

    try:
        csv_iterator = pd.read_csv(filepath, chunksize=chunk_size, dtype={'customer_unique_id': str})

        for chunk_idx, df in enumerate(csv_iterator):
            _logger.info(f"--- Đang xử lý Chunk {chunk_idx + 1} ---")

            # 1. ĐỌC DỮ LIỆU HIỆN TẠI TỪ ODOO
            # Lấy toàn bộ dữ liệu feature của các khách hàng có trong chunk này
            current_uids = df['customer_unique_id'].dropna().astype(str).tolist()
            existing_partners_data = env['res.partner'].search_read(
                [('x_unique_id', 'in', current_uids)], odoo_fields_to_read
            )
            # Tạo một map để tra cứu nhanh: {unique_id: {toàn bộ dữ liệu odoo}}
            partner_data_map = {p['x_unique_id']: p for p in existing_partners_data}

            # 2. SO SÁNH, UPDATE VÀ CHUẨN BỊ TẠO MỚI
            partners_to_create_vals = []
            partners_to_update_count = 0
            
            # Chuyển df sang dict để lặp qua
            records = df.to_dict('records')
            
            for row in records:
                unique_id = row.get('customer_unique_id')
                if not unique_id:
                    continue

                # Xây dựng dictionary giá trị mới từ CSV
                vals = {'x_is_imported_data': True}
                for field_info in fields_map:
                    val = row.get(field_info['csv'])
                    if pd.notna(val):
                        if field_info['type'] in ['int', 'float']:
                            vals[field_info['odoo']] = pd.to_numeric(val, errors='coerce')
                        else:
                            vals[field_info['odoo']] = str(val)

                odoo_partner_data = partner_data_map.get(unique_id)

                if odoo_partner_data:
                    # KHÁCH HÀNG ĐÃ TỒN TẠI -> So sánh
                    if _compare_row_and_partner_data(row, odoo_partner_data, fields_map):
                        # CÓ THAY ĐỔI -> Ghi
                        env['res.partner'].browse(odoo_partner_data['id']).write(vals)
                        partners_to_update_count += 1
                    else:
                        # KHÔNG THAY ĐỔI -> Bỏ qua
                        total_skipped += 1
                else:
                    # KHÁCH HÀNG MỚI -> Thêm vào danh sách chờ tạo
                    vals['name'] = f"Customer {unique_id[:8]}"
                    vals['x_unique_id'] = unique_id
                    partners_to_create_vals.append(vals)

            # 3. THỰC THI GHI DỮ LIỆU THEO LÔ
            if partners_to_create_vals:
                env['res.partner'].create(partners_to_create_vals)
                total_created += len(partners_to_create_vals)
                _logger.info(f"   -> Đã tạo {len(partners_to_create_vals)} khách hàng mới.")
            
            total_updated += partners_to_update_count
            _logger.info(f"   -> Đã cập nhật {partners_to_update_count} khách hàng.")
            _logger.info(f"   -> Đã bỏ qua {len(records) - partners_to_update_count - len(partners_to_create_vals)} khách hàng không đổi.")
            
            env.cr.commit()
            _logger.info(f"--- Commit Chunk {chunk_idx + 1} thành công ---")
            gc.collect()

        _logger.info("========================================================")
        _logger.info(f"HOÀN TẤT!")
        _logger.info(f"  - Tổng cộng đã TẠO MỚI: {total_created} khách hàng")
        _logger.info(f"  - Tổng cộng đã CẬP NHẬT: {total_updated} khách hàng")
        _logger.info(f"  - Tổng cộng đã BỎ QUA (không đổi): {total_skipped} khách hàng")
        _logger.info("========================================================")
    
    except Exception as e:
        _logger.error(f"Lỗi nghiêm trọng trong quá trình import features: {e}", exc_info=True)
        env.cr.rollback()