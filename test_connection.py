import xmlrpc.client

# ======================================================================
# === SỬA CÁC GIÁ TRỊ NÀY CHO ĐÚNG VỚI CẤU HÌNH CỦA BẠN ===
# ======================================================================
ODOO_URL = 'http://localhost:8069'
ODOO_DB = 'ChurnPredictor_v2'
ODOO_USER = 'admin' # Login/email bạn dùng để đăng nhập vào giao diện Odoo
ODOO_PASSWORD = 'admin' # Mật khẩu bạn dùng để đăng nhập vào giao diện Odoo
# ======================================================================


print("--- BẮT ĐẦU KIỂM TRA KẾT NỐI ODOO ---")
print(f"URL: {ODOO_URL}")
print(f"Database: {ODOO_DB}")
print(f"User: {ODOO_USER}")

try:
    # Bước 1: Kết nối đến server
    print("\nĐang kết nối đến server...")
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
    
    # In ra phiên bản server để xác nhận kết nối mạng thành công
    version = common.version()
    print(f"Kết nối mạng thành công! Phiên bản Odoo Server: {version['server_version']}")

    # Bước 2: Thử xác thực
    print("\nĐang thử xác thực người dùng...")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})

    if uid:
        print("\n==============================================")
        print(f"✅ Xác thực THÀNH CÔNG! User ID của bạn là: {uid}")
        print("==============================================")
        print(">>> Tất cả 4 tham số đều CHÍNH XÁC!")
    else:
        print("\n==============================================")
        print("❌ Xác thực THẤT BẠI!")
        print("==============================================")
        print(">>> Nguyên nhân: Cặp USER/PASSWORD không đúng, hoặc DB không tồn tại.")

except Exception as e:
    print("\n==============================================")
    print(f"❌ ĐÃ XẢY RA LỖI NGHIÊM TRỌNG KHI KẾT NỐI!")
    print("==============================================")
    print(f"Chi tiết lỗi: {e}")
    print(">>> Nguyên nhân có thể là: URL sai, hoặc container Odoo chưa chạy.")