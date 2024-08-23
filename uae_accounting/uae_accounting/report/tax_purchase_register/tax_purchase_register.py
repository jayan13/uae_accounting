# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _, msgprint
from frappe.query_builder.custom import ConstantColumn
from frappe.utils import flt, getdate
from pypika import Order

from erpnext.accounts.party import get_party_account
from erpnext.accounts.report.utils import (
	apply_common_conditions,
	get_advance_taxes_and_charges,
	get_journal_entries,
	get_opening_row,
	get_payment_entries,
	get_query_columns,
	get_taxes_query,
	get_values_for_columns,
)


def execute(filters=None):
	return _execute(filters)


def _execute(filters=None, additional_table_columns=None):
	if not filters:
		filters = {}
	
	include_payments = filters.get("include_payments")
	if filters.get("include_payments") and not filters.get("supplier"):
		frappe.throw(_("Please select a supplier for fetching payments."))
	invoice_list = get_invoices(filters, get_query_columns(additional_table_columns))
	if filters.get("include_payments"):
		invoice_list += get_payments(filters)

	columns, expense_accounts, tax_accounts, unrealized_profit_loss_accounts = get_columns(
		invoice_list, additional_table_columns, include_payments
	)

	if not invoice_list:
		msgprint(_("No record found"))
		return columns, invoice_list

	invoice_expense_map = get_invoice_expense_map(invoice_list)
	internal_invoice_map = get_internal_invoice_map(invoice_list)
	invoice_expense_map, invoice_tax_map = get_invoice_tax_map(
		invoice_list, invoice_expense_map, expense_accounts, include_payments
	)
	invoice_po_pr_map = get_invoice_po_pr_map(invoice_list)
	suppliers = list(set(d.supplier for d in invoice_list))
	supplier_details = get_party_details("Supplier", suppliers)
	
	company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	
	taxpre=get_field_precision('Purchase Invoice Item','tax_amount') or 2
	netpre=get_field_precision('Purchase Invoice Item','base_net_rate') or 2
	
	res = []
	data = []
	uaevatacc=frappe.db.get_all('UAE VAT Account',fields=['account'],pluck='account')
	puracchd=frappe.db.get_all('Purchase Taxes and Charges',filters={'parenttype':'Purchase Taxes and Charges Template','parent':filters.get("taxes_and_charges")},fields=['account_head'],pluck='account_head')
	acch=uaevatacc
	if filters.get("tax_account"):
		acch=filters.get("tax_account")
	if filters.get("taxes_and_charges"):
		if filters.get("taxes_and_charges")=='Nill':
			acch=uaevatacc
		else:
			acch=puracchd
		
	for inv in invoice_list:

		# invoice details
		purchase_order = list(set(invoice_po_pr_map.get(inv.name, {}).get("purchase_order", [])))
		purchase_receipt = list(set(invoice_po_pr_map.get(inv.name, {}).get("purchase_receipt", [])))
		project = list(set(invoice_po_pr_map.get(inv.name, {}).get("project", [])))
		
		taxtemp=inv.taxes_and_charges
		#if not taxtemp:
			#taxtemp='UAE VAT 5%'

		row = {
			"location":supplier_details.get(inv.supplier).get("country"),
			"voucher_type": inv.doctype,
			"voucher_no": inv.name,
			"posting_date": inv.posting_date,
			"supplier_id": inv.supplier,
			"supplier_name": inv.supplier_name,
			"supplier_group": supplier_details.get(inv.supplier).get("supplier_group"),
			"tax_id": supplier_details.get(inv.supplier).get("tax_id"),
			"payable_account": inv.credit_to,
			"mode_of_payment": inv.mode_of_payment,
			"project": ", ".join(project) if inv.doctype == "Purchase Invoice" else inv.project,
			"bill_no": inv.bill_no,
			"bill_date": inv.bill_date,
			"remarks": inv.remarks,
			"purchase_order": ", ".join(purchase_order),
			"purchase_receipt": ", ".join(purchase_receipt),
			"currency": company_currency,
			"trn_currency":inv.currency,
			"tax_template":taxtemp,
			"conversion_rate":inv.conversion_rate,
		}

		#------------------------------------------------------------------------
		
		#frappe.msgprint('=======================================================')
		itar={}
		inv_item=[]
		if inv.get('items'):
			itms=str(inv.get('items')).split(';')
			#frappe.msgprint(str(itms))
			
			for itrs in itms:
				itr=str(itrs).split('~')
				itar.setdefault(itr[0], frappe._dict())
				inv_item.append(itr[0])
				#frappe.msgprint(str(itr[1]))
				if itar[itr[0]].item_amount:
					itar[itr[0]].item_amount+=flt(float(itr[1]))
				else:	 
					itar[itr[0]].item_amount=flt(float(itr[1]))
					
				if itar[itr[0]].tax_amount:
					itar[itr[0]].tax_amount+=flt(float(itr[2]))
				else:	 
					itar[itr[0]].tax_amount=flt(float(itr[2]))  

				itar[itr[0]].item_tax_template=itr[4]
				

		txs=frappe.db.get_all('Purchase Taxes and Charges',filters={'parent':inv.name},fields=['category','account_head','item_wise_tax_detail','description','charge_type'])
			
		import json
		
		itemised_tax = {}
		for tx in txs:
			if tx.account_head in uaevatacc:
				if tx.category == "Valuation":
					continue

				item_tax_map = json.loads(tx.item_wise_tax_detail) if tx.item_wise_tax_detail else {}
				if item_tax_map:
					for item_code, tax_data in item_tax_map.items():
						
						itemised_tax.setdefault(item_code, frappe._dict())

						tax_rate = 0.0
						tax_amount = 0.0

						if isinstance(tax_data, list):
							tax_rate = flt(tax_data[0])
							tax_amount = flt(tax_data[1])
						else:
							tax_rate = flt(tax_data)

						itemised_tax[item_code][tx.description] = frappe._dict(
							dict(tax_rate=tax_rate, tax_amount=tax_amount)
						)
						itemised_tax[item_code][tx.description].description = tx.description
						itemised_tax[item_code][tx.description].tax_account = tx.account_head
						itemised_tax[item_code][tx.description].charge_type = tx.charge_type
		#frappe.msgprint(str(itemised_tax))
		inv_items = list(set(inv_item))
		itemwised_tax={}
		#frappe.msgprint(str(inv_items))
		#frappe.msgprint('-----------------------------------------')
		taxinfo=frappe.db.get_value('Purchase Taxes and Charges',{'parent':inv.name,'account_head':['in',uaevatacc]},['account_head']) or ''

		for item_code in inv_items:
			itemwised_tax.setdefault(item_code, frappe._dict())
			tax_rate = 0
			tax_amount = 0
			taxble=0
			account=''
			vou_tem_acc=''
			itm_ttem_acc=''
			vouch_temp=taxtemp
			#itm_tx_tmp=itar.get(item_code,{}).get('item_tax_template')
			#if itm_tx_tmp:
			#	account=frappe.db.get_value('Item Tax Template Detail',{'parent':itm_tx_tmp,'tax_type':['in',acch]},['tax_type']) or 'zero'
			
			
			if taxtemp:
				if taxinfo:
					vou_tem_acc=frappe.db.get_all('Purchase Taxes and Charges',filters={'charge_type':'On Net Total','parenttype':"Purchase Taxes and Charges Template",'parent':taxtemp},fields=['account_head','rate'])
					#frappe.msgprint(str(vou_tem_acc))
					itm_tx_tmp=itar.get(item_code,{}).get('item_tax_template')
					if itm_tx_tmp:	
						if taxtemp and vou_tem_acc:
							itm_ttem_acc=frappe.db.get_all('Item Tax Template Detail',filters={'parent':itm_tx_tmp},fields=['tax_type','tax_rate'])
							if len(itm_ttem_acc)>1:
								#frappe.msgprint('---in ------')							
								for vc in vou_tem_acc:
									for ic in itm_ttem_acc:
										if vc.account_head==ic.tax_type and vc.rate==0:
											account=vc.account_head
											vouch_temp=taxtemp
										elif vc.account_head!=ic.tax_type and ic.tax_rate==0:
											account=ic.tax_type
											vouch_temp=itm_tx_tmp	
											#break
										#else:		
											#account=vc.account_head
											
							else:
								account=vou_tem_acc[0].account_head
								vouch_temp=taxtemp
						else:
							account=frappe.db.get_value('Item Tax Template Detail',{'parent':itm_tx_tmp,'tax_type':['in',acch]},['tax_type'])
							vouch_temp=itm_tx_tmp 
					else:
						if len(vou_tem_acc):
							account=vou_tem_acc[0].account_head
							vouch_temp=taxtemp
						else:
							account=''
							vouch_temp=taxtemp
				else:
					account=''
					vouch_temp=taxtemp
			else:
				itm_tx_tmp=itar.get(item_code,{}).get('item_tax_template')
				account=frappe.db.get_value('Item Tax Template Detail',{'parent':itm_tx_tmp,'tax_type':['in',acch]},['tax_type'])
				vouch_temp=itm_tx_tmp
				if not itm_tx_tmp:
					account=''
					vouch_temp=''
					
			#frappe.msgprint(str(inv.name)+'-*-----'+str(item_code)+' '+str(account))
			
			if itemised_tax.get(item_code):
				for tax in itemised_tax.get(item_code).values():
					account=account or tax.get("tax_account")
					itemwised_tax[item_code][account]=frappe._dict()
					itemwised_tax[item_code][account].tax_rate=tax.get("tax_rate", 0)
					itemwised_tax[item_code][account].tax_amount=tax.get("tax_amount", 0)
					itemwised_tax[item_code][account].taxble=itar.get(item_code,{}).get('item_amount') or 0
					itemwised_tax[item_code][account].account=account
					itemwised_tax[item_code][account].template=vouch_temp
			else:
				
				account=account or 'zero'
				itemwised_tax[item_code][account]=frappe._dict()
				itemwised_tax[item_code][account].tax_rate=tax_rate
				itemwised_tax[item_code][account].tax_amount=itar.get(item_code,{}).get('tax_amount') or 0
				itemwised_tax[item_code][account].taxble=itar.get(item_code,{}).get('item_amount') or 0
				itemwised_tax[item_code][account].account=account
				itemwised_tax[item_code][account].template=vouch_temp

		
		new_tax_tot=0
		new_taxable=0
		new_zero_taxable=0
		new_non_taxable=0
		#frappe.msgprint(str(itemwised_tax))
		#frappe.msgprint(str(acch))
		for itx in itemwised_tax.values():
			for tc in itx.values():
				#frappe.msgprint(str(tc))
				if tc.get('account') in acch:
					#frappe.msgprint(str(tc.get('tax_amount')))
					if tc.get('tax_amount') == 0 and taxinfo:
						new_zero_taxable+=flt(tc.get('taxble'),netpre)
					elif tc.get('tax_amount') == 0:
						new_non_taxable+=flt(tc.get('taxble'),netpre)	
					else:
						new_taxable+=flt(tc.get('taxble'),netpre)
						new_tax_tot+=flt(tc.get('tax_amount'),taxpre)
				else:
					if tc.get('account')=='zero':
						new_non_taxable+=flt(tc.get('taxble'),netpre)

		row.update({"t_net_total": new_taxable,'z_net_total':new_zero_taxable,'n_net_total':new_non_taxable,'n_total_tax':new_tax_tot})
		#-----------------------------------------------------------------------------------------------------------------
		base_net_total = 0
		for expense_acc in expense_accounts:
			if inv.is_internal_supplier and inv.company == inv.represents_company:
				expense_amount = 0
			else:
				expense_amount = flt(invoice_expense_map.get(inv.name, {}).get(expense_acc))
			base_net_total += expense_amount
			row.update({frappe.scrub(expense_acc): expense_amount})

		# Add amount in unrealized account
		for account in unrealized_profit_loss_accounts:
			row.update(
				{frappe.scrub(account + "_unrealized"): flt(internal_invoice_map.get((inv.name, account)))}
			)
		#item_b_net
		#item_net
		#item_tax
		
		base_net_total=inv.item_b_net
		#base_net_total=inv.base_net_total
		#base_net_total or inv.base_net_total
		# net total
		 
		v_taxable_amount=flt(inv.base_net_total-base_net_total)
		row.update({"net_total": inv.base_net_total,'taxable_amount':base_net_total,'v_taxable_amount':v_taxable_amount})
		

		# tax account
		total_tax = 0
		for tax_acc in tax_accounts:
			if tax_acc not in expense_accounts and tax_acc in acch:
				tax_amount = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc))
				total_tax += tax_amount
				row.update({frappe.scrub(tax_acc): tax_amount})

		
		f_amount=flt(new_taxable/inv.conversion_rate)
		# total tax, grand total, rounded total & outstanding amount
		nntax_diff=new_tax_tot-total_tax
		calc_tax=0
		v_tax=0
		f_tax=0
		if total_tax:
			calc_tax=flt(base_net_total*.05)
			v_tax=flt(total_tax-calc_tax)
			f_tax=flt(new_tax_tot/inv.conversion_rate)

		if inv.conversion_rate==1:
			f_tax=0
			f_amount=0
		row.update(
			{
				"total_tax": total_tax,
				"calc_tax":calc_tax,
				"v_tax":v_tax,
				"grand_total": inv.base_grand_total,
				"rounded_total": inv.base_rounded_total,
				"outstanding_amount": inv.outstanding_amount,
				"f_tax": f_tax,
				"f_amount": f_amount,
				"grand": inv.grand_total,
				"nntax_diff":nntax_diff
			}
		)

		if inv.doctype == "Purchase Invoice":
			row.update({"debit": inv.base_grand_total, "credit": 0.0})
		else:
			row.update({"debit": 0.0, "credit": inv.base_grand_total})
		data.append(row)

	res += sorted(data, key=lambda x: x["posting_date"])

	

	return columns, res, None, None, None, include_payments


