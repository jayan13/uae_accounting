// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Summary Report"] = {
    "filters": [
            {
                    "fieldname":"company",
                    "label": __("Company"),
                    "fieldtype": "Link",
                    "options": "Company",
                    "default": frappe.defaults.get_user_default("Company")
            },
            {
                    "fieldname":"from_date",
                    "label": __("From Date"),
                    "fieldtype": "Date",
                    "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
                    "width": "80"
            },
            {
                    "fieldname":"to_date",
                    "label": __("To Date"),
                    "fieldtype": "Date",
                    "default": frappe.datetime.get_today()
            },

    ]
};