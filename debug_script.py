# D:\ChurnPredictor\debug_script.py
import os
import pandas as pd
import logging

_logger = logging.getLogger(__name__)

# =================================================================
# === CHỈNH SỬA DÒNG NÀY: DÁN ID BẠN ĐÃ COPY VÀO ĐÂY ===
CSV_ID_TO_TEST = "0000f46a9115fa3e82807973968c73c2" 
# =================================================================

def run_debug(env):
    _logger.info("===== BẮT ĐẦU SCRIPT DEBUG ĐỐI CHIẾU ID =====")
    
    # 1. In thông tin chi tiết của ID từ biến chúng ta cung cấp
    _logger.info(f"--- Thông tin ID từ Script ---")
    _logger.info(f"Giá trị: '{CSV_ID_TO_TEST}'")
    _logger.info(f"Kiểu dữ liệu: {type(CSV_ID_TO_TEST)}")
    _logger.info(f"Độ dài: {len(CSV_ID_TO_TEST)}")
    # repr() sẽ hiển thị các ký tự ẩn như \n, \t hoặc khoảng trắng thừa
    _logger.info(f"Dạng biểu diễn (repr): {repr(CSV_ID_TO_TEST)}")
    _logger.info("-" * 30)

    # 2. Tìm kiếm chính xác ID này trong Odoo
    _logger.info(f"Đang tìm kiếm chính xác ID '{CSV_ID_TO_TEST}' trong Odoo...")
    
    partner = env['res.partner'].search_read(
        [('x_unique_id', '=', CSV_ID_TO_TEST)],
        ['id', 'name', 'x_unique_id']
    )

    # 3. In kết quả đối chiếu
    if not partner:
        _logger.error("!!! KẾT QUẢ: KHÔNG TÌM THẤY BẤT KỲ KHÁCH HÀNG NÀO CÓ ID NÀY.")
        _logger.info("Gợi ý: Hãy kiểm tra kỹ xem ID bạn dán vào script có chính xác không, và có tồn tại trong Odoo không.")
    else:
        found_partner = partner[0]
        odoo_id_value = found_partner['x_unique_id']
        
        _logger.info(f"+++ KẾT QUẢ: ĐÃ TÌM THẤY! ID: {found_partner['id']}, Tên: {found_partner['name']}")
        _logger.info(f"--- Thông tin ID từ Odoo ---")
        _logger.info(f"Giá trị: '{odoo_id_value}'")
        _logger.info(f"Kiểu dữ liệu: {type(odoo_id_value)}")
        _logger.info(f"Độ dài: {len(odoo_id_value)}")
        _logger.info(f"Dạng biểu diễn (repr): {repr(odoo_id_value)}")
        _logger.info("-" * 30)

        # 4. So sánh cuối cùng
        if CSV_ID_TO_TEST == odoo_id_value:
            _logger.info(">>> SO SÁNH CUỐI CÙNG: HAI ID TRÙNG KHỚP HOÀN HẢO!")
        else:
            _logger.error(">>> SO SÁNH CUỐI CÙNG: LỖI! Dù tìm thấy nhưng hai ID KHÔNG TRÙNG KHỚP KHI SO SÁNH TRỰC TIẾP!")
            _logger.error("Đây là dấu hiệu của 'kẻ thù vô hình'. Hãy so sánh kỹ 2 dòng 'Dạng biểu diễn (repr)' ở trên.")

    _logger.info("===== KẾT THÚC SCRIPT DEBUG =====")

# Đoạn code để chạy khi gọi từ shell
run_debug(env)