/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const { Component, onWillStart, useState, onWillUnmount } = owl;

export class AdminModelDashboard extends Component {
    setup() {
        this.state = useState({
            modelsList: [],
            selectedModel: null,
            isEditMode: false,
            isLoading: false,
            isUploadingData: false,
        });
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.pollingInterval = null;

        onWillStart(async () => {
            await this.loadModelsList();
        });

        // Dọn dẹp interval khi thoát màn hình dashboard
        onWillUnmount(() => {
            if (this.pollingInterval) clearInterval(this.pollingInterval);
        });
    }

    // --- 1. LOAD DATA ---
    async loadModelsList() {
        const models = await this.orm.searchRead(
            'churn.model.version', [], 
            ['id', 'name', 'state', 'create_date', 'accuracy_score', 'learning_rate', 'n_estimators', 'max_depth', 'training_log', 'latest_csv_path', 'latest_filename']
        );
        this.state.modelsList = models;
        
        // Nếu đang chọn model nào đó, cập nhật lại data mới nhất cho nó
        if (this.state.selectedModel) {
            const updated = models.find(m => m.id === this.state.selectedModel.id);
            if (updated) {
                this.state.selectedModel = { ...updated };
                // Nếu model đang training, tiếp tục polling
                if (updated.state === 'training') {
                    this._startPolling(updated.id);
                }
            }
        } else if (models.length > 0) {
            this.selectModel(models[0]);
        }
    }

    selectModel(model) {
        this.state.selectedModel = { ...model };
        this.state.isEditMode = false;
        
        // Nếu model này đang training, bật lại polling
        if (this.pollingInterval) clearInterval(this.pollingInterval);
        if (model.state === 'training') {
            this._startPolling(model.id);
        }
    }

    // --- 2. UPLOAD CSV ---
    async onUploadData(ev) {
        const file = ev.target.files[0];
        if (!file || !this.state.selectedModel) return;

        this.state.isUploadingData = true;
        this.notification.add("Uploading file to history...", { type: "info" });

        const reader = new FileReader();
        reader.onload = async (e) => {
            try {
                const base64Data = e.target.result.split(',')[1];
                
                // Gọi Python
                const result = await this.orm.call(
                    'churn.model.version', 
                    'action_save_uploaded_data', 
                    [file.name, base64Data]
                );

                if (result.status === 'success') {
                    this.notification.add(result.message, { type: "success" });
                    
                    // Update backend (Lưu đường dẫn file vào bản ghi)
                    await this.orm.write('churn.model.version', [this.state.selectedModel.id], {
                        latest_csv_path: result.file_path,
                        latest_filename: result.file_name // Cần thêm field này ở Python nếu chưa có
                    });
                    
                    // Reload & Update UI
                    await this.loadModelsList();
                    
                } else {
                    this.notification.add("Upload Failed: " + result.message, { type: "danger" });
                }
            } catch (error) {
                console.error(error);
                this.notification.add("System Error: " + error.message, { type: "danger" });
            } finally {
                this.state.isUploadingData = false;
                ev.target.value = '';
            }
        };
        reader.readAsDataURL(file);
    }

    // --- 3. RETRAIN (TRIGGER + POLLING) ---
    async triggerRetrain() {
        const model = this.state.selectedModel;
        if (!model) return;

        if (!model.latest_csv_path) {
            this.notification.add("Warning: Using sample data.", { type: "warning" });
        }

        this.notification.add("Connecting to Kaggle...", { type: "info" });
        
        try {
            const result = await this.orm.call('churn.model.version', 'action_trigger_retrain', [model.id]);

            if (result.status === 'success') {
                this.notification.add("Kaggle started! Polling for results...", { type: "success" });
                this.state.selectedModel.state = 'training';
                this.state.selectedModel.training_log = "--- KAGGLE STARTED ---\nWaiting for kernel execution...";
                
                // Bắt đầu check tự động
                this._startPolling(model.id);
            } else {
                this.notification.add("Error: " + result.message, { type: "danger" });
            }
        } catch (error) {
            console.error(error);
            this.notification.add("RPC Error: " + error.message.data.message, { type: "danger" });
        }
    }

