// /** @odoo-module **/

// import { registry } from "@web/core/registry";
// import { Component, onWillStart, useState } from "@odoo/owl";
// import { useService } from "@web/core/utils/hooks";
// import { ActionContainer } from "@web/webclient/actions/action_container";

// // Component con
// class SubClientAction extends Component {
//     static template = "ChurnPredictor.subClientTemplate";
// }

// // Component chính cho Dashboard
// class MainDashboardAction extends Component {
//     // Khai báo template và các component con sẽ sử dụng
//     static template = "ChurnPredictor.mainDashboardTemplate";
//     static components = { ActionContainer, SubClientAction };

//     setup() {
//         super.setup();
//         this.action = useService("action");

//         // Sử dụng useState để Owl tự động render lại khi dữ liệu thay đổi
//         this.state = useState({
//             churnAction: null
//         });

//         onWillStart(async () => {
//             // Tải định nghĩa của Window Action bằng action service, đây là cách đúng trong Odoo 17
//             // 'sale.action_quotations_with_onboarding' là một ví dụ có sẵn, bạn có thể thay bằng action của bạn
//             // const loadedAction = await this.action.loadAction("sale.action_quotations_with_onboarding");
//             // this.state.odooAction = loadedAction;

//             const [churnActionData] = await Promise.all([
//                 // THAY ĐỔI Ở ĐÂY:
//                 // Thay thế action báo giá bằng action Churn Dashboard của bạn.
//                 // Nhớ thêm tiền tố là tên module: "ChurnPredictor."
//                 this.action.loadAction("ChurnPredictor.action_churn_main_dashboard")
//             ]);

//             // Gán dữ liệu vào state tương ứng
//             this.state.churnAction = churnActionData;
//         });
//     }
// }

// // Đăng ký các actions vào registry
// registry.category("actions").add("churn_dashboard_main_client", MainDashboardAction);
// // Thẻ tag này không cần định nghĩa action trong XML nếu nó chỉ được dùng như component con
// // registry.category("actions").add("churn_sub_client_action_tag", SubClientAction);

// console.log("✅ Churn dashboard actions (v17) loaded");