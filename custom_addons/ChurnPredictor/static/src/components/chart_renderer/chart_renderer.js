/** @odoo-module */

import { loadJS } from "@web/core/assets";
// === UPDATE 1: Thêm 'onWillUpdateProps' và 'onWillDestroy' vào danh sách import ===
const { Component, onWillStart, useRef, onMounted, onWillUpdateProps, onWillDestroy } = owl;

export class ChartRenderer extends Component {
    setup(){
        this.chartRef = useRef("chart");
        
        // === UPDATE 2: Thêm biến để lưu trữ instance của biểu đồ ===
        this.chart = null;

        onWillStart(async ()=>{
            // Giữ nguyên 100% logic tải thư viện của bạn
            await Promise.all([
                loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"),
                loadJS("https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"),
            ]);
        });

        onMounted(() => {
            this.renderChart();
        });

        // === UPDATE 3: Thêm hook 'onWillUpdateProps' để biểu đồ có thể nhận dữ liệu mới ===
        onWillUpdateProps((nextProps) => {
            this.renderChart(nextProps);
        });

        // === UPDATE 4: Thêm hook 'onWillDestroy' để dọn dẹp, tránh rò rỉ bộ nhớ ===
        onWillDestroy(() => {
            if (this.chart) {
                this.chart.destroy();
            }
        });
    }

    // Thêm `props` làm tham số để dùng cho onWillUpdateProps
    renderChart(props = this.props) {
        // === UPDATE 5: Thêm logic hủy biểu đồ cũ trước khi vẽ cái mới ===
        if (this.chart) {
            this.chart.destroy();
        }

        // Giữ nguyên 100% logic đăng ký plugin của bạn
        if (window.ChartDataLabels) {
            Chart.register(window.ChartDataLabels);
        }

        // Giữ nguyên 100% logic kiểm tra props của bạn
        if (!props.config && props.type !== 'gauge' && props.type !== 'customDoughnut') {
            return; 
        }

        // Giữ nguyên 100% logic lựa chọn loại biểu đồ của bạn
        if (props.type === 'gauge') {
            // Lưu instance biểu đồ mới vào this.chart
            this.chart = this.renderGaugeChart(props);
        } else if (props.type === 'customDoughnut') {
            this.chart = this.renderCustomDoughnutChart(props);
        } else {
            this.chart = new Chart(this.chartRef.el,
            {
              type: props.type,
              data: {
                labels: props.config.labels,
                datasets: props.config.datasets
              },
              options: {
                responsive: true,
                plugins: {
                  legend: {
                    position: 'bottom',
                  },
                  title: {
                    display: true,
                    text: props.title,
                    position: 'bottom',
                  }
                }
              },
            });
        }
    }

    // Các hàm render biểu đồ chi tiết được sửa lại để trả về instance của Chart
    renderGaugeChart() {
        const value = this.props.config.data[0] || 0;

        new Chart(this.chartRef.el, {
            type: 'doughnut',
            data: {
                labels: ['Low Risk', 'Medium Risk', 'High Risk'],
                datasets: [{
                    data: [30, 40, 30],
                    backgroundColor: ['#4caf50', '#ffc107', '#f44336'],
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                rotation: -90,
                circumference: 180,
                // cutout: '60%',
                layout: {
                    padding: {
                        top: 0,
                        bottom: 40,
                        // left: 10,
                        // right: 10
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false },
                }
            },
            plugins: [{
                id: 'customGauge',
                afterDraw: (chart) => {
                    const { ctx, chartArea } = chart;
                    if (!chartArea) return;

                    ctx.save();
                    const xCenter = (chartArea.left + chartArea.right) / 2;
                    const yCenter = (chartArea.top + chartArea.bottom) / 1.2;
                    const outerRadius = chart.getDatasetMeta(0).data[0].outerRadius;
                    
                    ctx.fillStyle = '#666';
                    ctx.font = `bold ${outerRadius / 4}px Arial`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    ctx.fillText(`${value.toFixed(1)}%`, xCenter, yCenter + (outerRadius/2));

                    const angle = Math.PI + (Math.PI * value / 100);
                    const pointX = xCenter + outerRadius * 0.9 * Math.cos(angle);
                    const pointY = yCenter + outerRadius * 0.9 * Math.sin(angle);
                    ctx.beginPath();
                    ctx.lineWidth = 5;
                    ctx.strokeStyle = '#555';
                    ctx.moveTo(xCenter, yCenter);
                    ctx.lineTo(pointX, pointY);
                    ctx.stroke();

                    ctx.beginPath();
                    ctx.arc(xCenter, yCenter, outerRadius * 0.08, 0, 2 * Math.PI);
                    ctx.fillStyle = '#555';
                    ctx.fill();

                    ctx.restore();
                }
            }]
        });
    }

    renderCustomDoughnutChart() {
        new Chart(this.chartRef.el, {
            type: 'doughnut',
            data: {
                labels: this.props.config.labels,
                datasets: [{
                    data: this.props.config.data,
                    borderWidth: 0,
                    // Bạn có thể tùy chỉnh màu sắc ở đây
                    backgroundColor: ['#29B6F6', '#0097A7', '#00838F', '#006064', '#01579B'],
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                // cutout: '70%',
                layout: {
                    padding: {
                        top: 30,
                        bottom: 30,
                        // left: 10,
                        // right: 10
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            boxWidth: 20,
                            padding: 20,
                            // Hiển thị legend là "No. of Product"
                            generateLabels: (chart) => {
                                const data = chart.data;
                                if (data.labels.length && data.datasets.length) {
                                    const { labels: { pointStyle } } = chart.legend.options;
                                    return data.labels.map((label, i) => {
                                        const meta = chart.getDatasetMeta(0);
                                        const style = meta.controller.getStyle(i);
                                        return {
                                            text: `${label}`,
                                            fillStyle: style.backgroundColor,
                                            strokeStyle: style.borderColor,
                                            lineWidth: style.borderWidth,
                                            pointStyle: pointStyle,
                                            hidden: !chart.getDataVisibility(i),
                                            index: i
                                        };
                                    });
                                }
                                return [];
                            }
                        }
                    },
                    // Cấu hình cho plugin datalabels
                    datalabels: {
                        anchor: 'end',
                        align: 'end',
                        offset: 15,
                        formatter: (value, context) => {
                            // Hiển thị giá trị dưới dạng %
                            return `${value.toFixed(2)}%`;
                        },
                        font: {
                            weight: 'bold',
                            size: 8,
                        },
                        color: '#666'
                    }
                }
            }
        });
    }
}

// Giữ nguyên 100% tên template và props của bạn
ChartRenderer.template = "owl.ChartRenderer";
ChartRenderer.props = {
    type: String,
    title: { type: String, optional: true },
    config: { type: Object, optional: true },
};