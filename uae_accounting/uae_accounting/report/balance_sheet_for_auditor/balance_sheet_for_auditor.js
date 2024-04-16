// Copyright (c) 2024, alantechnologies and contributors
// For license information, please see license.txt



frappe.query_reports["Balance Sheet for Auditor"] = $.extend(
	{},
	erpnext.financial_statements
);

erpnext.utils.add_dimensions("Balance Sheet for Auditor", 10);

frappe.query_reports["Balance Sheet for Auditor"]["filters"].push(
	{
		"fieldname": "selected_view",
		"label": __("Select View"),
		"fieldtype": "Select",
		"options": [
			{ "value": "Report", "label": __("Report View") },
			{ "value": "Growth", "label": __("Growth View") }
		],
		"default": "Report",
		"reqd": 1
	},
);

frappe.query_reports["Balance Sheet for Auditor"]["filters"].push({
	fieldname: "accumulated_values",
	label: __("Accumulated Values"),
	fieldtype: "Check",
	default: 1,
});

frappe.query_reports["Balance Sheet for Auditor"]["filters"].push({
	fieldname: "include_default_book_entries",
	label: __("Include Default FB Entries"),
	fieldtype: "Check",
	default: 1,
});