    // --- [FIX LỖI 2] BUTTON 3: CHECK & DOWNLOAD THỦ CÔNG ---
    // Bạn thiếu hàm này nên nó báo Invalid handler
    async checkDownload() {
        const model = this.state.selectedModel;
        if (!model) return;

        this.notification.add("Checking Kaggle status...", { type: "info" });
        
        try {
            // Gọi hàm check status (dùng chung logic với polling)
            const check = await this.orm.call('churn.model.version', 'check_training_status', [model.id]);

            if (check.status === 'done') {
                this.state.selectedModel.state = 'done';
                this.notification.add(check.message, { type: "success" });
                await this.loadModelsList();
                // Dừng polling nếu đang chạy
                if (this.pollingInterval) clearInterval(this.pollingInterval);
            } else if (check.status === 'running') {
                this.notification.add("Kaggle is still running: " + check.message, { type: "warning" });
            } else {
                this.notification.add("Error: " + check.message, { type: "danger" });
            }
        } catch (error) {
            this.notification.add("Check Failed: " + error.message.data.message, { type: "danger" });
        }
    }

    // --- [FIX LỖI 1] LOGIC POLLING ---
    _startPolling(modelId) {
        if (this.pollingInterval) clearInterval(this.pollingInterval);

        // Check mỗi 15 giây
        this.pollingInterval = setInterval(async () => {
            if (!this.state.selectedModel || this.state.selectedModel.id !== modelId) return;

            try {
                const check = await this.orm.call('churn.model.version', 'check_training_status', [modelId]);

                // Cập nhật Log
                this.state.selectedModel.training_log += `\n[${new Date().toLocaleTimeString()}] ${check.message}`;

                // [QUAN TRỌNG] Kiểm tra kỹ status trả về để dừng vòng lặp
                if (check.status === 'done') {
                    clearInterval(this.pollingInterval); // DỪNG NGAY
                    this.state.selectedModel.state = 'done';
                    this.notification.add("Training Finished & Downloaded!", { type: "success", sticky: true });
                    await this.loadModelsList();
                } 
                else if (check.status === 'error') {
                    clearInterval(this.pollingInterval); // DỪNG NGAY
                    this.notification.add("Training Failed: " + check.message, { type: "danger", sticky: true });
                }
                // Nếu 'running' thì cứ chạy tiếp

            } catch (err) {
                console.error("Polling error", err);
                // Nếu lỗi mạng 3 lần liên tiếp thì dừng (tránh spam server)
            }
        }, 15000); 
    }

    // --- 4. CRUD ---
    async createNewModel() {
        this.state.isLoading = true;
        const newId = await this.orm.create('churn.model.version', [{
            name: 'Experiment ' + new Date().toISOString().slice(0,19).replace('T',' '),
            state: 'draft'
        }]);
        await this.loadModelsList();
        const newModel = this.state.modelsList.find(m => m.id === newId[0]);
        if (newModel) this.selectModel(newModel);
        
        this.state.isLoading = false;
        this.state.isEditMode = true;
    }

    async saveModelParams() {
        if (!this.state.selectedModel) return;
        await this.orm.write('churn.model.version', [this.state.selectedModel.id], {
            name: this.state.selectedModel.name,
            learning_rate: parseFloat(this.state.selectedModel.learning_rate),
            n_estimators: parseInt(this.state.selectedModel.n_estimators),
            max_depth: parseInt(this.state.selectedModel.max_depth),
        });
        this.notification.add("Configuration saved.", { type: "success" });
        this.state.isEditMode = false;
        await this.loadModelsList();
    }

    async deleteModel(modelId) {
        const confirmed = confirm("Delete this version?");
        if (!confirmed) return;

        try {
            await this.orm.unlink('churn.model.version', [modelId]);
            this.notification.add("Deleted.", { type: "success" });
            if (this.state.selectedModel && this.state.selectedModel.id === modelId) {
                this.state.selectedModel = null;
            }
            await this.loadModelsList();
        } catch (error) {
            this.notification.add("Cannot delete: " + error.message.data.message, { type: "danger" });
        }
    }
}

AdminModelDashboard.template = "owl.AdminModelDashboard";
registry.category("actions").add("owl.model_admin_dashboard", AdminModelDashboard);