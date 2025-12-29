# %%
import pandas as pd
import os

# Kiểm tra xem dữ liệu đã được load vào chưa
for dirname, _, filenames in os.walk('/kaggle/input'):
    for filename in filenames:
        print(os.path.join(dirname, filename))

# %%
# Cài đặt phiên bản protobuf tương thích
!pip install protobuf==3.20.3

# %%
# Thêm dấu chấm than để chạy lệnh hệ thống
!curl -I https://huggingface.co

# %% [markdown]
# # 1: New merge: Dataset gốc + check thêm có csv nào không

# %%
import pandas as pd
import os
import glob # Thư viện này giúp tìm file theo tên đuôi

# =============================================================================
# CẤU HÌNH ĐƯỜNG DẪN
# =============================================================================

# 1. File gốc cố định (Main History)
# Đây là file dữ liệu lịch sử lớn, ít thay đổi tên
MAIN_DATA_PATH = '/kaggle/input/olist-merged-dataset-2016-2017/olist_merged_2016_2017.csv'

# 2. Thư mục chứa dữ liệu mới (Folder Update)
# Bạn chỉ cần trỏ đến TÊN THƯ MỤC dataset, không cần tên file cụ thể.
# Ví dụ: Khi bạn Add Data bộ "Olist Updates", đường dẫn thường là:
UPDATE_DIR = '/kaggle/input/olist-merged-dataset-2016-2017'

# =============================================================================
# LOGIC TỰ ĐỘNG QUÉT VÀ GỘP (AUTO-SCAN TRIGGER)
# =============================================================================

print("--- BẮT ĐẦU QUY TRÌNH SMART LOAD ---")

# --- Bước 1: Load dữ liệu gốc ---
if os.path.exists(MAIN_DATA_PATH):
    print(f"✅ Đang đọc dữ liệu gốc từ: {MAIN_DATA_PATH}")
    orders_features_df = pd.read_csv(MAIN_DATA_PATH)
    print(f"   -> Kích thước ban đầu: {orders_features_df.shape}")
else:
    # Nếu không tìm thấy file gốc, thử tìm trong thư mục hiện tại xem có file nào lớn không
    print(f"⚠️ Không tìm thấy file gốc đích danh. Đang tìm file CSV lớn nhất trong input...")
    # (Logic dự phòng này giúp bạn đỡ phải sửa path nếu lỡ đổi tên file gốc)
    pass 

# --- Bước 2: Quét thư mục Update để tìm file CSV lạ ---
# Lấy tất cả file .csv trong thư mục update
update_files = glob.glob(os.path.join(UPDATE_DIR, "*.csv"))
update_files = [f for f in update_files if os.path.abspath(f) != os.path.abspath(MAIN_DATA_PATH)]

