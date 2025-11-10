/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ProfileCard } from "../profile_card/profile_card";
// === UPDATE 1: Import component ChartRenderer mà chúng ta đã hoàn thiện ở Bước 1 ===
import { ChartRenderer } from "../chart_renderer/chart_renderer";

// === UPDATE 2: Dọn dẹp các import không còn cần thiết từ OWL ===
// Chúng ta không cần onMounted, onWillDestroy, useRef nữa vì ChartRenderer sẽ xử lý chúng.
const { Component, onWillStart, useState } = owl;

export class CustomerDashboard extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.customerId = this.props.action.context.active_id;
        
        // === UPDATE 3: Dọn dẹp setup() và cập nhật state ===
        // Xóa hoàn toàn các dòng sau:
        // this.chartRef = useRef("interactionChart");
        // this.chart = null;

        this.state = useState({
            customerData: {},
            lifetimeValue: 0,
            latestPrediction: null,
            interactionData: {
                timeline: [],
                insights: []
            },
            // Thêm một state mới để chứa object cấu hình cho biểu đồ.
            // Nó sẽ được truyền vào ChartRenderer như một prop.
            interactionChartConfig: null, 
            selectedEvent: null, 
        });

        onWillStart(async () => {
            await Promise.all([
                this.loadCustomerData(),
                this.loadSalesData(),
                this.loadLatestPrediction(),
                this.loadInteractionData(),
            ]);
        });
        
        // Xóa hoàn toàn các hook onMounted() và onWillDestroy() khỏi đây.
    }

    // Các hàm loadCustomerData, loadSalesData, loadLatestPrediction giữ nguyên 100%
    async loadCustomerData() {
        if (!this.customerId) return;
        const data = await this.orm.read("res.partner", [this.customerId], ["id", "name", "create_date", "email", "phone", "street", "city", "state_id", "country_id", "image_128"]);
        if (data && data.length > 0) this.state.customerData = data[0];
    }
    async loadSalesData() {
        if (!this.customerId) return;
        const salesData = await this.orm.readGroup('sale.order', [['partner_id', '=', this.customerId], ['state', 'in', ['sale', 'done']]], ['amount_total:sum'], []);
        if (salesData && salesData.length > 0) {
            const total = salesData[0].amount_total || 0;
            this.state.lifetimeValue = total.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
        }
    }
    async loadLatestPrediction() {
        if (!this.customerId) return;
        const fieldsToLoad = ['prediction_result', 'prediction_date', 'probability', 'probability_level', 'product_count', 'churn_rate', 'is_high_risk', 'shap_html'];
        const predictionData = await this.orm.searchRead('churn.prediction', [['customer_id', '=', this.customerId]], fieldsToLoad, { order: 'prediction_date desc', limit: 1 });
        if (predictionData && predictionData.length > 0) this.state.latestPrediction = predictionData[0];
    }

    // === UPDATE 4: Sửa đổi hàm loadInteractionData để chuẩn bị config cho ChartRenderer ===
    async loadInteractionData() {
        if (!this.customerId) return;
        const data = await this.orm.call("res.partner", "get_interaction_timeline_data", [this.customerId]);

        // Cập nhật state cho timeline và insights như cũ
        this.state.interactionData = {
            timeline: data.timeline,
            insights: data.insights,
        };
        
        // Thay vì tự vẽ, chúng ta tạo một object config và đưa vào state
        this.state.interactionChartConfig = {
            labels: data.chart_data.labels,
            datasets: [{
                label: 'Interactions',
                data: data.chart_data.values,
                backgroundColor: 'rgba(54, 162, 235, 0.6)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        };

        if (data.timeline && data.timeline.length > 0) {
            this.state.selectedEvent = data.timeline[0];
        }
    }
    
    // XÓA HOÀN TOÀN HÀM renderChart() KHỎI ĐÂY.

    // Các hàm xử lý sự kiện giữ nguyên 100%
    onSelectEvent(event) {
        this.state.selectedEvent = event;
    }
    onViewShapClick() {
        if (this.state.latestPrediction && this.state.latestPrediction.id) {
            const predictionId = this.state.latestPrediction.id;
            const url = `/churn_predictor/shap_plot/${predictionId}`;
            window.open(url, '_blank');
        }
    }
}

CustomerDashboard.template = "churn_predictor.CustomerDashboard";
// === UPDATE 5: Đăng ký ChartRenderer như một component con ===
CustomerDashboard.components = { ProfileCard, ChartRenderer }; 
registry.category("actions").add("churn_predictor.customer_dashboard", CustomerDashboard);