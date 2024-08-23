# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _, msgprint
from frappe.model.meta import get_field_precision
from frappe.query_builder.custom import ConstantColumn
from frappe.utils import flt, getdate
from pypika import Order

from erpnext.accounts.party import get_party_account
from erpnext.accounts.report.utils import (
	apply_common_conditions,
	get_advance_taxes_and_charges,
	get_journal_entries,
	get_opening_row,
	get_party_details,
	get_payment_entries,
	get_query_columns,
	get_taxes_query,
	get_values_for_columns,
)


def execute(filters=None):
	return _execute(filters)


def _execute(filters, additional_table_columns=None):
	if not filters:
		filters = frappe._dict({})

	include_payments = filters.get("include_payments")
	if filters.get("include_payments") and not filters.get("customer"):
		frappe.throw(_("Please select a customer for fetching payments."))
	invoice_list = get_invoices(filters, get_query_columns(additional_table_columns))
	if filters.get("include_payments"):
		invoice_list += get_payments(filters)

	columns, income_accounts, unrealized_profit_loss_accounts, tax_accounts = get_columns(
		invoice_list, additional_table_columns, include_payments
	)

	if not invoice_list:
		msgprint(_("No record found"))
		return columns, invoice_list

	invoice_income_map = get_invoice_income_map(invoice_list)
	internal_invoice_map = get_internal_invoice_map(invoice_list)
	invoice_income_map, invoice_tax_map = get_invoice_tax_map(
		invoice_list, invoice_income_map, income_accounts, include_payments
	)
	#frappe.msgprint(str(invoice_tax_map))
	# Cost Center & Warehouse Map
	invoice_cc_wh_map = get_invoice_cc_wh_map(invoice_list)
	invoice_so_dn_map = get_invoice_so_dn_map(invoice_list)
	company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	mode_of_payments = get_mode_of_payments([inv.name for inv in invoice_list])
	customers = list(set(d.customer for d in invoice_list))
	customer_details = get_party_details("Customer", customers)

	res = []
	if include_payments:
		opening_row = get_opening_row(
			"Customer", filters.customer, getdate(filters.from_date), filters.company
		)[0]
		res.append(
			{
				"receivable_account": opening_row.account,
				"debit": flt(opening_row.debit),
				"credit": flt(opening_row.credit),
				"balance": flt(opening_row.balance),
			}
		)

	data = []
	company_country = frappe.get_cached_value("Company", filters.get("company"), "country")

	template_acc=frappe.db.get_all('UAE VAT Account',fields=['account'],pluck='account')
	vat_accs=template_acc	
	if filters.get("taxes_and_charges"):
		if filters.get("taxes_and_charges")!='Nill':
			template_acc=frappe.db.get_all('Sales Taxes and Charges',filters={'parenttype':'Sales Taxes and Charges Template','parent':filters.get("taxes_and_charges")},fields=['account_head'],pluck='account_head',debug=0)		
		

	shpacc=frappe.db.get_all('Vendor Account Mapping',fields=['shipping_revenue_account'],pluck='shipping_revenue_account')

	
	for inv in invoice_list:
		# invoice details
		sales_order = list(set(invoice_so_dn_map.get(inv.name, {}).get("sales_order", [])))
		delivery_note = list(set(invoice_so_dn_map.get(inv.name, {}).get("delivery_note", [])))
		cost_center = list(set(invoice_cc_wh_map.get(inv.name, {}).get("cost_center", [])))
		warehouse = list(set(invoice_cc_wh_map.get(inv.name, {}).get("warehouse", [])))

		country=company_country
		cnt=frappe.db.sql("""select a.country from `tabDynamic Link` d left join `tabAddress` a on d.parent=a.name  where d.link_doctype='Customer' and a.country is not null and d.link_name='{0}' order by a.address_type """.format(inv.customer)) 
		
		if cnt:
			country=cnt[0][0] or company_country
		
		

		row = {
			"voucher_type": inv.doctype,
			"voucher_no": inv.name,
			"posting_date": inv.posting_date,
			"customer": inv.customer,
			"customer_name": inv.customer_name,			
			"total_taxes_and_charges": inv.total_taxes_and_charges,
			"customer_group": customer_details.get(inv.customer).get("customer_group"),
			"territory": country,
			"tax_id": customer_details.get(inv.customer).get("tax_id"),
			"receivable_account": inv.debit_to,
			"mode_of_payment": ", ".join(mode_of_payments.get(inv.name, [])),
			"project": inv.project,
			"owner": inv.owner,
			"remarks": inv.remarks,
			"sales_order": ", ".join(sales_order),
			"delivery_note": ", ".join(delivery_note),
			"cost_center": ", ".join(cost_center),
			"warehouse": ", ".join(warehouse),
			"currency": company_currency,
			"trn_currency": inv.currency,
		}

		# map income values
		
		
		row.update({"base_net_total": inv.base_net_total})

		tacc=[]
		
		if filters.get("tax_account"):
			tacc=filters.get("tax_account")
		elif len(template_acc):
			tacc=template_acc
		# tax account
		#frappe.msgprint(str(tacc))
		total_tax = 0
		oth_dis_charge=0
		ship_charge=0
		
		for tax_acc in tax_accounts:
			#------------ tax .................
			if len(tacc):
				if tax_acc not in income_accounts and tax_acc in tacc and tax_acc not in shpacc:
					tax_amount_precision = (
						get_field_precision(
							frappe.get_meta("Sales Taxes and Charges").get_field("tax_amount"), currency=company_currency
						)
						or 2
					)
					tax_amount = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc), tax_amount_precision)
					total_tax += tax_amount
					row.update({frappe.scrub(tax_acc): tax_amount})
			else:
				if tax_acc not in income_accounts and tax_acc not in shpacc:
					tax_amount_precision = (
						get_field_precision(
							frappe.get_meta("Sales Taxes and Charges").get_field("tax_amount"), currency=company_currency
						)
						or 2
					)
					tax_amount = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc), tax_amount_precision)
					total_tax += tax_amount
					row.update({frappe.scrub(tax_acc): tax_amount})
			#----------- shiping -----------------------
			"""if tax_acc in shpacc:
				tax_amount_precision = (
					get_field_precision(
						frappe.get_meta("Sales Taxes and Charges").get_field("tax_amount"), currency=company_currency
					)
					or 2
				)
				tax_amount = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc), tax_amount_precision)
				ship_charge += tax_amount
				#row.update({frappe.scrub(tax_acc): tax_amount})"""
			#------------other / dis -----------
			if tax_acc not in shpacc and tax_acc not in income_accounts and tax_acc not in tacc:
				tax_amount_precision = (
					get_field_precision(
						frappe.get_meta("Sales Taxes and Charges").get_field("tax_amount"), currency=company_currency
					)
					or 2
				)
				tax_amount_o = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc), tax_amount_precision)
				oth_dis_charge += tax_amount_o
				#row.update({frappe.scrub(tax_acc): tax_amount})
		ship_charge=0
		shpamt=[]
		if len(shpacc):
			shpamt=frappe.db.get_all('Sales Taxes and Charges',filters={'parent':inv.name,'account_head':['in',shpacc]},fields=['base_tax_amount'])

		for sh in shpamt:
			ship_charge+=sh.base_tax_amount
		# total tax, grand total, outstanding amount & rounded total
		#total_taxes_and_charges
		ftax=total_tax
		if inv.conversion_rate:
			ftax=flt(total_tax/inv.conversion_rate)
		
		non_taxable=0
		ship_net_total=0
		taxamt=frappe.db.get_all('Sales Taxes and Charges',filters={'parent':inv.name,'account_head':['in',vat_accs],'base_tax_amount':['!=',0]},fields=['base_tax_amount'])
		if taxamt:
			ship_net_total=ship_charge+inv.base_net_total
		else:
			non_taxable=inv.base_net_total

		fnet_total=ship_net_total
		if inv.conversion_rate:
			fnet_total=flt(ship_net_total/inv.conversion_rate)

		
		tax_calc=flt(ship_net_total*.05)

		grand=ship_net_total+tax_calc
		tax_diff=total_tax-tax_calc

		taxtemp=inv.taxes_and_charges
		if not taxtemp:
			if total_tax==0 and country!=company_country:
				taxtemp='Export'
			else:
				taxtemp='UAE VAT 5%'
		grand_total=inv.grand_total
		if inv.conversion_rate==1:
			ftax=''
			fnet_total=''
			grand_total=''

		row.update(
			{	"ship_charge":ship_charge,
				"oth_dis_charge":oth_dis_charge,
				"non_taxable":non_taxable,
				"ship_net_total":ship_net_total,
				"tax_total": total_tax,
				"tax_diff":tax_diff,
				"f_tax": ftax,
				"conversion_rate": inv.conversion_rate,
				"net_total":fnet_total,
				"grand": grand,
				"tax_calc": tax_calc,
				"taxes_and_charges":taxtemp,
				"grand_total": grand_total,
				"base_grand_total": inv.base_grand_total,
				"rounded_total": inv.base_rounded_total,
				"outstanding_amount": inv.outstanding_amount,
			}
		)

		if inv.doctype == "Sales Invoice":
			row.update({"debit": inv.base_grand_total, "credit": 0.0})
		else:
			row.update({"debit": 0.0, "credit": inv.base_grand_total})
		data.append(row)

	res += sorted(data, key=lambda x: x["posting_date"])

	if include_payments:
		running_balance = flt(opening_row.balance)
		for row in range(1, len(res)):
			running_balance += res[row]["debit"] - res[row]["credit"]
			res[row].update({"balance": running_balance})

	return columns, res, None, None, None, include_payments


