FROM odoo:17.0

USER root

# 1. Cài libfaketime và dọn dẹp rác ngay trong một layer để giảm dung lượng
RUN apt-get update && \
    apt-get install -y libfaketime && \
    rm -rf /var/lib/apt/lists/*

# 2. Cài các thư viện Python (giữ nguyên)
COPY ./requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# --- LƯU Ý QUAN TRỌNG VỀ ĐƯỜNG DẪN LIBFAKETIME ---
# Để tiện lợi, chúng ta có thể tạo một symlink (đường dẫn tắt) dễ nhớ
# Vì đường dẫn gốc có thể khác nhau tùy chip (Intel vs Apple M1/M2/ARM)
RUN ln -s /usr/lib/*/faketime/libfaketime.so.1 /usr/lib/libfaketime.so.1

USER odoo

# KHÔNG set ENV LD_PRELOAD và FAKETIME ở đây. 
# Hãy để docker-compose quản lý việc đó.