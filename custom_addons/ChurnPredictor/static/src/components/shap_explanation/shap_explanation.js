/** @odoo-module */

const { Component } = owl;

export class ShapExplanation extends Component {}

ShapExplanation.template = "churn_predictor.ShapExplanation";
ShapExplanation.props = {
    // Prop để nhận chuỗi HTML đã được giải mã
    htmlContent: { type: String, optional: true },
};