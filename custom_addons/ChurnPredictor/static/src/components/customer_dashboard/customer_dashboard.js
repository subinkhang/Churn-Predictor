/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ProfileCard } from "../profile_card/profile_card";

const { Component, onWillStart, useState } = owl;

export class CustomerDashboard extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.customerId = this.props.action.context.active_id;
        
        this.state = useState({
            customerData: {}, // Dữ liệu từ res.partner
            lifetimeValue: 0, // Dữ liệu từ sale.order
            latestPrediction: null, // Dữ liệu từ churn.prediction
        });

        onWillStart(async () => {
            // Chạy song song các hàm tải dữ liệu để tăng tốc
            await Promise.all([
                this.loadCustomerData(),
                this.loadSalesData(),
                this.loadLatestPrediction(),
            ]);
        });
    }

    // Hàm tải dữ liệu của khách hàng (res.partner)
    async loadCustomerData() {
        if (!this.customerId) return;
        const data = await this.orm.read(
            "res.partner",
            [this.customerId],
            ["id", "name", "create_date", "email", "phone", "street", "city", "state_id", "country_id", "image_128"]
        );
        if (data && data.length > 0) {
            this.state.customerData = data[0];
        }
    }

    // HÀM MỚI: Tải tổng giá trị đơn hàng (Lifetime Value)
    async loadSalesData() {
        if (!this.customerId) return;
        const salesData = await this.orm.readGroup(
            'sale.order',
            [['partner_id', '=', this.customerId], ['state', 'in', ['sale', 'done']]],
            ['amount_total:sum'],
            []
        );
        if (salesData && salesData.length > 0) {
            // Lấy giá trị tổng và định dạng tiền tệ (ví dụ)
            const total = salesData[0].amount_total || 0;
            this.state.lifetimeValue = total.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
        }
    }

    // HÀM MỚI: Tải bản ghi dự đoán mới nhất
    async loadLatestPrediction() {
        if (!this.customerId) return;
        
        // Thêm 'shap_html' trở lại danh sách các trường cần lấy
        const fieldsToLoad = [
            'prediction_result', 'prediction_date', 'probability', 'probability_level',
            'product_count', 'churn_rate', 'is_high_risk',
            'shap_html' // TRƯỜNG NÀY RẤT QUAN TRỌNG CHO ĐIỀU KIỆN `t-if`
        ];
        
        const predictionData = await this.orm.searchRead(
            'churn.prediction',
            [['customer_id', '=', this.customerId]],
            fieldsToLoad,
            { order: 'prediction_date desc', limit: 1 }
        );

        if (predictionData && predictionData.length > 0) {
            this.state.latestPrediction = predictionData[0];
        }
    }

    // === BẮT ĐẦU PHẦN SỬA LỖI QUAN TRỌNG ===
    onViewShapClick() {
        // Kiểm tra xem có bản ghi dự đoán và ID của nó không
        if (this.state.latestPrediction && this.state.latestPrediction.id) {
            const predictionId = this.state.latestPrediction.id;
            
            // Xây dựng URL trỏ đến controller của bạn
            // Cấu trúc: /<tên_module>/<tên_route>/<tham_số>
            const url = `/churn_predictor/shap_plot/${predictionId}`;
            
            // Mở URL này trong một tab mới
            window.open(url, '_blank');
        }
    }
}

CustomerDashboard.template = "churn_predictor.CustomerDashboard";
CustomerDashboard.components = { ProfileCard };
registry.category("actions").add("churn_predictor.customer_dashboard", CustomerDashboard);