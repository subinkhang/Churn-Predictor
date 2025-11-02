/** @odoo-module */

import { registry } from "@web/core/registry";
import { KpiCard } from "./kpi_card/kpi_card";
import { ChartRenderer } from "./chart_renderer/chart_renderer";
import { useService } from "@web/core/utils/hooks";

const { Component, onWillStart, useState } = owl;

export class ChurnDashboard extends Component {
    setup() {
        this.state = useState({
            period: 90,
            highRiskCustomers: { value: 0, percentage: 0 },
            predictedChurn: { value: 0, percentage: 0 },
            totalPredictions: { value: 0, percentage: 0 },
            riskDistribution: { labels: [], data: [] },
            topHighRiskStates: { labels: [], data: [] },
            probabilityTrend: { labels: [], data: [] },
            topCustomers: [],
            avgChurnProbability: { value: 0, rawValue: 0, percentage: 0 },
            churnByProductCount: { labels: [], data: [] },
            churnByState: { labels: [], datasets: [] },
            predictionTrend: { labels: [], datasets: [] },
        });

        this.orm = useService("orm");
        this.actionService = useService("action");

        onWillStart(async () => {
            this.getDates();
            await Promise.all([
                this.getChurnData(),
                this.getChartData()
            ]);
        });
    }

    async onChangePeriod() {
        this.getDates();
        await Promise.all([
            this.getChurnData(),
            this.getChartData()
        ]);
    }

    getDates() {
        const now = new Date();
        const current = new Date(now.getTime() - this.state.period * 24 * 60 * 60 * 1000);
        const previous = new Date(now.getTime() - this.state.period * 2 * 24 * 60 * 60 * 1000);
        this.current_date_str = current.toISOString().slice(0, 19).replace('T', ' ');
        this.previous_date_str = previous.toISOString().slice(0, 19).replace('T', ' ');
    }
    
    computePercentage(current, previous) {
        if (previous === 0) return current > 0 ? 100 : 0;
        return ((current - previous) / previous * 100).toFixed(2);
    }

    _createDomain() {
        let domain = [];
        if (this.state.period > 0) {
            domain.push(['prediction_date', '>', this.current_date_str]);
        }
        return domain;
    }

    async getChurnData() {
        const model = 'churn.prediction';
        const current_domain = this._createDomain();
        let prev_domain = [];
        if (this.state.period > 0) {
            prev_domain.push(['prediction_date', '>', this.previous_date_str], ['prediction_date', '<=', this.current_date_str]);
        }
        
        const highRisk_current_count = this.orm.searchCount(model, [...current_domain, ['probability_level', '=', 'high']]);
        const highRisk_prev_count = this.orm.searchCount(model, [...prev_domain, ['probability_level', '=', 'high']]);
        const churn_current_count = this.orm.searchCount(model, [...current_domain, ['prediction_result', '=', 'churn']]);
        const churn_prev_count = this.orm.searchCount(model, [...prev_domain, ['prediction_result', '=', 'churn']]);
        const avgProb_current_data = this.orm.readGroup(model, current_domain, ['probability:avg'], []);
        const avgProb_prev_data = this.orm.readGroup(model, prev_domain, ['probability:avg'], []);
        const total_current_count = this.orm.searchCount(model, current_domain);
        const total_prev_count = this.orm.searchCount(model, prev_domain);
        
        const [hr_curr, hr_prev, ch_curr, ch_prev, avg_curr_data, avg_prev_data, tot_curr, tot_prev] = await Promise.all([
            highRisk_current_count, highRisk_prev_count, churn_current_count, churn_prev_count, 
            avgProb_current_data, avgProb_prev_data, total_current_count, total_prev_count
        ]);
        
        this.state.highRiskCustomers = { value: hr_curr, percentage: this.computePercentage(hr_curr, hr_prev) };
        this.state.predictedChurn = { value: ch_curr, percentage: this.computePercentage(ch_curr, ch_prev) };
        const current_avg = avg_curr_data[0]?.probability || 0;
        const prev_avg = avg_prev_data[0]?.probability || 0;
        this.state.avgChurnProbability = {
            value: `${current_avg.toFixed(2)}%`, // Dùng cho KPI Card
            rawValue: current_avg, // Dùng cho Gauge Chart mới
            percentage: this.computePercentage(current_avg, prev_avg),
        };
        this.state.totalPredictions = { value: tot_curr, percentage: this.computePercentage(tot_curr, tot_prev) };
    }

