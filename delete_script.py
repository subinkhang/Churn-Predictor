# Tên file: delete_script.py
# Cách chạy: Get-Content delete_script.py | docker-compose exec -T odoo odoo shell -d ChurnPredictor_v2 ...

import logging
import time

_logger = logging.getLogger(__name__)

# ==============================================================================
# CẤU HÌNH XÓA DỮ LIỆU (HÃY CHỈNH SỬA TẠI ĐÂY)
# ==============================================================================

# 1. Khoảng thời gian của ĐƠN HÀNG cần xóa (Dựa trên field date_order)
# Định dạng: 'YYYY-MM-DD'
DATE_FROM = '2018-01-01'
DATE_TO   = '2018-08-31'  # Set xa về tương lai để xóa hết nếu muốn

# 2. Kích thước lô xóa (Tránh tràn RAM hoặc Lock DB)
BATCH_SIZE = 1000

# 3. CÁC TÙY CHỌN XÓA (True = Có xóa, False = Giữ lại)
DELETE_TRANSACTIONS = True  # Xóa: Orders, Order Lines, Payments, Reviews, Predictions
DELETE_ORPHAN_CUSTOMERS = True # Xóa: Khách hàng có cờ import NHƯNG không còn đơn hàng nào
DELETE_ORPHAN_PRODUCTS  = False # Xóa: Sản phẩm có cờ import NHƯNG không nằm trong đơn hàng nào

# ==============================================================================

def run_delete_process(env):
    _logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    _logger.info("!!! CẢNH BÁO: BẮT ĐẦU QUY TRÌNH XÓA DỮ LIỆU MASS DELETE !!!")
    _logger.info(f"!!! Phạm vi ngày: {DATE_FROM} đến {DATE_TO}")
    _logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    
    # 1. Xóa dữ liệu giao dịch (Transaction Data)
    if DELETE_TRANSACTIONS:
        delete_transactional_data(env)
    
    # 2. Dọn dẹp dữ liệu danh mục (Master Data) bị mồ côi sau khi xóa giao dịch
    if DELETE_ORPHAN_CUSTOMERS:
        delete_orphan_customers(env)
        
    if DELETE_ORPHAN_PRODUCTS:
        delete_orphan_products(env)

    _logger.info(">>> QUY TRÌNH XÓA HOÀN TẤT <<<")


def delete_transactional_data(env):
    """
    Xóa Sale Orders và các dữ liệu vệ tinh.
    CẬP NHẬT: Hủy đơn hàng trước khi xóa để tránh lỗi Odoo UserError.
    """
    _logger.info(f"--- BƯỚC 1: Tìm kiếm Đơn hàng (Sale Order) từ {DATE_FROM} đến {DATE_TO} ---")
    
    domain = [
        ('x_kaggle_id', '!=', False),
        ('date_order', '>=', DATE_FROM),
        ('date_order', '<=', DATE_TO)
    ]
    
    total_orders = env['sale.order'].search_count(domain)
    _logger.info(f"Tìm thấy {total_orders} đơn hàng cần xử lý.")
    
    if total_orders == 0:
        return

    while True:
        # Lấy 1 lô đơn hàng
        orders = env['sale.order'].search(domain, limit=BATCH_SIZE)
        if not orders:
            break
            
        order_ids = orders.ids
        count = len(order_ids)
        _logger.info(f"Đang xử lý lô {count} đơn hàng...")
        
        try:
            # 1. Xóa các dữ liệu vệ tinh trước
            partner_ids = orders.mapped('partner_id.id')
            if partner_ids:
                # Xóa Prediction
                env['churn.prediction'].search([('customer_id', 'in', partner_ids)]).unlink()
            
            # Xóa Rating
            env['rating.rating'].search([
                ('res_model', '=', 'sale.order'),
                ('res_id', 'in', order_ids)
            ]).unlink()
                
            # Xóa Payments
            env['payment.transaction'].search([
                ('sale_order_ids', 'in', order_ids)
            ]).unlink()
            
            # 2. QUAN TRỌNG: CHUYỂN TRẠNG THÁI VỀ 'CANCEL' ĐỂ ĐƯỢC PHÉP XÓA
            # Dùng write trực tiếp để cưỡng chế (nhanh hơn gọi action_cancel)
            orders.write({'state': 'cancel'})
            
            # 3. Xóa Đơn hàng
            orders.unlink()
            
            env.cr.commit() # Commit thành công
            _logger.info(f"   -> Đã HỦY và XÓA thành công lô {count} đơn hàng.")
            
        except Exception as e:
            env.cr.rollback()
            _logger.error(f"Lỗi khi xóa lô đơn hàng: {e}", exc_info=True)
            # Nếu lỗi, thử xóa từng cái một hoặc break để debug
            break


