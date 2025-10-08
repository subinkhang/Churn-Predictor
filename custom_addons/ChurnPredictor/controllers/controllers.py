# -*- coding: utf-8 -*-
# from odoo import http


# class Churn-app(http.Controller):
#     @http.route('/churn-app/churn-app', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/churn-app/churn-app/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('churn-app.listing', {
#             'root': '/churn-app/churn-app',
#             'objects': http.request.env['churn-app.churn-app'].search([]),
#         })

#     @http.route('/churn-app/churn-app/objects/<model("churn-app.churn-app"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('churn-app.object', {
#             'object': obj
#         })