    async getChartData() {
        await Promise.all([
            this.getRiskDistributionData(),
            this.getTopHighRiskStatesData(),
            this.getProbabilityTrendData(),
            this.getTopCustomersListData(),
            this.getChurnByProductCountData(),
            this.getChurnByStateData(),
            this.getPredictionTrendData(),
        ]);
    }

    async getRiskDistributionData() {
        const data = await this.orm.readGroup('churn.prediction', this._createDomain(), ['probability_level'], ['probability_level'], { lazy: false });
        const levelMap = { low: 'Low Risk', medium: 'Medium Risk', high: 'High Risk' };
        this.state.riskDistribution = {
            labels: data.map(d => levelMap[d.probability_level] || 'N/A'),
            data: data.map(d => d.probability_level_count)
        };
    }

    async getTopHighRiskStatesData() {
        const domain = this._createDomain();
        domain.push(['probability_level', '=', 'high']);
        const allStatesData = await this.orm.readGroup('churn.prediction', domain, ['customer_state_id'], ['customer_state_id'], { lazy: false });
        const sortedData = allStatesData.sort((a, b) => b.customer_state_id_count - a.customer_state_id_count).slice(0, 5);
        this.state.topHighRiskStates = {
            labels: sortedData.filter(d => d.customer_state_id).map(d => d.customer_state_id[1]),
            data: sortedData.filter(d => d.customer_state_id).map(d => d.customer_state_id_count)
        };
    }

    // === PHIÊN BẢN SỬA LỖI CUỐI CÙNG CHO HÀM NÀY ===
    async getProbabilityTrendData() {
        // 1. Lấy dữ liệu thô, KHÔNG sắp xếp từ server
        const rawData = await this.orm.readGroup(
            'churn.prediction',
            this._createDomain(),
            ['probability:avg'],
            ['prediction_date:day'],
            { lazy: false } // Bỏ hoàn toàn orderby
        );

        // 2. Sắp xếp bằng Javascript để đảm bảo thứ tự thời gian là đúng
        const sortedData = rawData.sort((a, b) => {
            // Chuyển đổi chuỗi ngày tháng thành đối tượng Date để so sánh chính xác
            const dateA = new Date(a['prediction_date:day']);
            const dateB = new Date(b['prediction_date:day']);
            return dateA - dateB;
        });

        // 3. Cập nhật state
        this.state.probabilityTrend = {
            labels: sortedData.map(d => d['prediction_date:day']),
            data: sortedData.map(d => d.probability.toFixed(2))
        };
    }
    
    async getTopCustomersListData() {
        // 1. Lấy TẤT CẢ khách hàng, không sắp xếp, không giới hạn từ server
        const allCustomers = await this.orm.searchRead(
            'churn.prediction',
            this._createDomain(),
            ['customer_name', 'probability', 'prediction_date']
            // Xóa hoàn toàn limit và order khỏi đây
        );

        // 2. Sắp xếp và cắt top 10 bằng Javascript
        const sortedData = allCustomers.sort((a, b) => {
            // Sắp xếp giảm dần dựa trên xác suất
            return b.probability - a.probability;
        }).slice(0, 10); // Lấy 10 phần tử đầu tiên

        // 3. Cập nhật state với dữ liệu đã xử lý
        this.state.topCustomers = sortedData.map(c => ({
            ...c,
            probability: `${c.probability.toFixed(2)}%`
        }));
    }