def get_columns(invoice_list, additional_table_columns, include_payments=False):
	"""return columns based on filters"""
	columns = [
		
		{
			"label": _("Voucher"),
			"fieldname": "voucher_no",
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 120,
		},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 80},
		{
			"label": _("Supplier"),
			"fieldname": "supplier_id",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 120,
		},
		{"label": _("Invoice Date"), "fieldname": "bill_date", "fieldtype": "Date", "width": 80},
		{"label": _("Invoice No"), "fieldname": "bill_no", "fieldtype": "Data", "width": 120},
		{"label": _("Tax Id"), "fieldname": "tax_id", "fieldtype": "Data", "width": 80},		
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 120},
		{"label": _("Location"), "fieldname": "location", "fieldtype": "Data", "width": 100},
		{"label": _("Tax Code"), "fieldname": "tax_template", "fieldtype": "Data", "width": 100},
	]

	if additional_table_columns and not include_payments:
		columns += additional_table_columns

	

	account_columns, accounts = get_account_columns(invoice_list, include_payments)

	
	columns += [
		{
				"label": _("Taxable Amount"),
				"fieldname": "t_net_total",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Non Taxable"),
				"fieldname": "n_net_total",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("0 Rate Taxable "),
				"fieldname": "z_net_total",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Input Tax"),
				"fieldname": "n_total_tax",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Voucher Tax"),
				"fieldname": "total_tax",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Tax diff"),
				"fieldname": "nntax_diff",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Voucher Net Total"),
				"fieldname": "net_total",
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
			"width": 80,
		},
		{
			"label": _("Foreign Amount"),
			"fieldname": "f_amount",
			"fieldtype": "Currency",
			"options": "trn_currency",
			"width": 80,
		},
		{
			"label": _("Foreign Tax "),
			"fieldname": "f_tax",
			"fieldtype": "Currency",
			"options": "trn_currency",
			"width": 80,
		},
		
	]
	columns += [{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 120}]
	return columns, accounts[0], accounts[2], accounts[1]


