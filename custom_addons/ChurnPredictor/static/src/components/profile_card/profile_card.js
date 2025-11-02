/** @odoo-module */

const { Component } = owl;

export class ProfileCard extends Component {}

ProfileCard.template = "churn_predictor.ProfileCard";
ProfileCard.props = {
    customer: { type: Object },
    lifetimeValue: { type: String, optional: true },
    latestPrediction: { type: Object, optional: true },
};