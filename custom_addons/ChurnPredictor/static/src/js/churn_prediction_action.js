/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class ChurnPredictionSPA extends Component {
    static template = "ChurnPredictor.ChurnPredictionSPATemplate";

    setup() {
        this.orm = useService("orm");
        this.rpc = useService("rpc");

        this.state = useState({
            // Quản lý màn hình hiện tại: 'list' hoặc 'detail'
            currentView: 'list', 
            
            // Dữ liệu cho màn hình danh sách
            records: [],
            isLoadingList: true,

            // Dữ liệu cho màn hình chi tiết
            activeRecord: null,
            shapHtml: null,
            // shapScript: null,
            isLoadingDetail: false,
        });

        // Tải dữ liệu cho màn hình danh sách khi component khởi động
        onWillStart(async () => {
            // === THAY ĐỔI Ở ĐÂY ===
            // Kiểm tra xem có 'active_id' được gửi từ context không
            const activeId = this.props.action.context.active_id;
            
            if (activeId) {
                // Nếu có, mở thẳng màn hình chi tiết
                await this.selectRecord(activeId);
            } else {
                // Nếu không, mở màn hình danh sách như bình thường
                await this.loadListData();
            }
        });
    }

    // Tải danh sách các bản ghi dự đoán
    async loadListData() {
        this.state.isLoadingList = true;
        this.state.records = await this.orm.searchRead(
            "churn.prediction",
            [], // Không có domain, lấy tất cả
            ["prediction_date", "customer_name", "prediction_result", "probability"],
            { order: 'prediction_date desc' }
        );
        this.state.isLoadingList = false;
    }

    // Được gọi khi click vào một dòng trong bảng
    async selectRecord(recordId) {
        this.state.currentView = 'detail';
        this.state.isLoadingDetail = true;
        
        const data = await this.orm.read("churn.prediction", [recordId], ["customer_id", "prediction_date", "prediction_result", "probability"]);
        if (data.length > 0) {
            this.state.activeRecord = data[0];
        }
        
        this.state.isLoadingDetail = false;
    }

    onViewShapInNewTab() {
        // Lấy ID của bản ghi hiện tại
        const recordId = this.state.activeRecord.id;
        
        // Tạo URL đến controller của chúng ta
        const url = `/churn_predictor/shap_plot/${recordId}`;
        
        // Mở URL đó trong một tab mới. Đây là một hàm JavaScript tiêu chuẩn.
        window.open(url, '_blank');
    }

    // Quay lại màn hình danh sách
    backToList() {
        this.state.currentView = 'list';
        this.state.activeRecord = null;
        this.state.shapHtml = null;
    }
}

registry.category("actions").add("churn_prediction_spa_action_tag", ChurnPredictionSPA);