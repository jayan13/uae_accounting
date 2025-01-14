// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Tax Sales Register"] = {
	"filters": [
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
		{
			"fieldname":"customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer"
		},
		{
			"fieldname":"customer_group",
			"label": __("Customer Group"),
			"fieldtype": "Link",
			"options": "Customer Group"
		},
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"mode_of_payment",
			"label": __("Mode of Payment"),
			"fieldtype": "Link",
			"options": "Mode of Payment"
		},
		{
			"fieldname":"owner",
			"label": __("Owner"),
			"fieldtype": "Link",
			"options": "User"
		},
		{
			"fieldname":"cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center"
		},
		{
			"fieldname":"warehouse",
			"label": __("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse"
		},
		{
			"fieldname":"brand",
			"label": __("Brand"),
			"fieldtype": "Link",
			"options": "Brand"
		},
		{
			"fieldname":"item_group",
			"label": __("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group"
		},
		{
			"fieldname":"taxes_and_charges",
			"label": __("Tax Group"),
			"fieldtype": "Select",
			options: get_temp_options()
		},
		{
			"fieldname":"tax_account",
			"label": __("Tax Account"),
			"fieldtype": "MultiSelectList",
			options: get_ac_options()
		},
		{
			"fieldname":"is_return",
			"label": __("Voucher Type"),
			"fieldtype": "Select",
			"options": ['All','Sales Invoice','Sales Return'],
			"default": 'All'
		},
	]
};



function get_ac_options() {
	let values = [];
	//console.log('c='+company)
	//{"value":"110100 - Bank - GG","description":"110100"},
	frappe.call({
		method: "uae_accounting.uae_accounting.report.tax_sales_register.tax_sales_register.uae_acc_list",
		args: {
			company: ''
		},
		callback: function(r) {
			if (r.message) {
				r.message.forEach(row => values.push({'value':row.account,'description':''}));
			}
		}
	});

	return values;
};


function get_temp_options() {
	let values = [{'value':'','description':''}];
	//console.log('c='+company)
	//{"value":"110100 - Bank - GG","description":"110100"},
	frappe.call({
		method: "uae_accounting.uae_accounting.report.tax_sales_register.tax_sales_register.vat_temp_list",
		args: {
			company: ''
		},
		callback: function(r) {
			if (r.message) {
				r.message.forEach(row => values.push({'value':row.name,'label':row.title,'description':row.title}));
			}
			values.push({'value':'Nill','description':'Nill'});
		}
	});

	return values;
};

//erpnext.utils.add_dimensions('Sales Register', 7);