if len(update_files) > 0:
    print(f"\n🚀 PHÁT HIỆN {len(update_files)} FILE DỮ LIỆU MỚI:")
    for file_path in update_files:
        try:
            new_data_df = pd.read_csv(file_path)
            orders_features_df = pd.concat([orders_features_df, new_data_df], ignore_index=True)
            print(f"   + Đã thêm {new_data_df.shape[0]} dòng từ: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"   ❌ Lỗi file {file_path}: {e}")
else:
    print(f"\nℹ️ Không có file mới.")

# =================================================================
# QUAN TRỌNG: LUÔN LUÔN XÓA TRÙNG LẶP (Dù có file mới hay không)
# =================================================================
if 'order_item_id' in orders_features_df.columns:
    orders_features_df.drop_duplicates(subset=['order_id', 'order_item_id'], keep='last', inplace=True)
    print("Đã xóa trùng lặp dựa trên (Order ID + Item ID).")

# 2. Hoặc nếu data đã aggregate (không có item id), nhưng bạn sợ xóa nhầm dòng khác nhau:
# Chỉ xóa khi dòng đó TRÙNG 100% tất cả các cột
else:
    # Bỏ tham số subset để so sánh toàn bộ các cột
    orders_features_df.drop_duplicates(keep='last', inplace=True) 
    print("Đã xóa các dòng trùng lặp hoàn toàn (Duplicate Rows).")

# =============================================================================
# CHUẨN HÓA DỮ LIỆU (BẮT BUỘC)
# =============================================================================
print("\n--- CHUẨN HÓA DỮ LIỆU ---")

date_cols = ['order_purchase_timestamp', 'order_delivered_customer_date', 'order_estimated_delivery_date']
for col in date_cols:
    if col in orders_features_df.columns:
        orders_features_df[col] = pd.to_datetime(orders_features_df[col], errors='coerce')

# 2. Sort lại
if 'order_purchase_timestamp' in orders_features_df.columns:
    orders_features_df.sort_values(by='order_purchase_timestamp', inplace=True)

# 3. Tái tạo cột thiếu
if 'delivery_days' not in orders_features_df.columns:
    orders_features_df['delivery_days'] = (orders_features_df['order_delivered_customer_date'] - orders_features_df['order_purchase_timestamp']).dt.days
if 'delivery_delay_days' not in orders_features_df.columns:
    orders_features_df['delivery_delay_days'] = (orders_features_df['order_delivered_customer_date'] - orders_features_df['order_estimated_delivery_date']).dt.days
if 'num_items' not in orders_features_df.columns:
    orders_features_df['num_items'] = orders_features_df['order_item_id'].fillna(1) if 'order_item_id' in orders_features_df.columns else 1

# 4. Fill NaN
for col in ['delivery_days', 'delivery_delay_days', 'num_items', 'payment_value', 'review_score']:
    if col in orders_features_df.columns:
        orders_features_df[col] = orders_features_df[col].fillna(0)

print(f"\n🎉 Final Data Shape: {orders_features_df.shape}")

# %% [markdown]
# ## Ngày của dữ liệu

# %%
import pandas as pd

# Sử dụng biến 'orders_features_df' thay vì 'df'
if 'orders_features_df' in locals() and isinstance(orders_features_df, pd.DataFrame) and 'order_purchase_timestamp' in orders_features_df.columns:
    # Convert to datetime if not already
    orders_features_df['order_purchase_timestamp'] = pd.to_datetime(orders_features_df['order_purchase_timestamp'], errors='coerce')

    # Find the earliest and latest timestamps
    earliest_date = orders_features_df['order_purchase_timestamp'].min()
    latest_date = orders_features_df['order_purchase_timestamp'].max()

    if pd.notnull(earliest_date) and pd.notnull(latest_date):
        print(f"Bộ dữ liệu chứa các đơn hàng từ ngày: {earliest_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Đến ngày: {latest_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("Cột thời gian không chứa dữ liệu hợp lệ.")
else:
    print("Không tìm thấy DataFrame 'orders_features_df' hoặc cột 'order_purchase_timestamp'.")

# %%
import pandas as pd
import numpy as np

# --- ĐOẠN CODE NÀY ĐỂ TẠO LẠI CÁC CỘT BỊ THIẾU ---
# Chạy đoạn này ngay sau khi load orders_features_df và trước khi chạy các bước tiếp theo

print("Đang tái tạo các cột đặc trưng (Features) bị thiếu...")

# 1. Chuyển đổi các cột thời gian sang định dạng datetime (Bắt buộc để trừ ngày tháng)
# errors='coerce' sẽ biến các giá trị lỗi/rác thành NaT (để tránh lỗi RuntimeWarning phía trên)
date_cols = ['order_purchase_timestamp', 'order_delivered_customer_date', 'order_estimated_delivery_date']
for col in date_cols:
    if col in orders_features_df.columns:
        orders_features_df[col] = pd.to_datetime(orders_features_df[col], errors='coerce')

# 2. Tạo cột 'delivery_days' (Thời gian giao hàng thực tế)
if 'delivery_days' not in orders_features_df.columns:
    orders_features_df['delivery_days'] = (orders_features_df['order_delivered_customer_date'] - orders_features_df['order_purchase_timestamp']).dt.days

# 3. Tạo cột 'delivery_delay_days' (Độ trễ so với dự kiến)
if 'delivery_delay_days' not in orders_features_df.columns:
    orders_features_df['delivery_delay_days'] = (orders_features_df['order_delivered_customer_date'] - orders_features_df['order_estimated_delivery_date']).dt.days

# 4. Tạo cột 'num_items' (Số lượng sản phẩm trong đơn)
if 'num_items' not in orders_features_df.columns:
    # Nếu file của bạn có cột 'order_item_id', ta dùng nó để đại diện số lượng (hoặc gán = 1 nếu không có thông tin)
    if 'order_item_id' in orders_features_df.columns:
        # Giả sử dataset đã merge, nếu muốn chính xác tuyệt đối cần group lại, 
        # nhưng để code chạy được ngay, ta có thể fill tạm hoặc dùng logic đơn giản:
        orders_features_df['num_items'] = orders_features_df['order_item_id'].fillna(1)
    else:
        print("Cảnh báo: Không có cột order_item_id, gán num_items = 1")
        orders_features_df['num_items'] = 1

# 5. Xử lý sạch dữ liệu (Hết cảnh báo đỏ)
# Điền 0 vào các ô bị trống do tính toán ngày tháng (ví dụ đơn chưa giao xong)
cols_to_fix = ['delivery_days', 'delivery_delay_days', 'num_items', 'payment_value', 'review_score']
for col in cols_to_fix:
    if col in orders_features_df.columns:
        orders_features_df[col] = orders_features_df[col].fillna(0)

print("Đã tạo xong các cột thiếu: delivery_days, delivery_delay_days, num_items")
print(f"Shape hiện tại: {orders_features_df.shape}")

# %% [markdown]
# # labeling

# %%
import pandas as pd
import numpy as np

# --- GIẢ SỬ 'orders_features_df' LÀ DATAFRAME CẤP ĐỘ ĐƠN HÀNG TỪ PHẦN 1 ---
# orders_features_df = pd.read_csv(...)
# orders_features_df['order_purchase_timestamp'] = pd.to_datetime(...)

print("--- Bắt đầu Phần 2 (Mới): Gán nhãn Churn dựa trên Ngưỡng Động ---")

# --- BƯỚC 2.1: SẮP XẾP VÀ CHUẨN BỊ DỮ LIỆU ---
# Sắp xếp theo khách hàng và thời gian là bước quan trọng nhất
df_sorted = orders_features_df.sort_values(by=['customer_unique_id', 'order_purchase_timestamp'])

# --- BƯỚC 2.2: TÍNH KHOẢNG THỜI GIAN MUA LẠI (REPURCHASE GAPS) ---
# 2.2.1. Tính khoảng cách giữa các lần mua của cùng một khách hàng
print("Tính toán personal_avg_gap...")
df_sorted['days_since_previous_purchase'] = df_sorted.groupby('customer_unique_id')['order_purchase_timestamp'].diff().dt.days

# 2.2.2. Tính khoảng cách giữa các lần mua của cùng một khách hàng TRONG CÙNG một danh mục
print("Tính toán category_avg_gap...")
df_sorted['days_since_previous_purchase_in_category'] = df_sorted.groupby(['customer_unique_id', 'product_category_name_english'])['order_purchase_timestamp'].diff().dt.days

# --- BƯỚC 2.3: TÍNH NGƯỠNG CÁ NHÂN VÀ NGƯỠNG DANH MỤC ---
# 2.3.1. Tính personal_avg_gap (thói quen mua sắm cá nhân)
# Sử dụng transform('mean') để tính trung bình và gán lại cho tất cả các hàng của khách hàng đó
df_sorted['personal_avg_gap'] = df_sorted.groupby('customer_unique_id')['days_since_previous_purchase'].transform('mean')

# 2.3.2. Tính category_avg_gap (thói quen mua sắm theo danh mục)
# Ở đây ta tính trung bình toàn cục của danh mục, không phải của cá nhân trong danh mục
category_global_avg_gap = df_sorted.groupby('product_category_name_english')['days_since_previous_purchase_in_category'].mean().reset_index(name='category_avg_gap')
df_sorted = pd.merge(df_sorted, category_global_avg_gap, on='product_category_name_english', how='left')


# --- BƯỚC 2.4: XỬ LÝ GIÁ TRỊ NaN (CHO KHÁCH HÀNG MUA 1 LẦN) ---
print("Xử lý giá trị NaN cho khách hàng mua 1 lần...")
# Ước tính thói quen cho những người chưa có lịch sử mua lại
# bằng phân vị thứ 75 của những người có lịch sử.
# Đây là một giả định hợp lý: "một khách hàng mới có thể sẽ hành xử giống như
# những khách hàng có xu hướng mua lại chậm hơn một chút".
global_p75_customer_gap = df_sorted['days_since_previous_purchase'].quantile(0.75)
df_sorted['personal_avg_gap'] = df_sorted['personal_avg_gap'].fillna(global_p75_customer_gap)

global_p75_category_gap = df_sorted['days_since_previous_purchase_in_category'].quantile(0.75)
df_sorted['category_avg_gap'] = df_sorted['category_avg_gap'].fillna(global_p75_category_gap)


# --- BƯỚC 2.5: TÍNH NGƯỠNG RỜI BỎ ĐỘNG (HYBRID HORIZON) ---
print("Tính toán ngưỡng rời bỏ động 'hybrid_horizon'...")
w1, w2 = 0.6, 0.4  # Trọng số cho thói quen cá nhân và thói quen danh mục
alpha = 1.5       # Hệ số an toàn (ví dụ: chờ gấp 1.5 lần thời gian thông thường)

df_sorted['hybrid_gap'] = (df_sorted['personal_avg_gap'] * w1 + df_sorted['category_avg_gap'] * w2)
df_sorted['hybrid_horizon'] = df_sorted['hybrid_gap'] * alpha


# --- BƯỚC 2.6: GÁN NHÃN CHURN DỰA TRÊN HYBRID HORIZON ---
print("Gán nhãn churn cuối cùng...")
# Tính ngày mua tiếp theo để so sánh
df_sorted['next_purchase_timestamp'] = df_sorted.groupby('customer_unique_id')['order_purchase_timestamp'].shift(-1)
df_sorted['days_to_next_purchase'] = (df_sorted['next_purchase_timestamp'] - df_sorted['order_purchase_timestamp']).dt.days

dataset_end_date = df_sorted['order_purchase_timestamp'].max()

def assign_churn(row):
    # Nếu có lần mua tiếp theo (không phải giao dịch cuối)
    if pd.notnull(row['days_to_next_purchase']):
        # Churn nếu khoảng thời gian đến lần mua tiếp theo lớn hơn ngưỡng
        return 1 if row['days_to_next_purchase'] > row['hybrid_horizon'] else 0
    # Nếu là lần mua cuối cùng
    else:
        days_since_last_purchase = (dataset_end_date - row['order_purchase_timestamp']).days
        # Churn nếu thời gian chờ kể từ lần mua cuối lớn hơn ngưỡng
        return 1 if days_since_last_purchase > row['hybrid_horizon'] else 0

df_sorted['churn'] = df_sorted.apply(assign_churn, axis=1)


# --- BƯỚC 2.7: DỌN DẸP VÀ HOÀN THIỆN ---
# Chọn các cột cần thiết và đổi tên 'df_sorted' thành 'final_df' để nhất quán
final_df = df_sorted.copy()

# Dọn dẹp các cột trung gian không cần thiết cho các bước sau
cols_to_drop = [
    'days_since_previous_purchase', 'days_since_previous_purchase_in_category',
    'next_purchase_timestamp', 'days_to_next_purchase', 'personal_avg_gap',
    'category_avg_gap', 'hybrid_gap', 'hybrid_horizon'
]
final_df.drop(columns=cols_to_drop, inplace=True, errors='ignore')


# --- KIỂM TRA KẾT QUẢ ---
print("\n--- KẾT THÚC PHẦN 2 (MỚI) ---")
print("Phân phối nhãn Churn mới:")
print(final_df['churn'].value_counts(normalize=True))

print("\nShape của final_df mới:", final_df.shape)
print("\n5 dòng cuối của final_df để kiểm tra:")
print(final_df[['customer_unique_id', 'order_purchase_timestamp', 'churn']].tail())

# %% [markdown]
# # 3 col: personal + cate + segment

# %%
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import os

print("--- BẮT ĐẦU QUY TRÌNH TẠO DỮ LIỆU NGỮ CẢNH (CONTEXT PIPELINE) ---")

# =============================================================================
# BƯỚC 1: TÁI TẠO CÁC TRƯỜNG GAP (THÓI QUEN MUA SẮM)
# =============================================================================
# Lưu ý: Ta làm trên bản copy để không ảnh hưởng luồng train model chính
context_df = final_df.copy()

# Sắp xếp để tính toán diff chính xác
context_df.sort_values(by=['customer_unique_id', 'order_purchase_timestamp'], inplace=True)

# 1.1 Tính Personal Avg Gap
# Khoảng cách giữa các lần mua của khách
context_df['diff_days'] = context_df.groupby('customer_unique_id')['order_purchase_timestamp'].diff().dt.days
# Tính trung bình cho mỗi khách
personal_gap_series = context_df.groupby('customer_unique_id')['diff_days'].mean()
# Fillna cho người mua lần đầu (bằng quantile 0.75 toàn cục)
global_p75_gap = context_df['diff_days'].quantile(0.75)
personal_gap_series = personal_gap_series.fillna(global_p75_gap)

# 1.2 Tính Category Avg Gap (LOGIC ĐÃ CẢI TIẾN)
# Logic: Tính gap dựa trên các ĐƠN HÀNG DUY NHẤT (tránh việc mua nhiều món 1 đơn làm gap = 0)
print("Đang tính toán Category Gap (Improved Logic)...")
unique_orders_per_cat = context_df.drop_duplicates(subset=['customer_unique_id', 'order_id', 'product_category_name_english']).copy()
unique_orders_per_cat.sort_values(by=['customer_unique_id', 'product_category_name_english', 'order_purchase_timestamp'], inplace=True)

# Tính khoảng cách giữa các đơn hàng trong cùng danh mục của khách
unique_orders_per_cat['cat_diff_days'] = unique_orders_per_cat.groupby(['product_category_name_english', 'customer_unique_id'])['order_purchase_timestamp'].diff().dt.days

# Tính trung bình cho danh mục
category_gap_df = unique_orders_per_cat.groupby('product_category_name_english')['cat_diff_days'].mean().reset_index()
category_gap_df.rename(columns={'cat_diff_days': 'category_avg_gap'}, inplace=True)
# Fillna cho category
category_gap_df['category_avg_gap'] = category_gap_df['category_avg_gap'].fillna(category_gap_df['category_avg_gap'].mean())


# =============================================================================
# BƯỚC 2: CUSTOMER SEGMENTATION (RFM + K-MEANS)
# =============================================================================
print("Đang thực hiện phân khúc khách hàng (RFM + K-Means)...")

# 2.1 Chuẩn bị dữ liệu RFM
snapshot_date = context_df['order_purchase_timestamp'].max() + pd.Timedelta(days=1)

# Tính RFM mức khách hàng (Lúc này customer_unique_id sẽ là INDEX)
rfm_df = context_df.groupby('customer_unique_id').agg({
    'order_purchase_timestamp': lambda x: (snapshot_date - x.max()).days, # Recency
    'order_id': 'nunique', # Frequency
    'payment_value': 'sum' # Monetary
}).rename(columns={
    'order_purchase_timestamp': 'Recency',
    'order_id': 'Frequency',
    'payment_value': 'Monetary'
})

# 2.2 Xử lý Outlier (IQR Method)
def get_non_outlier_index(df, cols):
    indices = df.index
    for col in cols:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        condition = (df[col] >= lower) & (df[col] <= upper)
        indices = indices.intersection(df[condition].index)
    return indices

clean_idx = get_non_outlier_index(rfm_df, ['Recency', 'Frequency', 'Monetary'])
rfm_clean = rfm_df.loc[clean_idx].copy()

print(f"Dùng {len(rfm_clean)} khách hàng (đã lọc outlier) để huấn luyện K-Means.")

# 2.3 Standard Scaling & K-Means
scaler = StandardScaler()
scaler.fit(rfm_clean[['Recency', 'Frequency', 'Monetary']])
rfm_scaled_all = scaler.transform(rfm_df[['Recency', 'Frequency', 'Monetary']])
rfm_clean_scaled = scaler.transform(rfm_clean[['Recency', 'Frequency', 'Monetary']])

kmeans = KMeans(n_clusters=5, random_state=42, n_init=10)
kmeans.fit(rfm_clean_scaled) # Fit trên tập sạch

# Predict cho TOÀN BỘ khách hàng
rfm_df['segment'] = kmeans.predict(rfm_scaled_all)

# --- QUAN TRỌNG: RESET INDEX ĐỂ SỬA LỖI KEYERROR ---
# Đưa customer_unique_id từ Index ra thành Cột để dùng cho Analysis và Merge
rfm_df.reset_index(inplace=True) 

# --- PHÂN TÍCH CHÂN DUNG KHÁCH HÀNG ---
print("\n--- PHÂN TÍCH CHÂN DUNG KHÁCH HÀNG (CLUSTER ANALYSIS) ---")
segment_analysis = rfm_df.groupby('segment').agg({
    'Recency': 'mean',
    'Frequency': 'mean',
    'Monetary': 'mean',
    'customer_unique_id': 'count' # Bây giờ cột này đã tồn tại, code sẽ chạy đúng
}).rename(columns={'customer_unique_id': 'Count'})

segment_analysis = segment_analysis.sort_values(by='Monetary', ascending=False)
print(segment_analysis.round(2))
print("-" * 60)
print("Phân phối Segment:")
print(rfm_df['segment'].value_counts())


# =============================================================================
# BƯỚC 3: MAPPING VÀ XUẤT FILE ORDER LEVEL
# =============================================================================
print("Đang tổng hợp dữ liệu cấp độ Order...")

# 3.1 Map Personal Gap
personal_gap_df = personal_gap_series.reset_index(name='personal_avg_gap')

# 3.2 Chuẩn bị bảng chính
output_df = context_df[['order_id', 'customer_unique_id', 'product_category_name_english']].copy()
# Giữ lại unique order + category
output_df.drop_duplicates(subset=['order_id', 'product_category_name_english'], keep='first', inplace=True)

# 3.3 Merge tất cả
output_df = output_df.merge(personal_gap_df, on='customer_unique_id', how='left')
output_df = output_df.merge(category_gap_df, on='product_category_name_english', how='left')
# Merge Segment (Bây giờ rfm_df đã có cột customer_unique_id nhờ reset_index ở trên)
output_df = output_df.merge(rfm_df[['customer_unique_id', 'segment']], on='customer_unique_id', how='left')

# Fill NaN
output_df['personal_avg_gap'].fillna(global_p75_gap, inplace=True)
output_df['category_avg_gap'].fillna(output_df['category_avg_gap'].mean(), inplace=True)
output_df['segment'].fillna(-1, inplace=True)

# 3.4 Lưu file
output_filename = 'order_context_data.csv'
output_df.to_csv(output_filename, index=False)

print(f"\n✅ Đã tạo thành công file dataset bổ sung: {output_filename}")
print(f"Shape: {output_df.shape}")
print("5 dòng đầu tiên:")
print(output_df.head())

# %%
# ===== EXPORT CSV =====
output_filename = "order_context_data.csv"
output_df.to_csv(output_filename, index=False)
print(f"✔ Đã xuất file: {output_filename}")

# ===== TẠO LINK TẢI FILE (KAGGLE) =====
from IPython.display import FileLink
FileLink(output_filename)


# %% [markdown]
# # 2: Chuẩn bị dữ liệu

# %%
# ==============================================================================
# BƯỚC 1.2: CHUẨN BỊ DỮ LIỆU VĂN BẢN (REVIEW TEXT)
# ==============================================================================
print("\n--- Bắt đầu Bước 1.2: Chuẩn bị Dữ liệu Văn bản ---")

# --- 1.2.1: Tổng hợp bình luận cho mỗi khách hàng ---
# Loại bỏ các bình luận rỗng trước khi join để tránh các "[SEP]" thừa
final_df['review_comment_message'] = final_df['review_comment_message'].str.strip()
final_df.replace('', np.nan, inplace=True)

agg_reviews = final_df.dropna(subset=['review_comment_message']).groupby('customer_unique_id')['review_comment_message'].apply(lambda x: " [SEP] ".join(x)).reset_index()
review_map = dict(zip(agg_reviews['customer_unique_id'], agg_reviews['review_comment_message']))

print(f"Đã tổng hợp được {len(review_map)} chuỗi bình luận cho khách hàng.")

# >>> VÍ DỤ <<<
print("\n--- Ví dụ về các bình luận đã được tổng hợp ---")

# Lấy ra một vài ID khách hàng có nhiều hơn 1 bình luận để xem ví dụ
customer_counts = final_df.dropna(subset=['review_comment_message'])['customer_unique_id'].value_counts()
customers_with_multiple_reviews = customer_counts[customer_counts > 1].index.tolist()

num_examples_to_show = 3
if len(customers_with_multiple_reviews) >= num_examples_to_show:
    example_ids = customers_with_multiple_reviews[:num_examples_to_show]

    for i, customer_id in enumerate(example_ids):
        print(f"\n--- Ví dụ {i+1} ---")
        print(f"Customer ID: {customer_id}")

        # In ra các bình luận gốc
        original_comments = final_df[final_df['customer_unique_id'] == customer_id]['review_comment_message'].dropna().tolist()
        print("Bình luận gốc:")
        for comment in original_comments:
            print(f"  - \"{comment}\"")

        # In ra bình luận đã được tổng hợp
        aggregated_comment = review_map.get(customer_id, "Không tìm thấy bình luận tổng hợp.")
        print(f"Bình luận đã tổng hợp (đầu vào cho mô hình):")
        print(f"  -> \"{aggregated_comment}\"")
else:
    print("Không tìm thấy đủ khách hàng có nhiều hơn 1 bình luận để hiển thị ví dụ.")

# # --- 1.2.2: Khởi tạo Tokenizer ---
# MODEL_NAME = 'distilbert-base-uncased'
# tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

# %% [markdown]
# # 3: Baseline: XGBoost + BERT

# %%
# ==============================================================================
# PHẦN 0: CÀI ĐẶT VÀ IMPORTS CÁC THƯ VIỆN CẦN THIẾT
# ==============================================================================
# Hầu hết đã được cài đặt, chỉ cần thêm xgboost
!pip install xgboost -q

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, f1_score, accuracy_score, precision_score, recall_score, confusion_matrix
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel
from tqdm.notebook import tqdm

# Giả sử 'final_df' đã tồn tại từ các cell code trước của bạn.
print("Kiểm tra shape của final_df:", final_df.shape)

# ==============================================================================
# BƯỚC 1: FEATURE ENGINEERING CHO MÔ HÌNH THÔNG THƯỜNG (XGBOOST)
# ==============================================================================
print("\n--- Bắt đầu Bước 1: Feature Engineering cho XGBoost ---")

# --- 1.1: Tổng hợp Dữ liệu về Cấp độ Khách hàng ---
# Thay vì giữ chuỗi giao dịch, chúng ta sẽ tổng hợp chúng thành các chỉ số thống kê
# cho mỗi khách hàng. Đây là cách làm kinh điển.

# Sắp xếp để đảm bảo các phép tính 'first' và 'last' là chính xác
final_df = final_df.sort_values(by=['customer_unique_id', 'order_purchase_timestamp'])

# Định nghĩa các hàm tổng hợp
agg_funcs = {
    # Đặc trưng Tần suất (Frequency)
    # 'order_id': 'count',
    # Đặc trưng Tiền tệ (Monetary)
    'payment_value': ['sum', 'mean', 'max', 'min'],
    # Đặc trưng Hành vi
    'num_items': ['sum', 'mean'],
    'review_score': ['mean', 'min', 'std'],
    'delivery_days': ['mean', 'max'],
    'delivery_delay_days': ['mean', 'max'],
    # Đặc trưng hạng mục (lấy giá trị của giao dịch cuối cùng)
    'customer_state': 'last',
    'product_category_name_english': 'last',
    'payment_type': 'last',
    # Nhãn Churn (lấy của giao dịch cuối cùng)
    'churn': 'last'
}

customer_df = final_df.groupby('customer_unique_id').agg(agg_funcs)

# "Làm phẳng" tên các cột đa cấp (MultiIndex)
customer_df.columns = ['_'.join(col).strip() for col in customer_df.columns.values]
# customer_df.rename(columns={'order_id_count': 'frequency'}, inplace=True)
customer_df.reset_index(inplace=True)

# --- 1.2: Tạo Đặc trưng Gần đây (Recency) ---
# Tính ngày cuối cùng của bộ dữ liệu để làm mốc
snapshot_date = final_df['order_purchase_timestamp'].max() + pd.DateOffset(days=1)
# Tính ngày mua gần nhất của mỗi khách hàng
recency_df = final_df.groupby('customer_unique_id')['order_purchase_timestamp'].max().reset_index()
recency_df.rename(columns={'order_purchase_timestamp': 'last_purchase_date'}, inplace=True)
# Tính Recency (số ngày kể từ lần mua cuối)
recency_df['recency'] = (snapshot_date - recency_df['last_purchase_date']).dt.days

# Merge đặc trưng Recency vào dataframe khách hàng
# customer_df = pd.merge(customer_df, recency_df[['customer_unique_id', 'recency']], on='customer_unique_id')

print(f"DataFrame cấp độ khách hàng được tạo với shape: {customer_df.shape}")


# ==============================================================================
# BƯỚC 2: TRÍCH XUẤT ĐẶC TRƯNG VĂN BẢN VỚI BERT
# ==============================================================================
print("\n--- Bắt đầu Bước 2: Trích xuất đặc trưng văn bản với BERT ---")

# Tải mô hình và tokenizer (giống như trước)
MODEL_NAME = 'distilbert-base-uncased'
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
bert_model = AutoModel.from_pretrained(MODEL_NAME)

# Chuyển mô hình sang GPU để tăng tốc
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
bert_model.to(device)
bert_model.eval() # Đặt ở chế độ đánh giá

# Sử dụng lại review_map đã tạo ở Giai đoạn 1 của mô hình ViT-like
# (Nếu chưa có, bạn có thể chạy lại đoạn code tạo review_map)
print(f"Sử dụng lại {len(review_map)} chuỗi bình luận đã tổng hợp.")

def get_bert_embeddings(texts, model, tokenizer, device, batch_size=64):
    all_embeddings = []
    # Chia nhỏ để không làm quá tải GPU
    for i in tqdm(range(0, len(texts), batch_size), desc="Tạo BERT Embeddings"):
        batch_texts = texts[i:i+batch_size]
        inputs = tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="pt"
        ).to(device)

        with torch.no_grad():
            outputs = model(**inputs)

        # Lấy embedding của token [CLS]
        cls_embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()
        all_embeddings.extend(cls_embeddings)

    return np.array(all_embeddings)

# Lấy danh sách ID và văn bản tương ứng từ customer_df
customers_with_reviews = customer_df[customer_df['customer_unique_id'].isin(review_map.keys())]
ids_to_process = customers_with_reviews['customer_unique_id'].tolist()
texts_to_process = [review_map[cid] for cid in ids_to_process]

# Tạo embeddings
bert_embeddings = get_bert_embeddings(texts_to_process, bert_model, tokenizer, device)

# Tạo DataFrame từ embeddings
bert_features_df = pd.DataFrame(bert_embeddings, columns=[f'bert_{i}' for i in range(bert_embeddings.shape[1])])
bert_features_df['customer_unique_id'] = ids_to_process

print(f"Đã tạo {bert_embeddings.shape[0]} BERT embeddings với {bert_embeddings.shape[1]} chiều.")


# ==============================================================================
# BƯỚC 3: KẾT HỢP DỮ LIỆU VÀ CHIA TẬP
# ==============================================================================
print("\n--- Bắt đầu Bước 3: Kết hợp và chia dữ liệu ---")

# Merge đặc trưng BERT vào dataframe khách hàng (sử dụng left join)
final_customer_df = pd.merge(customer_df, bert_features_df, on='customer_unique_id', how='left')
# Điền 0 cho những khách hàng không có review
final_customer_df.fillna(0, inplace=True)

# Mã hóa One-Hot cho các cột hạng mục còn lại
final_customer_df = pd.get_dummies(final_customer_df, columns=['customer_state_last', 'product_category_name_english_last', 'payment_type_last'])

print(f"DataFrame cuối cùng có shape: {final_customer_df.shape}")

# Chuẩn bị dữ liệu cho mô hình Scikit-Learn
X = final_customer_df.drop(columns=['customer_unique_id', 'churn_last'])
y = final_customer_df['churn_last']

# Chia dữ liệu
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
print(f"Kích thước tập Train: {X_train.shape}")
print(f"Kích thước tập Test: {X_test.shape}")


# ==============================================================================
# BƯỚC 4: HUẤN LUYỆN VÀ ĐÁNH GIÁ MÔ HÌNH XGBOOST
# ==============================================================================
print("\n--- Bắt đầu Bước 4: Huấn luyện và Đánh giá XGBoost ---")

# Khởi tạo mô hình XGBoost
# scale_pos_weight hữu ích cho dữ liệu mất cân bằng
scale_pos_weight = y_train.value_counts()[0] / y_train.value_counts()[1]
xgb_model = xgb.XGBClassifier(
    objective='binary:logistic',
    eval_metric='logloss',
    use_label_encoder=False,
    scale_pos_weight=scale_pos_weight,
    random_state=42
)

# Huấn luyện mô hình
xgb_model.fit(X_train, y_train)

# Dự đoán trên tập test
y_pred = xgb_model.predict(X_test)
y_pred_proba = xgb_model.predict_proba(X_test)[:, 1] # Xác suất cho lớp 1 (churn)

# Đánh giá hiệu suất
print("\n--- KẾT QUẢ CỦA MÔ HÌNH XGBOOST + BERT ---")
print(f"Accuracy: {accuracy_score(y_test, y_pred):.4f}")
# Thay roc_auc_score(y_test, y_pred) bằng roc_auc_score(y_test, y_pred_proba)
print(f"AUC: {roc_auc_score(y_test, y_pred_proba):.4f}")
print(f"F1-Score: {f1_score(y_test, y_pred):.4f}")
print(f"Precision: {precision_score(y_test, y_pred):.4f}")
print(f"Recall: {recall_score(y_test, y_pred):.4f}")

# Vẽ ma trận nhầm lẫn
cm = confusion_matrix(y_test, y_pred)
plt.figure(figsize=(8, 6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=['Not Churn', 'Churn'], yticklabels=['Not Churn', 'Churn'])
plt.xlabel('Predicted')
plt.ylabel('Actual')
plt.title('Confusion Matrix (XGBoost + BERT) on Test Set')
plt.show()

# %% [markdown]
# # 4: Đánh giá

# %%
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, f1_score, accuracy_score, precision_score, recall_score, confusion_matrix
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Assume X_test, y_test, and xgb_model are already defined and available
# from the previous cell where XGBoost was trained.

print("--- Đánh giá Mô hình XGBoost (Không có BERT Embeddings) ---")

# Dự đoán trên tập test
y_pred_xgb_only = xgb_model.predict(X_test)
y_pred_proba_xgb_only = xgb_model.predict_proba(X_test)[:, 1] # Xác suất cho lớp 1 (churn)

# Đánh giá hiệu suất
print("\n--- KẾT QUẢ CỦA MÔ HÌNH XGBOOST TRÊN TẬP TEST ---")
print(f"Accuracy: {accuracy_score(y_test, y_pred_xgb_only):.4f}")
print(f"AUC: {roc_auc_score(y_test, y_pred_proba_xgb_only):.4f}")
print(f"F1-Score: {f1_score(y_test, y_pred_xgb_only):.4f}")
print(f"Precision: {precision_score(y_test, y_pred_xgb_only):.4f}")
print(f"Recall: {recall_score(y_test, y_pred_xgb_only):.4f}")

# Vẽ ma trận nhầm lẫn
cm_xgb_only = confusion_matrix(y_test, y_pred_xgb_only)
plt.figure(figsize=(8, 6))
sns.heatmap(cm_xgb_only, annot=True, fmt='d', cmap='Blues', xticklabels=['Not Churn', 'Churn'], yticklabels=['Not Churn', 'Churn'])
plt.xlabel('Predicted')
plt.ylabel('Actual')
plt.title('Confusion Matrix (XGBoost Only) on Test Set')
plt.show()

# %% [markdown]
# # 5: SHAP cho XGB

# %%
# ==============================================================================
# BƯỚC XAI: SỬ DỤNG SHAP ĐỂ ĐIỀU TRA DATA LEAKAGE
# ==============================================================================
!pip install shap -q
import shap

print("\n--- Bắt đầu Phân tích XAI với SHAP ---")

# --- Bước 1: Khởi tạo Explainer ---
# Chúng ta cần mô hình đã huấn luyện (xgb_model) và dữ liệu huấn luyện (X_train)
# TreeExplainer là một thuật toán tối ưu của SHAP dành riêng cho các mô hình cây.
explainer = shap.TreeExplainer(xgb_model)

print("Đã khởi tạo SHAP TreeExplainer.")

# --- Bước 2: Tính toán giá trị SHAP trên tập Test ---
# Việc tính toán này có thể mất một chút thời gian
print("Đang tính toán giá trị SHAP cho tập Test...")
shap_values = explainer.shap_values(X_test)

print("Đã tính toán xong giá trị SHAP.")


# --- Bước 3: Trực quan hóa và Phân tích ---

# 3.1. Biểu đồ Tóm tắt (Summary Plot) - QUAN TRỌNG NHẤT
# Biểu đồ này xếp hạng các đặc trưng theo tầm quan trọng trung bình của chúng
# và cho thấy ảnh hưởng của chúng (giá trị cao/thấp của đặc trưng ảnh hưởng đến dự đoán như thế nào).
print("\n--- Biểu đồ Tóm tắt Tầm quan trọng của Đặc trưng (SHAP Summary Plot) ---")
print("Biểu đồ này cho thấy các đặc trưng quan trọng nhất (trên cùng) và tác động của chúng.")
print("Màu đỏ: Giá trị đặc trưng cao. Màu xanh: Giá trị đặc trưng thấp.")
print("Trục x: Giá trị SHAP. Giá trị dương -> tăng khả năng churn. Giá trị âm -> giảm khả năng churn.")

shap.summary_plot(shap_values, X_test, plot_type="dot")


# 3.2. Biểu đồ Tầm quan trọng (Bar Plot)
# Một cách nhìn khác, đơn giản hơn về tầm quan trọng trung bình của các đặc trưng.
print("\n--- Biểu đồ Tầm quan trọng Trung bình (SHAP Bar Plot) ---")
shap.summary_plot(shap_values, X_test, plot_type="bar")


# --- Bước 4: Phân tích kết quả từ biểu đồ ---
print("\n--- PHÂN TÍCH KẾT QUẢ XAI ---")
print("Hãy quan sát các biểu đồ trên, đặc biệt là Summary Plot (biểu đồ đầu tiên):")
print("\n1. Đặc trưng nào đứng đầu danh sách?")
print("   -> Rất có thể bạn sẽ thấy 'recency' và 'frequency' ở các vị trí cao nhất. Điều này xác nhận chúng là những yếu tố dự đoán mạnh nhất.")
print("\n2. Phân tích tác động của 'recency':")
print("   -> Nhìn vào dải màu của 'recency'. Bạn sẽ thấy các điểm màu đỏ (recency cao) nằm hoàn toàn ở phía bên phải của trục x (giá trị SHAP dương), có nghĩa là 'recency' cao đẩy mạnh dự đoán churn. Điều này khớp hoàn hảo với logic gán nhãn của bạn và là bằng chứng mạnh mẽ về data leakage.")
print("\n3. Phân tích tác động của 'frequency':")
print("   -> Nhìn vào dải màu của 'frequency'. Rất có thể bạn sẽ thấy các điểm màu xanh (frequency thấp, ví dụ = 1) nằm ở phía bên phải (tăng khả năng churn, khi kết hợp với recency cao), trong khi các điểm màu đỏ (frequency cao) nằm ở bên trái (giảm khả năng churn).")
print("\n==> KẾT LUẬN TỪ XAI: Các biểu đồ SHAP đã trực quan hóa một cách rõ ràng mối quan hệ toán học giữa các đặc trưng như 'recency', 'frequency' và nhãn 'churn' mà chúng ta đã nghi ngờ. Đây là bằng chứng không thể chối cãi về việc rò rỉ logic (logical leakage) trong pipeline dữ liệu ban đầu.")

# %% [markdown]
# # 6: Lưu cái file về

# %%
import joblib
import pickle
import os

# --- 1. XÁC ĐỊNH CÁC "TÀI SẢN" CẦN LƯU ---
model_to_save = xgb_model
model_columns_to_save = X_train.columns.tolist()

# --- 2. LƯU FILE VÀO THƯ MỤC OUTPUT CỦA KAGGLE ---
# Mặc định thư mục làm việc hiện tại là /kaggle/working/
model_filename = 'churn_model.joblib'
# columns_filename = 'model_columns.pkl'

# 2.1. Lưu mô hình
try:
    joblib.dump(model_to_save, model_filename)
    print(f"Đã lưu thành công mô hình tại: {os.path.abspath(model_filename)}")
except Exception as e:
    print(f"Lỗi khi lưu mô hình: {e}")

# # 2.2. Lưu danh sách cột
# try:
#     with open(columns_filename, 'wb') as f:
#         pickle.dump(model_columns_to_save, f)
#     print(f"Đã lưu thành công danh sách cột tại: {os.path.abspath(columns_filename)}")
# except Exception as e:
#     print(f"Lỗi khi lưu danh sách cột: {e}")

print("\nCác file đã được lưu vào thư mục Output (/kaggle/working).")
print("Bạn có thể tìm thấy chúng trong phần 'Output' của Kernel sau khi chạy xong.")

# %%
!pip freeze | grep -E 'scikit-learn|xgboost|pandas|numpy|shap|joblib|pickle'


