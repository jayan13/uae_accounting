# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe import _, msgprint
from frappe.query_builder.custom import ConstantColumn
from frappe.utils import flt, getdate

def execute(filters=None):
	columns, data = [], []
	columns=get_columns()
	data=get_data(filters)
	return columns, data

def get_data(filters=None):
	if not filters:
		filters = {}
	cond=''

	if filters.get("company"):
		cond+=" and pi.company='{0}' ".format(filters.get("company")) 
	if filters.get("from_date"):
		cond+=" and pi.posting_date>='{0}' ".format(filters.get("from_date")) 
	if filters.get("to_date"):
		cond+=" and pi.posting_date<='{0}' ".format(filters.get("to_date")) 
		
	if filters.get("item_group"):
		acc="','".join(filters.get("item_group"))
		cond+=" and pii.item_group in ('{0}') ".format(acc)

	if filters.get("item_group_no"):
		acc="','".join(filters.get("item_group_no"))
		cond+=" and pii.item_group not in ('{0}') ".format(acc)

	invoices=frappe.db.sql(" select pi.name,pi.posting_date,pi.conversion_rate,pi.supplier,pi.supplier_name,pi.base_grand_total,pi.grand_total,pi.outstanding_amount,pi.currency,pi.due_date,pi.is_return,pi.status from `tabPurchase Invoice Item` pii left join `tabPurchase Invoice` pi on pi.name=pii.parent where pi.docstatus=1 {0} group by pi.name ORDER BY pi.`posting_date` ASC".format(cond),as_dict=1,debug=0 )

	return invoices 



def get_columns():

	columns = [
		{
			"label": _("Purchase Invoice"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 220,
		},
		{
			"label": _("Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 220,
		},
		{
				"label": _("Grand Total"),
				"fieldname": "grand_total",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{"label": _("Exchange Rate"), "fieldname": "conversion_rate", "fieldtype": "Currency", "width": 100},
			{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 100},
			{
				"label": _("Grand Total (AED)"),
				"fieldname": "base_grand_total",
				"fieldtype": "Currency",
				"width": 120,
			},
			{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
			{
				"label": _("Outstanding Amount"),
				"fieldname": "outstanding_amount",
				"fieldtype": "Currency",
				"width": 120,
			},
			{
			"label": _("Due Date"),
			"fieldname": "due_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{"label": _("Is Return"), "fieldname": "is_return", "fieldtype": "Check", "width": 120},
	]

	return columns
