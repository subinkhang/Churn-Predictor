/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets"; // Dùng nếu cần load thư viện ngoài

const { Component, onWillStart, useState } = owl;

export class AdminModelDashboard extends Component {
    setup() {
        // State quản lý toàn bộ giao diện
        this.state = useState({
            modelsList: [],       // Danh sách các model bên trái
            selectedModel: null,  // Model đang được chọn để xem chi tiết
            isEditMode: false,    // Chế độ chỉnh sửa tham số
            isLoading: false,
        });

        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state.isUploadingData = false;

        onWillStart(async () => {
            await this.loadModelsList();
        });
    }

    // --- LOGIC TẢI DỮ LIỆU ---
    async loadModelsList() {
        // Lấy danh sách model từ backend, sắp xếp mới nhất lên đầu
        const models = await this.orm.searchRead(
            'churn.model.version',
            [], 
            ['id', 'name', 'state', 'create_date', 'accuracy_score', 'learning_rate', 'n_estimators', 'max_depth', 'training_log']
        );
        
        this.state.modelsList = models;
        
        // Nếu chưa chọn model nào, chọn cái đầu tiên
        if (models.length > 0 && !this.state.selectedModel) {
            this.selectModel(models[0]);
        }
    }

    async onUploadData(ev) {
        const file = ev.target.files[0];
        if (!file) return;

        this.state.isUploadingData = true;
        const reader = new FileReader();

        reader.onload = async (e) => {
            try {
                // Lấy phần data base64 (cắt bỏ header 'data:text/csv;base64,...')
                const base64Data = e.target.result.split(',')[1];
                
                // Gọi Python để lưu file
                const result = await this.orm.call(
                    'churn.model.version', 
                    'action_save_uploaded_data', 
                    [file.name, base64Data]
                );

                if (result.status === 'success') {
                    this.notification.add(`Data saved to: upload_data/${file.name}`, { type: "success" });
                } else {
                    this.notification.add("Save failed: " + result.message, { type: "danger" });
                }

            } catch (error) {
                console.error(error);
                this.notification.add("Upload Error", { type: "danger" });
            } finally {
                this.state.isUploadingData = false;
                ev.target.value = ''; // Reset input để chọn lại file cũ được
            }
        };

        reader.readAsDataURL(file);
    }

    // --- LOGIC TƯƠNG TÁC UI ---
    selectModel(model) {
        // Clone object để tránh thay đổi trực tiếp vào list khi chưa save
        this.state.selectedModel = { ...model }; 
        this.state.isEditMode = false;
    }

    async createNewModel() {
        this.state.isLoading = true;
        // Gọi ORM tạo bản ghi mới
        const newId = await this.orm.create('churn.model.version', [{
            name: 'New Experiment ' + new Date().toISOString().slice(0,10),
            state: 'draft'
        }]);
        
        await this.loadModelsList();
        // Tìm và chọn model vừa tạo
        const newModel = this.state.modelsList.find(m => m.id === newId[0]);
        if (newModel) this.selectModel(newModel);
        
        this.state.isLoading = false;
        this.state.isEditMode = true; // Bật chế độ sửa luôn
    }

    async saveModelParams() {
        if (!this.state.selectedModel) return;

        await this.orm.write('churn.model.version', [this.state.selectedModel.id], {
            name: this.state.selectedModel.name,
            learning_rate: parseFloat(this.state.selectedModel.learning_rate),
            n_estimators: parseInt(this.state.selectedModel.n_estimators),
            max_depth: parseInt(this.state.selectedModel.max_depth),
        });

        this.notification.add("Model configuration saved!", { type: "success" });
        this.state.isEditMode = false;
        await this.loadModelsList(); // Reload để cập nhật list bên trái
    }

    // --- MOCK FUNCTION CHO PHASE SAU ---
    async triggerRetrain() {
        const model = this.state.selectedModel;
        if (!model) return;

        // Giả lập loading
        this.state.selectedModel.state = 'training';
        this.state.selectedModel.training_log = "Initializing connection to Kaggle...\nUploading dataset...\nTraining started...";
        
        // Cập nhật tạm thời lên UI (thực tế sẽ gọi Python function)
        setTimeout(() => {
            this.state.selectedModel.state = 'done';
            this.state.selectedModel.training_log += "\nTraining finished.\nAccuracy: 0.92";
            this.state.selectedModel.accuracy_score = 0.92;
            this.notification.add("Training Completed (Mock)!", { type: "success" });
        }, 2000);
    }
}

AdminModelDashboard.template = "owl.AdminModelDashboard";
registry.category("actions").add("owl.model_admin_dashboard", AdminModelDashboard);