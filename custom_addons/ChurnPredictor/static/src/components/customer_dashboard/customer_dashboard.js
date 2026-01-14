/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ProfileCard } from "../profile_card/profile_card";
import { ChartRenderer } from "../chart_renderer/chart_renderer";
const { Component, onWillStart, useState, markup } = owl;

export class CustomerDashboard extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.customerId = this.props.action.context.active_id;
        
        // === UPDATE 3: Dọn dẹp setup() và cập nhật state ===
        // Xóa hoàn toàn các dòng sau:
        // this.chartRef = useRef("interactionChart");
        // this.chart = null;

        const currentYear = new Date().getFullYear();
        const years = Array.from({ length: 15 }, (_, i) => currentYear - i); // Lấy 15 năm gần nhất

        this.state = useState({
            customerData: {},
            lifetimeValue: 0,
            latestPrediction: null,
            interactionData: { timeline: [], insights: [] },
            interactionChartConfig: null, 
            selectedEvent: null,
            isGeneratingExplanation: false,
            isSendingEmail: false,
            
            // State mới để quản lý filter
            periodType: 'last_12_months', // Mặc định
            availableYears: years,
            selectedYear: currentYear,
        });

        onWillStart(async () => {
            await Promise.all([
                this.loadCustomerData(),
                this.loadSalesData(),
                this.loadLatestPrediction(),
                this.loadInteractionData(), // Hàm này giờ sẽ dùng state mới
            ]);
        });
        
        // Xóa hoàn toàn các hook onMounted() và onWillDestroy() khỏi đây.
    }

    // Các hàm loadCustomerData, loadSalesData, loadLatestPrediction giữ nguyên 100%
    async loadCustomerData() {
        if (!this.customerId) return;
        
        // === UPDATE: Thêm 3 trường x_feat_... vào danh sách này ===
        const fieldsToRead = [
            "id", "name", "create_date", "email", "phone", 
            "street", "city", "state_id", "country_id", "image_128",
            "x_feat_segment", "x_feat_personal_avg_gap", "x_feat_category_avg_gap" // <--- MỚI THÊM
        ];

        const data = await this.orm.read("res.partner", [this.customerId], fieldsToRead);
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
        
        const fieldsToLoad = [
            'prediction_result', 'prediction_date', 'probability', 'probability_level', 
            'product_count', 'churn_rate', 'is_high_risk', 'shap_html',
            'shap_ai_explanation', 'shap_data_json'
        ];
        
        const predictionData = await this.orm.searchRead('churn.prediction', [['customer_id', '=', this.customerId]], fieldsToLoad, { order: 'prediction_date desc', limit: 1 });
        
        if (predictionData && predictionData.length > 0) {
            const prediction = predictionData[0];

            // === SỬA TẠI ĐÂY: Dùng hàm markup() ===
            if (prediction.shap_ai_explanation) {
                // Hàm markup() sẽ báo cho Odoo biết chuỗi này là HTML an toàn
                prediction.shap_ai_explanation = markup(prediction.shap_ai_explanation);
            }

            this.state.latestPrediction = prediction;
        }
    }

    // === UPDATE 4: Sửa đổi hàm loadInteractionData để chuẩn bị config cho ChartRenderer ===
    async loadInteractionData() {
        if (!this.customerId) return;
        const data = await this.orm.call(
            "res.partner", 
            "get_interaction_timeline_data", 
            [ // Mở đầu danh sách các tham số (args)
                this.customerId,
                this.state.periodType,
                this.state.selectedYear
            ] // Đóng danh sách
        );


        console.log("--- DỮ LIỆU TỪ SERVER CHO BIỂU ĐỒ ---");
        console.log(JSON.stringify(data.chart_data, null, 2));

        // Cập nhật state cho timeline và insights như cũ
        this.state.interactionData = {
            timeline: data.timeline,
            insights: data.insights,
        };
        
        // Thay vì tự vẽ, chúng ta tạo một object config và đưa vào state
        this.state.interactionChartConfig = {
            labels: data.chart_data.labels,
            datasets: [{
                label: 'Monthly Spending', // Đổi tên cho đúng ý nghĩa
                data: data.chart_data.values,
                // === SỬA CÁC DÒNG SAU ĐỂ THÀNH LINE CHART ===
                backgroundColor: 'rgba(1, 126, 132, 0.1)', // Màu nền mờ
                borderColor: 'rgba(1, 126, 132, 1)',     // Màu đường kẻ đậm
                borderWidth: 2,
                fill: true, // Tô màu khu vực bên dưới đường kẻ
                tension: 0.3 // Làm cho đường kẻ mượt hơn
            }]
        };

        if (data.timeline && data.timeline.length > 0) {
            this.state.selectedEvent = data.timeline[0];
        }
    }

    async onChangePeriodType(ev) {
        this.state.periodType = ev.target.value;
        // Tải lại dữ liệu biểu đồ
        await this.loadInteractionData();
    }
    async onChangeYear(ev) {
        this.state.selectedYear = parseInt(ev.target.value);
        // Tải lại dữ liệu biểu đồ
        await this.loadInteractionData();
    }

    async onCheckDebugLogs() {
        if (!this.state.latestPrediction || !this.state.latestPrediction.id) {
            return;
        }

        try {
            // Gọi hàm python 'action_view_shap_logs'
            const action = await this.orm.call(
                "churn.prediction",       // Model name
                "action_view_shap_logs",  // Method name
                [this.state.latestPrediction.id] // Arguments (Ids)
            );

            // Vì hàm Python trả về một action (display_notification),
            // ta cần dùng actionService để thực thi nó.
            if (action) {
                await this.actionService.doAction(action);
            }
        } catch (e) {
            console.error("Error fetching debug logs:", e);
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

    async generateAIExplanation() {
        if (!this.state.latestPrediction || !this.state.latestPrediction.id) {
            return;
        }
        
        this.state.isGeneratingExplanation = true; // Bật trạng thái loading

        try {
            await this.orm.call(
                'churn.prediction', // model
                'action_generate_ai_explanation', // method
                [[this.state.latestPrediction.id]] // args (danh sách ID)
            );
            
            // Sau khi thành công, tải lại dữ liệu dự đoán để cập nhật UI
            await this.loadLatestPrediction(); 

        } catch (error) {
            // Hiển thị lỗi cho người dùng nếu có sự cố
            this.notification.add(
                error.data?.message || "An unknown error occurred.",
                { type: 'danger', title: 'AI Explanation Failed' }
            );
        } finally {
            this.state.isGeneratingExplanation = false; // Tắt trạng thái loading
        }
    }

    async onSendEmailClick() {
        if (!this.state.latestPrediction || !this.state.latestPrediction.id) {
            this.notification.add("No prediction selected.", { type: 'warning' });
            return;
        }

        // SỬ DỤNG window.confirm() - TƯƠNG THÍCH 100% VỚI MỌI PHIÊN BẢN
        const isConfirmed = window.confirm("Are you sure you want to send this AI analysis directly to the customer?");
        
        if (!isConfirmed) {
            return; // Người dùng đã nhấn "Cancel"
        }

        this.state.isSendingEmail = true;

        try {
            await this.orm.call(
                'churn.prediction',
                'action_send_ai_explanation_email',
                [[this.state.latestPrediction.id]]
            );

            this.notification.add("AI analysis email has been sent successfully!", {
                type: 'success',
                title: 'Email Sent'
            });

        } catch (error) {
            this.notification.add(
                error.data?.message || "An unknown error occurred while sending the email.",
                { type: 'danger', title: 'Email Failed' }
            );
        } finally {
            this.state.isSendingEmail = false;
        }
    }
}

CustomerDashboard.template = "churn_predictor.CustomerDashboard";
// === UPDATE 5: Đăng ký ChartRenderer như một component con ===
CustomerDashboard.components = { ProfileCard, ChartRenderer }; 
registry.category("actions").add("churn_predictor.customer_dashboard", CustomerDashboard);