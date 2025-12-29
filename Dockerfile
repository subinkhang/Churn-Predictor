FROM odoo:17.0

USER root

# 1. Cài các thư viện Python
# Lệnh 'apt-get install libfaketime' đã được xóa bỏ hoàn toàn.
COPY ./requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Lệnh tạo symlink cho libfaketime cũng đã được xóa.

USER odoo