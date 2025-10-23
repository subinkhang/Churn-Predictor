/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

class ChurnDashboard extends Component {
    // Trỏ đến template XML sẽ được tạo ở bước 3
    static template = "ChurnPredictor.ChurnDashboardTemplate";

    setup() {
        console.log("SUCCESS: Churn Dashboard Component has been setup!");
    }

    onButtonClick() {
        console.log("SUCCESS: Button inside Owl Component was clicked!");
    }
}

// Đây là phần quan trọng nhất:
// Đăng ký component của chúng ta như một "action".
// Tên 'churn_dashboard_action_tag' sẽ được dùng để liên kết trong XML.
registry.category("actions").add("churn_dashboard_action_tag", ChurnDashboard);