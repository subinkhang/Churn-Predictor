# -*- coding: utf-8 -*-
{
    'name': "Churn Predictor",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'web', 'sale', 'board'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/churn_prediction_views.xml',
        'views/res_partner_views.xml',
        'views/views.xml',
        'views/templates.xml',
        'views/churn_dashboard_views_1.xml',
        'views/churn_dashboard_views_2.xml',
        'views/churn_kpi_views.xml',
        'views/churn_progress_views.xml',
        # 'views/churn_CA_view.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # 'ChurnPredictor/static/src/js/churn_dashboard_action.js',
            # 'ChurnPredictor/static/src/js/churn_prediction_action.js',
            # 'ChurnPredictor/static/src/xml/churn_dashboard_template.xml',
            # 'ChurnPredictor/static/src/xml/churn_prediction_action.xml',
            
            # 'ChurnPredictor/static/src/js/churn_CA.js',
            # 'ChurnPredictor/static/src/xml/churn_CA.xml',
            'ChurnPredictor/static/src/components/kpi_card/kpi_card.js',
            'ChurnPredictor/static/src/components/kpi_card/kpi_card.xml',
            'ChurnPredictor/static/src/components/chart_renderer/chart_renderer.js',
            'ChurnPredictor/static/src/components/chart_renderer/chart_renderer.xml',
            'ChurnPredictor/static/src/components/churn_dashboard.js',
            'ChurnPredictor/static/src/components/churn_dashboard.xml',
        ],
    },
    
    # để hiện icon ngoài Apps
    'application': True,
    'installable': True,
    'external_dependencies': {
        'python': [
            'joblib',
            'pandas',
            'scikit-learn',
            'xgboost',
            'shap',
        ],
    },
}