    // --- Các hàm Tương tác (khi click vào KPI) ---
    // (Giữ nguyên các hàm này, không có lỗi)
    async viewHighRiskCustomers() { 
        const domain = this._createDomain();
        domain.push(['probability_level', '=', 'high']);

        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "High-Risk Customers",
            res_model: "churn.prediction",
            domain,
            views: [[false, "list"], [false, "form"]],
            context: { 'search_default_group_by_customer_id': 1 }
        });
    }

    async viewPredictedChurn() {
        const domain = this._createDomain();
        domain.push(['prediction_result', '=', 'churn']);

        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Predicted to Churn",
            res_model: "churn.prediction",
            domain,
            views: [[false, "list"], [false, "form"]],
            context: { 'search_default_group_by_customer_id': 1 }
        });
    }

    async viewAvgChurnProbability() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Churn Probability Analysis",
            res_model: "churn.prediction",
            domain: this._createDomain(),
            views: [[false, "pivot"], [false, "graph"], [false, "list"], [false, "form"]],
            context: { 'search_default_group_by_prediction_date': 1 }
        });
    }

    async viewTotalPredictions() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Total Predictions",
            res_model: "churn.prediction",
            domain: this._createDomain(),
            views: [[false, "list"], [false, "form"]],
        });
    }
    
    async getChurnByProductCountData() {
        // Nhóm theo trường product_count và tính xác suất trung bình
        const rawData = await this.orm.readGroup(
            'churn.prediction',
            this._createDomain(),
            ['probability:avg'], // Lấy xác suất trung bình
            ['product_count'],   // Nhóm theo số lượng sản phẩm
            { lazy: false }
        );

        // Sắp xếp để biểu đồ trông đẹp hơn
        const sortedData = rawData.sort((a, b) => a.product_count - b.product_count);

        this.state.churnByProductCount = {
            labels: sortedData.map(d => `${d.product_count}`), // Nhãn sẽ là số lượng sản phẩm
            data: sortedData.map(d => d.probability) // Dữ liệu là xác suất trung bình
        };
    }

    async getChurnByStateData() {
        // 1. Lấy dữ liệu thô, KHÔNG sắp xếp từ server
        const rawData = await this.orm.readGroup(
            'churn.prediction',
            this._createDomain(),
            ['prediction_result'],
            ['customer_state_id', 'prediction_result'],
            { lazy: false } // XÓA HOÀN TOÀN 'orderby'
        );

        // 2. Xử lý và sắp xếp bằng Javascript
        const states = {};
        for (const item of rawData) {
            if (!item.customer_state_id) continue;

            const stateName = item.customer_state_id[1];
            if (!states[stateName]) {
                // Khởi tạo với __count là trường đếm mặc định của readGroup
                states[stateName] = { churn: 0, no_churn: 0, total: 0 };
            }
            states[stateName][item.prediction_result] = item.__count;
            states[stateName].total += item.__count;
        }

        // Sắp xếp các Tỉnh/Thành theo tổng số dự đoán và chỉ lấy top 5
        const topStates = Object.entries(states)
            .sort(([, a], [, b]) => b.total - a.total)
            .slice(0, 5);

        // 3. Tạo cấu trúc dữ liệu cuối cùng cho biểu đồ
        this.state.churnByState = {
            labels: topStates.map(([name]) => name),
            datasets: [
                {
                    label: 'Predicted Churn',
                    data: topStates.map(([, counts]) => counts.churn),
                    backgroundColor: 'rgba(255, 99, 132, 0.7)',
                },
                {
                    label: 'No Churn',
                    data: topStates.map(([, counts]) => counts.no_churn),
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                }
            ]
        };
    }

    async getPredictionTrendData() {
        // Lấy dữ liệu, nhóm theo Tuần và Kết quả dự đoán
        const rawData = await this.orm.readGroup(
            'churn.prediction',
            this._createDomain(),
            ['prediction_result'],
            ['prediction_date:week', 'prediction_result'],
            { lazy: false }
        );

        // Xử lý dữ liệu thô để đưa về định dạng Chart.js cần
        const trendData = {};
        for (const item of rawData) {
            const weekLabel = item['prediction_date:week'];
            if (!trendData[weekLabel]) {
                trendData[weekLabel] = { churn: 0, no_churn: 0 };
            }
            trendData[weekLabel][item.prediction_result] = item.__count;
        }

        // Sắp xếp các tuần theo thứ tự thời gian
        const sortedLabels = Object.keys(trendData).sort();

        // Tạo cấu trúc dữ liệu cuối cùng cho biểu đồ
        this.state.predictionTrend = {
            labels: sortedLabels, // Nhãn là các Tuần
            datasets: [
                {
                    label: 'Predicted Churn',
                    data: sortedLabels.map(week => trendData[week].churn),
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.7)',
                    tension: 0.1 // Làm cho đường cong mượt hơn
                },
                {
                    label: 'No Churn',
                    data: sortedLabels.map(week => trendData[week].no_churn),
                    borderColor: 'rgba(54, 162, 235, 1)',
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                    tension: 0.1
                }
            ]
        };
    }

}

ChurnDashboard.template = "owl.ChurnDashboard";
ChurnDashboard.components = { KpiCard, ChartRenderer };

registry.category("actions").add("owl.churn_dashboard", ChurnDashboard);