def get_columns(invoice_list, additional_table_columns, include_payments=False):
	"""return columns based on filters"""
	columns = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 80},
		{
			"label": _("Inv. No"),
			"fieldname": "voucher_no",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 120,
		},
		{
			"label": _("TRN"),
			"fieldname": "tax_id",
			"fieldtype": "Data",
			"width": 120,
		},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 120},
	]

	
	#columns += additional_table_columns

	
	columns += [
		{
			"label": _("Location"),
			"fieldname": "territory",
			"fieldtype": "Link",
			"options": "Territory",
			"width": 80,
		},
		{
			"label": _("Tax Code"),
			"fieldname": "taxes_and_charges",
			"fieldtype": "Data",
			"width": 100,
		},
		
	]
	

	
	account_columns, accounts = get_account_columns(invoice_list, include_payments)

	net_total_column = [
		{
			"label": _("Net Amount"),
			"fieldname": "base_net_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Shipping Charge"),
			"fieldname": "ship_charge",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Other Charges/Discount"),
			"fieldname": "oth_dis_charge",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Non Taxable"),
			"fieldname": "non_taxable",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Taxable Amount"),
			"fieldname": "ship_net_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	]

	total_columns = [
		{
			"label": _("Tax Colleted (A)"),
			"fieldname": "tax_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Tax Calculated (B)") ,
			"fieldname": "tax_calc",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Tax Variance (A-B)"),
			"fieldname": "tax_diff",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	]
	
	total_columns += [
		{
			"label": _("Grand Calculated"),
			"fieldname": "grand",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Voucher Grand Total"),
			"fieldname": "base_grand_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{"fieldname": "trn_currency", "label": _("Currency"), "fieldtype": "Data", "width": 80},
		{
			"label": _("Exchange Rate"),
			"fieldname": "conversion_rate",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Foreign Amount"),
			"fieldname": "net_total",
			"fieldtype": "Currency",
			"options": "trn_currency",
			"width": 120,
		},
		{
			"label": _("Foreign tax"),
			"fieldname": "f_tax",
			"fieldtype": "Currency",
			"options": "trn_currency",
			"width": 120,
		},
		{
			"label": _("Foreign Total"),
			"fieldname": "grand_total",
			"fieldtype": "Currency",
			"options": "trn_currency",
			"width": 120,
		},
	]

	columns = (
		columns
		+ net_total_column
		+ total_columns
	)
	columns += [{"label": _("Discreption"), "fieldname": "remarks", "fieldtype": "Data", "width": 150}]
	return columns, accounts[0], accounts[1], accounts[2]


def get_account_columns(invoice_list, include_payments):
	income_accounts = []
	tax_accounts = []
	unrealized_profit_loss_accounts = []

	income_columns = []
	tax_columns = []
	unrealized_profit_loss_account_columns = []

	if invoice_list:
		income_accounts = frappe.db.sql_list(
			"""select distinct income_account
			from `tabSales Invoice Item` where docstatus = 1 and parent in (%s)
			order by income_account"""
			% ", ".join(["%s"] * len(invoice_list)),
			tuple(inv.name for inv in invoice_list),
		)

		sales_taxes_query = get_taxes_query(invoice_list, "Sales Taxes and Charges", "Sales Invoice")
		sales_tax_accounts = sales_taxes_query.run(as_dict=True, pluck="account_head")
		tax_accounts = sales_tax_accounts

		if include_payments:
			advance_taxes_query = get_taxes_query(
				invoice_list, "Advance Taxes and Charges", "Payment Entry"
			)
			advance_tax_accounts = advance_taxes_query.run(as_dict=True, pluck="account_head")
			tax_accounts = set(tax_accounts + advance_tax_accounts)

		unrealized_profit_loss_accounts = frappe.db.sql_list(
			"""SELECT distinct unrealized_profit_loss_account
			from `tabSales Invoice` where docstatus = 1 and name in (%s)
			and is_internal_customer = 1
			and ifnull(unrealized_profit_loss_account, '') != ''
			order by unrealized_profit_loss_account"""
			% ", ".join(["%s"] * len(invoice_list)),
			tuple(inv.name for inv in invoice_list),
		)

	for account in income_accounts:
		income_columns.append(
			{
				"label": account,
				"fieldname": frappe.scrub(account),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	for account in tax_accounts:
		if account not in income_accounts:
			tax_columns.append(
				{
					"label": account,
					"fieldname": frappe.scrub(account),
					"fieldtype": "Currency",
					"options": "currency",
					"width": 120,
				}
			)

	for account in unrealized_profit_loss_accounts:
		unrealized_profit_loss_account_columns.append(
			{
				"label": account,
				"fieldname": frappe.scrub(account + "_unrealized"),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns = [income_columns, unrealized_profit_loss_account_columns, tax_columns]
	accounts = [income_accounts, unrealized_profit_loss_accounts, tax_accounts]

	return columns, accounts


def get_invoices(filters, additional_query_columns):
	
	join=''
	cond=' where si.docstatus=1 '
	gpby=''

	join_required = False

	if filters.get("company"):
		cond+=" and si.company='{0}' ".format(filters.get("company")) 
	if filters.get("from_date"):
		cond+=" and si.posting_date>='{0}' ".format(filters.get("from_date")) 
	if filters.get("to_date"):
		cond+=" and si.posting_date<='{0}' ".format(filters.get("to_date")) 

	if filters.get("cost_center"):
		cond+=" and i.cost_center='{0}' ".format(filters.get("cost_center")) 
		join_required = True
	if filters.get("warehouse"):
		cond+=" and i.warehouse='{0}' ".format(filters.get("warehouse")) 
		join_required = True
	if filters.get("item_group"):
		cond+=" and i.item_group='{0}' ".format(filters.get("item_group")) 
		join_required = True
	if filters.get("brand"):
		cond+=" and i.brand='{0}' ".format(filters.get("brand")) 
		join_required = True

	if join_required:
		join+=" inner join `tabSales Invoice Item` i on si.name=i.parent "

	if filters.get("is_return"):
		if filters.get("is_return")=='Sales Return':
			cond+=" and si.is_return=1 "
		if filters.get("is_return")=='Sales Invoice':
			cond+=" and si.is_return=0 "

	if filters.get("customer"):
		cond+=" and si.customer='{0}' ".format(filters.get("customer")) 

	if filters.get("customer_group"):
		cond+=" and si.customer_group='{0}' ".format(filters.get("customer_group"))

	if filters.get("owner"):
		cond+=" and si.owner='{0}' ".format(filters.get("owner"))

	if filters.get("mode_of_payment"):
		join+=" inner join `tabSales Invoice Payment` p on si.name=p.parent "
		cond+=" and p.mode_of_payment='{0}' ".format(filters.get("mode_of_payment"))

	if filters.get("tax_account") or filters.get("taxes_and_charges"):
		join+=" left join `tabSales Taxes and Charges` t on si.name=t.parent "
		gpby=' group by si.name '

	if filters.get("tax_account"):
		acc="','".join(filters.get("tax_account"))
		cond+=" and t.account_head in('{0}') ".format(acc)
		
		

	if filters.get("taxes_and_charges"):
		template_acc=frappe.db.get_all('Sales Taxes and Charges',filters={'parenttype':'Sales Taxes and Charges Template','parent':filters.get("taxes_and_charges")},fields=['account_head'],pluck='account_head')
		subq=" select account from `tabUAE VAT Account` "

		if filters.get("taxes_and_charges")=='Nill':
			#cond+=" and NOT (t.account_head in({0}) and t.tax_amount_after_discount_amount > 0) ".format(subq)
			cond+="and NOT EXISTS (select tt.parent from `tabSales Taxes and Charges` tt where tt.parent=si.name and tt.account_head in({0}) and (tt.tax_amount_after_discount_amount > 0 or tt.tax_amount_after_discount_amount < 0) )".format(subq)
		else:
			if template_acc:
				acc="','".join(template_acc)
				cond+=" and (t.account_head in('{0}') or si.taxes_and_charges='{1}') ".format(acc,filters.get("taxes_and_charges"))
			else:
				cond+=" and si.taxes_and_charges='{0}' ".format(filters.get("taxes_and_charges"))

	invoices=frappe.db.sql(" select si.name,si.posting_date,si.debit_to,si.project,si.customer,si.customer_name,si.owner,si.remarks,si.territory,si.tax_id,si.customer_group,si.base_net_total,	si.base_grand_total,si.base_rounded_total,si.outstanding_amount,si.is_internal_customer,si.represents_company,si.taxes_and_charges,si.company,si.conversion_rate,si.net_total,si.grand_total,si.base_total,si.currency from `tabSales Invoice` si {0} {1} {2} order by si.posting_date asc,si.name asc".format(join,cond,gpby),as_dict=1,debug=0)	
	
	
	
	return invoices


def get_conditions(filters, query, doctype):
	parent_doc = frappe.qb.DocType(doctype)
	if filters.get("owner"):
		query = query.where(parent_doc.owner == filters.owner)
	if filters.get("tax_account"):
		tax_account=filters.get("tax_account")
		tax_doc = frappe.qb.DocType("Sales Taxes and Charges")
		query = query.left_join(tax_doc).on(parent_doc.name == tax_doc.parent)
		query = query.where(tax_doc.account_head.isin(tax_account))
		query = query.groupby(parent_doc.name)

	if filters.get("mode_of_payment"):
		payment_doc = frappe.qb.DocType("Sales Invoice Payment")
		query = query.inner_join(payment_doc).on(parent_doc.name == payment_doc.parent)
		query = query.where(payment_doc.mode_of_payment == filters.mode_of_payment).distinct()

	return query


def get_payments(filters):
	args = frappe._dict(
		account="debit_to",
		account_fieldname="paid_from",
		party="customer",
		party_name="customer_name",
		party_account=get_party_account(
			"Customer", filters.customer, filters.company, include_advance=True
		),
	)
	payment_entries = get_payment_entries(filters, args)
	journal_entries = get_journal_entries(filters, args)
	return payment_entries + journal_entries


def get_invoice_income_map(invoice_list):
	income_details = frappe.db.sql(
		"""select parent, income_account, sum(base_net_amount) as amount
		from `tabSales Invoice Item` where parent in (%s) group by parent, income_account"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	invoice_income_map = {}
	for d in income_details:
		invoice_income_map.setdefault(d.parent, frappe._dict()).setdefault(d.income_account, [])
		invoice_income_map[d.parent][d.income_account] = flt(d.amount)

	return invoice_income_map


def get_internal_invoice_map(invoice_list):
	unrealized_amount_details = frappe.db.sql(
		"""SELECT name, unrealized_profit_loss_account,
		base_net_total as amount from `tabSales Invoice` where name in (%s)
		and is_internal_customer = 1 and company = represents_company"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	internal_invoice_map = {}
	for d in unrealized_amount_details:
		if d.unrealized_profit_loss_account:
			internal_invoice_map.setdefault((d.name, d.unrealized_profit_loss_account), d.amount)

	return internal_invoice_map


def get_invoice_tax_map(invoice_list, invoice_income_map, income_accounts, include_payments=False):
	tax_details = frappe.db.sql(
		"""select parent, account_head,
		sum(base_tax_amount_after_discount_amount) as tax_amount
		from `tabSales Taxes and Charges` where parent in (%s) group by parent, account_head"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	if include_payments:
		tax_details += get_advance_taxes_and_charges(invoice_list)

	invoice_tax_map = {}
	for d in tax_details:
		if d.account_head in income_accounts:
			if d.account_head in invoice_income_map[d.parent]:
				invoice_income_map[d.parent][d.account_head] += flt(d.tax_amount)
			else:
				invoice_income_map[d.parent][d.account_head] = flt(d.tax_amount)
		else:
			invoice_tax_map.setdefault(d.parent, frappe._dict()).setdefault(d.account_head, [])
			invoice_tax_map[d.parent][d.account_head] = flt(d.tax_amount)

	return invoice_income_map, invoice_tax_map


def get_invoice_so_dn_map(invoice_list):
	si_items = frappe.db.sql(
		"""select parent, sales_order, delivery_note, so_detail
		from `tabSales Invoice Item` where parent in (%s)
		and (sales_order != '' or delivery_note != '')"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	invoice_so_dn_map = {}
	for d in si_items:
		if d.sales_order:
			invoice_so_dn_map.setdefault(d.parent, frappe._dict()).setdefault("sales_order", []).append(
				d.sales_order
			)

		delivery_note_list = None
		if d.delivery_note:
			delivery_note_list = [d.delivery_note]
		elif d.sales_order:
			delivery_note_list = frappe.db.sql_list(
				"""select distinct parent from `tabDelivery Note Item`
				where docstatus=1 and so_detail=%s""",
				d.so_detail,
			)

		if delivery_note_list:
			invoice_so_dn_map.setdefault(d.parent, frappe._dict()).setdefault(
				"delivery_note", delivery_note_list
			)

	return invoice_so_dn_map


def get_invoice_cc_wh_map(invoice_list):
	si_items = frappe.db.sql(
		"""select parent, cost_center, warehouse
		from `tabSales Invoice Item` where parent in (%s)
		and (cost_center != '' or warehouse != '')"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	invoice_cc_wh_map = {}
	for d in si_items:
		if d.cost_center:
			invoice_cc_wh_map.setdefault(d.parent, frappe._dict()).setdefault("cost_center", []).append(
				d.cost_center
			)

		if d.warehouse:
			invoice_cc_wh_map.setdefault(d.parent, frappe._dict()).setdefault("warehouse", []).append(
				d.warehouse
			)

	return invoice_cc_wh_map


def get_mode_of_payments(invoice_list):
	mode_of_payments = {}
	if invoice_list:
		inv_mop = frappe.db.sql(
			"""select parent, mode_of_payment
			from `tabSales Invoice Payment` where parent in (%s) group by parent, mode_of_payment"""
			% ", ".join(["%s"] * len(invoice_list)),
			tuple(invoice_list),
			as_dict=1,
		)

		for d in inv_mop:
			mode_of_payments.setdefault(d.parent, []).append(d.mode_of_payment)

	return mode_of_payments
	
@frappe.whitelist()
def uae_acc_list(company):
	#filters={'parent':company},
	return frappe.db.get_all('UAE VAT Account',fields=['account'])

@frappe.whitelist()
def vat_temp_list(company):
	#filters={'parent':company},
	return frappe.db.get_all('Sales Taxes and Charges Template',fields=['name','title'])