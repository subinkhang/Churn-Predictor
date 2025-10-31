// /** @odoo-module **/
// import { Component, onMounted } from "@odoo/owl";
// import { nextTick } from "@odoo/owl/utils";
// import { useService } from "@web/core/utils/hooks";
// import { registry } from "@web/core/registry";

// export class ChurnDashboard extends Component {
//     setup() {
//         this.action = useService("action");

//         onMounted(async () => {
//             // Đảm bảo DOM sẵn sàng trước khi thao tác
//             await nextTick();

//             // 1️⃣ Client Action
//             await this.action.doAction("churn_dashboard.action_churn_sub_client", {
//                 target: this.el.querySelector("#client_action_zone"),
//                 replace_last_action: false,
//             });

//             // 2️⃣ Odoo View (Graph)
//             await this.action.doAction("churn_prediction.action_churn_kpi", {
//                 target: this.el.querySelector("#odoo_view_zone"),
//                 replace_last_action: false,
//             });

//             // 3️⃣ Odoo Action (Tree)
//             await this.action.doAction("churn_prediction.action_churn_main_dashboard", {
//                 target: this.el.querySelector("#odoo_action_zone"),
//                 replace_last_action: false,
//             });
//         });
//     }
// }

// ChurnDashboard.template = "churn_dashboard_template";
// registry.category("actions").add("churn_dashboard_main_client", ChurnDashboard);
