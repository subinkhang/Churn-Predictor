ChurnPredictor/
├── __manifest__.py                 # 1. File kê khai Module
├── controllers/
│   └── main.py                     # 2. Lớp Xử lý Yêu cầu Web (HTTP)
├── data/
│   ├── cron.xml                    # 3. Định nghĩa Tác vụ Tự động
│   └── mail_templates.xml          #    Định nghĩa Mẫu Email
├── models/
│   ├── res_partner.py              # 4. Lớp Logic chính - Mở rộng Model Khách hàng
│   ├── churn_prediction.py         #    Model lưu trữ Lịch sử Dự báo
│   ├── churn_model_version.py      #    Model quản lý các Phiên bản Mô hình
│   ├── kaggle_connector.py         # 5. Lớp Dịch vụ - Giao tiếp với Kaggle
│   └── ml_assets/                  # 6. Kho lưu trữ các Tạo tác AI
│       └── <timestamp>/
│           └── churn_model.joblib
├── security/
│   └── ir.model.access.csv         # 7. Định nghĩa Quyền Truy cập Dữ liệu
├── static/
│   └── src/
│       ├── components/             # 8. Các thành phần Giao diện (JavaScript & XML)
│       │   ├── churn_dashboard.js
│       │   └── ...
│       └── ...
├── views/
│   ├── dashboard_views.xml         # 9. Định nghĩa Bố cục Giao diện
│   └── res_partner_views.xml       #    Tùy chỉnh Giao diện Khách hàng
└── wizards/
    └── ...                         # (Ví dụ: upload_csv_wizard.py)