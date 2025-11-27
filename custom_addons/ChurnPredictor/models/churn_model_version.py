# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ChurnModelVersion(models.Model):
    _name = 'churn.model.version'
    _description = 'Churn Model Version Control'
    _order = 'create_date desc'

    name = fields.Char(string='Version Name', required=True, default='New Model')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('training', 'Training'),
        ('done', 'Done'),
        ('active', 'Active')
    ], default='draft')

    # Hyperparameters
    learning_rate = fields.Float(default=0.1)
    n_estimators = fields.Integer(default=100)
    max_depth = fields.Integer(default=6)

    # Metrics (Kết quả)
    accuracy_score = fields.Float(readonly=True)
    f1_score = fields.Float(readonly=True)
    training_log = fields.Text(default="Ready to train...")