def get_account_columns(invoice_list, include_payments):
	expense_accounts = []
	tax_accounts = []
	unrealized_profit_loss_accounts = []

	expense_columns = []
	tax_columns = []
	unrealized_profit_loss_account_columns = []

	if invoice_list:
		expense_accounts = frappe.db.sql_list(
			"""select distinct expense_account
			from `tabPurchase Invoice Item` where docstatus = 1
			and (expense_account is not null and expense_account != '')
			and parent in (%s) order by expense_account"""
			% ", ".join(["%s"] * len(invoice_list)),
			tuple([inv.name for inv in invoice_list]),
		)

		purchase_taxes_query = get_taxes_query(
			invoice_list, "Purchase Taxes and Charges", "Purchase Invoice"
		)
		purchase_tax_accounts = purchase_taxes_query.run(as_dict=True, pluck="account_head")
		tax_accounts = purchase_tax_accounts

		if include_payments:
			advance_taxes_query = get_taxes_query(
				invoice_list, "Advance Taxes and Charges", "Payment Entry"
			)
			advance_tax_accounts = advance_taxes_query.run(as_dict=True, pluck="account_head")
			tax_accounts = set(tax_accounts + advance_tax_accounts)

		unrealized_profit_loss_accounts = frappe.db.sql_list(
			"""SELECT distinct unrealized_profit_loss_account
			from `tabPurchase Invoice` where docstatus = 1 and name in (%s)
			and ifnull(unrealized_profit_loss_account, '') != ''
			order by unrealized_profit_loss_account"""
			% ", ".join(["%s"] * len(invoice_list)),
			tuple(inv.name for inv in invoice_list),
		)

	for account in expense_accounts:
		expense_columns.append(
			{
				"label": account,
				"fieldname": frappe.scrub(account),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	for account in tax_accounts:
		if account not in expense_accounts:
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
				"fieldname": frappe.scrub(account),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns = [expense_columns, unrealized_profit_loss_account_columns, tax_columns]
	accounts = [expense_accounts, unrealized_profit_loss_accounts, tax_accounts]

	return columns, accounts


def get_invoices(filters, additional_query_columns):
	
	join=''
	cond=''

	if filters.get("company"):
		cond+=" and pi.company='{0}' ".format(filters.get("company")) 
	if filters.get("from_date"):
		cond+=" and pi.posting_date>='{0}' ".format(filters.get("from_date")) 
	if filters.get("to_date"):
		cond+=" and pi.posting_date<='{0}' ".format(filters.get("to_date")) 

	if filters.get("cost_center"):
		cond+=" and pii.cost_center='{0}' ".format(filters.get("cost_center")) 
		
	if filters.get("warehouse"):
		cond+=" and pii.warehouse='{0}' ".format(filters.get("warehouse")) 
		
	if filters.get("item_group"):
		cond+=" and pii.item_group='{0}' ".format(filters.get("item_group")) 
		
	if filters.get("brand"):
		cond+=" and pii.brand='{0}' ".format(filters.get("brand"))

	if filters.get("mode_of_payment"):
		cond+=" and pi.mode_of_payment='{0}' ".format(filters.get("mode_of_payment"))

	if filters.get("is_return"):
		if filters.get("is_return")=='Purchase Return':
			cond+=" and pi.is_return=1 "
		if filters.get("is_return")=='Purchase Invoice':
			cond+=" and pi.is_return=1 "

	if filters.get("rcm"):
		if filters.get("rcm")!='All':
			cond+=" and pi.reverse_charge='{0}' ".format(filters.get("rcm"))
		
	#if filters.get("tax_account") or filters.get("taxes_and_charges"):
		#join+=" left join `tabPurchase Taxes and Charges` t on pi.name=t.parent "	

	if filters.get("tax_account"):
		acc="','".join(filters.get("tax_account"))
		#cond+=" and t.account_head in('{0}') ".format(acc)
		cond+=" and EXISTS (select tt.parent from `tabPurchase Taxes and Charges` tt where tt.parent=pi.name and tt.account_head in('{0}')  ) ".format(acc)
		
	
	if filters.get("taxes_and_charges"):
		
		template_acc=frappe.db.get_all('Purchase Taxes and Charges',filters={'parenttype':'Purchase Taxes and Charges Template','parent':filters.get("taxes_and_charges")},fields=['account_head'],pluck='account_head')

		uaevatacc=frappe.db.get_all('UAE VAT Account',fields=['account'],pluck='account')
		vacc="','".join(uaevatacc)

		if filters.get("taxes_and_charges")=='Nill':
			#cond+=" and (pi.total_taxes_and_charges=0 or t.account_head in('{0}')) ".format(filters.get("taxes_and_charges"))
			cond+=" and NOT EXISTS (select tt.parent from `tabPurchase Taxes and Charges` tt where tt.parent=pi.name and tt.account_head in('{0}') and (tt.tax_amount_after_discount_amount > 0 or tt.tax_amount_after_discount_amount < 0) ) ".format(vacc)
		else:
			if template_acc:
				acc="','".join(template_acc)
				cond+=" and (EXISTS (select tt.parent from `tabPurchase Taxes and Charges` tt where tt.parent=pi.name and tt.account_head in('{0}')) or pi.taxes_and_charges='{1}' or pii.item_tax_template='{1}') ".format(acc,filters.get("taxes_and_charges"))
			else:
				cond+=" and (pi.taxes_and_charges='{0}' or pii.item_tax_template='{0}' ) ".format(filters.get("taxes_and_charges")) 
		

	invoices=frappe.db.sql(" select GROUP_CONCAT(CONCAT(pii.item_code,'~',pii.base_net_amount,'~',pii.tax_amount,'~',pii.tax_rate,'~',IFNULL(pii.item_tax_template,'')) SEPARATOR ';') as items,pi.name,pi.posting_date,pi.credit_to,pi.supplier,pi.supplier_name,pi.tax_id,pi.bill_no,pi.bill_date,pi.remarks,pi.base_net_total,pi.base_grand_total,pi.base_rounded_total,pi.outstanding_amount,pi.mode_of_payment,pi.taxes_and_charges,pi.conversion_rate,pi.currency,pi.net_total,pi.grand_total,sum(pii.base_net_amount) as 'item_b_net' from `tabPurchase Invoice Item` pii left join `tabPurchase Invoice` pi on pi.name=pii.parent left join `tabItem` i on i.name=pii.item_code {0} where pi.docstatus=1 {1} group by pi.name ORDER BY pi.`posting_date` DESC,pi.`name` DESC".format(join,cond),as_dict=1,debug=0 )
	return invoices


def get_conditions(filters, query, doctype):
	parent_doc = frappe.qb.DocType(doctype)

	if filters.get("mode_of_payment"):
		query = query.where(parent_doc.mode_of_payment == filters.mode_of_payment)

	if filters.get("is_return"):
		if filters.get("is_return")=='Sales Return':
			query = query.where(parent_doc.is_return == 1)
		if filters.get("is_return")=='Sales Invoice':
			query = query.where(parent_doc.is_return == 0)

	if filters.get("rcm"):
		if filters.get("rcm")!='All':
			query = query.where(parent_doc.reverse_charge == filters.get("rcm"))
		
	if filters.get("taxes_and_charges") or filters.get("tax_account"):
		tax_account=filters.get("tax_account")
		tax_doc = frappe.qb.DocType("Purchase Taxes and Charges")
		query = query.left_join(tax_doc).on(parent_doc.name == tax_doc.parent)
		

	if filters.get("tax_account"):
		query = query.where(tax_doc.account_head.isin(tax_account))
		
	
	if filters.get("taxes_and_charges"):
		
		template_acc=frappe.db.get_all('Purchase Taxes and Charges',filters={'parenttype':'Purchase Taxes and Charges Template','parent':filters.get("taxes_and_charges")},fields=['account_head'],pluck='account_head')
		uaevatacc=frappe.db.get_all('UAE VAT Account',fields=['account'],pluck='account')
		#pii.item_tax_template
		if filters.get("taxes_and_charges")=='Nill':
			query = query.where((tax_doc.account_head.isin(uaevatacc) | parent_doc.total_taxes_and_charges==0))
			#query = query.having(Sum(tax_doc.base_tax_amount) == 0)
		else:
			if template_acc:
				query = query.where((tax_doc.account_head.isin(template_acc) | parent_doc.taxes_and_charges==filters.taxes_and_charges))
			else:
				query = query.where(parent_doc.taxes_and_charges==filters.taxes_and_charges)

	return query


def get_payments(filters):
	args = frappe._dict(
		account="credit_to",
		account_fieldname="paid_to",
		party="supplier",
		party_name="supplier_name",
		party_account=get_party_account(
			"Supplier", filters.supplier, filters.company, include_advance=True
		),
	)
	payment_entries = get_payment_entries(filters, args)
	journal_entries = get_journal_entries(filters, args)
	return payment_entries + journal_entries


def get_invoice_expense_map(invoice_list):
	expense_details = frappe.db.sql(
		"""
		select parent, expense_account, sum(base_net_amount) as amount
		from `tabPurchase Invoice Item`
		where parent in (%s)
		group by parent, expense_account
	"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	invoice_expense_map = {}
	for d in expense_details:
		invoice_expense_map.setdefault(d.parent, frappe._dict()).setdefault(d.expense_account, [])
		invoice_expense_map[d.parent][d.expense_account] = flt(d.amount)

	return invoice_expense_map


def get_internal_invoice_map(invoice_list):
	unrealized_amount_details = frappe.db.sql(
		"""SELECT name, unrealized_profit_loss_account,
		base_net_total as amount from `tabPurchase Invoice` where name in (%s)
		and is_internal_supplier = 1 and company = represents_company"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	internal_invoice_map = {}
	for d in unrealized_amount_details:
		if d.unrealized_profit_loss_account:
			internal_invoice_map.setdefault((d.name, d.unrealized_profit_loss_account), d.amount)

	return internal_invoice_map


def get_invoice_tax_map(
	invoice_list, invoice_expense_map, expense_accounts, include_payments=False
):
	tax_details = frappe.db.sql(
		"""
		select parent, account_head, case add_deduct_tax when "Add" then sum(base_tax_amount_after_discount_amount)
		else sum(base_tax_amount_after_discount_amount) * -1 end as tax_amount
		from `tabPurchase Taxes and Charges`
		where parent in (%s) and category in ('Total', 'Valuation and Total')
			and base_tax_amount_after_discount_amount != 0
		group by parent, account_head, add_deduct_tax
	"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	if include_payments:
		tax_details += get_advance_taxes_and_charges(invoice_list)

	invoice_tax_map = {}
	for d in tax_details:
		if d.account_head in expense_accounts:
			if d.account_head in invoice_expense_map[d.parent]:
				invoice_expense_map[d.parent][d.account_head] += flt(d.tax_amount)
			else:
				invoice_expense_map[d.parent][d.account_head] = flt(d.tax_amount)
		else:
			invoice_tax_map.setdefault(d.parent, frappe._dict()).setdefault(d.account_head, [])
			invoice_tax_map[d.parent][d.account_head] = flt(d.tax_amount)

	return invoice_expense_map, invoice_tax_map


def get_invoice_po_pr_map(invoice_list):
	pi_items = frappe.db.sql(
		"""
		select parent, purchase_order, purchase_receipt, po_detail, project
		from `tabPurchase Invoice Item`
		where parent in (%s)
	"""
		% ", ".join(["%s"] * len(invoice_list)),
		tuple(inv.name for inv in invoice_list),
		as_dict=1,
	)

	invoice_po_pr_map = {}
	for d in pi_items:
		if d.purchase_order:
			invoice_po_pr_map.setdefault(d.parent, frappe._dict()).setdefault("purchase_order", []).append(
				d.purchase_order
			)

		pr_list = None
		if d.purchase_receipt:
			pr_list = [d.purchase_receipt]
		elif d.po_detail:
			pr_list = frappe.db.sql_list(
				"""select distinct parent from `tabPurchase Receipt Item`
				where docstatus=1 and purchase_order_item=%s""",
				d.po_detail,
			)

		if pr_list:
			invoice_po_pr_map.setdefault(d.parent, frappe._dict()).setdefault("purchase_receipt", pr_list)

		if d.project:
			invoice_po_pr_map.setdefault(d.parent, frappe._dict()).setdefault("project", []).append(
				d.project
			)

	return invoice_po_pr_map


def get_account_details(invoice_list):
	account_map = {}
	accounts = list(set([inv.credit_to for inv in invoice_list]))
	for acc in frappe.db.sql(
		"""select name, parent_account from tabAccount
		where name in (%s)"""
		% ", ".join(["%s"] * len(accounts)),
		tuple(accounts),
		as_dict=1,
	):
		account_map[acc.name] = acc.parent_account

	return account_map

def get_party_details(party_type, party_list):
	party_details = {}
	party = frappe.qb.DocType(party_type)
	query = frappe.qb.from_(party).select(party.name, party.tax_id).where(party.name.isin(party_list))
	if party_type == "Supplier":
		query = query.select(party.supplier_group,party.country)
	else:
		query = query.select(party.customer_group, party.territory)

	party_detail_list = query.run(as_dict=True)
	for party_dict in party_detail_list:
		party_details[party_dict.name] = party_dict
	return party_details

@frappe.whitelist()
def uae_acc_list(company):
	#filters={'parent':company},
	return frappe.db.get_all('UAE VAT Account',fields=['account'])

@frappe.whitelist()
def vat_temp_list(company):
	#filters={'parent':company},
	return frappe.db.get_all('Purchase Taxes and Charges Template',fields=['name','title'])


def get_field_precision(doctype, fieldname):
    # Fetch the DocType metadata
    meta = frappe.get_meta(doctype)
    
    # Find the field in the DocType
    field = next((f for f in meta.fields if f.fieldname == fieldname), None)
    
    # Return the precision if the field is found
    if field:
        return field.precision
    else:
        return None