def delete_orphan_customers(env):
    """
    Xóa các khách hàng được import (có x_unique_id) nhưng KHÔNG CÒN đơn hàng nào.
    """
    _logger.info("--- BƯỚC 2: Dọn dẹp Khách hàng mồ côi (Orphaned Customers) ---")
    
    # Tìm khách hàng có cờ import (hoặc x_unique_id)
    # VÀ không có đơn hàng nào (sale_order_count = 0 hoặc check id)
    
    # Cách tìm nhanh: Lấy tất cả khách import, sau đó lọc.
    # Nhưng để tối ưu, ta dùng domain:
    domain = [('x_unique_id', '!=', False)]
    
    # Đếm sơ bộ
    total_imported = env['res.partner'].search_count(domain)
    _logger.info(f"Đang quét trong tổng số {total_imported} khách hàng import...")

    while True:
        # Lấy batch khách hàng import
        partners = env['res.partner'].search(domain, limit=BATCH_SIZE)
        if not partners:
            break
            
        # Lọc ra những người KHÔNG có đơn hàng (sale_order_ids rỗng)
        # Lưu ý: sale_order_ids là One2many
        orphans = partners.filtered(lambda p: not p.sale_order_ids)
        
        if not orphans:
            # Nếu trong lô này ai cũng có đơn, thì bỏ qua lô này (để không lặp lại search, ta cần cẩn thận)
            # Vì search luôn trả về kết quả giống nhau nếu không xóa.
            # Mẹo: Nếu không xóa được ai trong lô này, ta phải skip nó trong lần search sau.
            # Tuy nhiên, cách đơn giản nhất cho script 1 lần là:
            # Search những thằng KHÔNG có order ngay từ đầu (nhưng Odoo domain search one2many empty hơi khó viết trực tiếp)
            
            # Cách xử lý vòng lặp vô tận:
            # Nếu lô này không có ai để xóa, ta break loop hoặc dùng offset (nhưng offset với unlink nguy hiểm).
            # Tốt nhất: Xóa xong 1 lô -> commit. Nếu lô đó không xóa được ai -> Break hoặc logic thông minh hơn.
            _logger.info("Lô hiện tại toàn bộ khách đều còn đơn hàng. Dừng quét khách hàng.")
            break
            
        count = len(orphans)
        try:
            orphans.unlink()
            env.cr.commit()
            _logger.info(f"   -> Đã xóa {count} khách hàng mồ côi.")
            
            # Nếu số lượng orphans < batch_size, có thể vẫn còn partner có đơn hàng trong batch search
            # nhưng ta không xóa họ. Lần search tiếp theo họ vẫn xuất hiện.
            # Để tránh loop vô tận, ta kiểm tra: nếu số lượng partners tìm được > số lượng orphans đã xóa
            # nghĩa là có những partner KHÔNG xóa được -> Lần sau search sẽ lại ra họ.
            if len(partners) > len(orphans):
                 _logger.info("Đã đến giới hạn các khách hàng có thể xóa (số còn lại đều có đơn hàng).")
                 break
                 
        except Exception as e:
            env.cr.rollback()
            _logger.error(f"Lỗi khi xóa khách hàng: {e}")
            break

def delete_orphan_products(env):
    """
    Xóa sản phẩm import không được dùng trong đơn hàng nào.
    """
    _logger.info("--- BƯỚC 3: Dọn dẹp Sản phẩm mồ côi ---")
    # Tương tự logic khách hàng, tìm product.template có x_kaggle_id
    # Check xem có sale_line_ids (liên kết qua product.product) hay không.
    # Phần này khá phức tạp do quan hệ Template -> Variant -> Sale Line.
    # Tạm thời để pass nếu không thực sự cần thiết.
    _logger.info("Chức năng xóa sản phẩm đang tắt để đảm bảo an toàn.")
    pass

if 'env' in locals():
    run_delete_process(env)