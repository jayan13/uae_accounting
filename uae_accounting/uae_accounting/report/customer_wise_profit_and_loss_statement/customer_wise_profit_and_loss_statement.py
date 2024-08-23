# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
import functools
import math
import re

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	cstr,
	flt,
	formatdate,
	get_first_day,
	getdate,
	today,
)

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_fiscal_year

def execute(filters=None):
	
	
	income = get_data(
		filters.company,
		"Income",
		"Credit",
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
		ignore_accumulated_values_for_fy=True,
	)

	expense = get_data(
		filters.company,
		"Expense",
		"Debit",
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
		ignore_accumulated_values_for_fy=True,
	)
	
	net_profit_loss = get_net_profit_loss(
		income, expense, filters.company, filters.presentation_currency
	)

	data = []
	data.extend(income or [])
	data.extend(expense or [])
	if net_profit_loss:
		data.append(net_profit_loss)

	columns = get_columns(
		filters.accumulated_values, filters.company
	)
	
	return columns, data


def get_net_profit_loss(income, expense, company, currency=None, consolidated=False):
	total = 0
	net_profit_loss = {
		"account_name": "'" + _("Gross Profit / Loss") + "'",
		"account": "'" + _("Gross Profit / Loss") + "'",
		"warn_if_negative": True,
		"currency": currency or frappe.get_cached_value("Company", company, "default_currency"),
	}

	has_value = False
	key = 'total'
	total_income = flt(income[-2][key], 3) if income else 0
	total_expense = flt(expense[-2][key], 3) if expense else 0

	net_profit_loss[key] = total_income - total_expense

	if net_profit_loss[key]:
		has_value = True

	if has_value:
		return net_profit_loss




def get_projects(filters):
	
	projects=[]
	if filters.get('project'):
		projects=filters.get('project')
	else:
		#project=frappe.db.get_all('Sales Invoice',filters={'customer':filters.get('customer'),'docstatus': '1','project':['not in',['null','','None']] },fields=['project'], pluck='project') or []
		#if project and len(project):
		#	projects=project
		if filters.filter_based_on == "Fiscal Year":
			fiscal_year = get_fiscal_year_data(filters.from_fiscal_year, filters.to_fiscal_year)
			validate_fiscal_year(fiscal_year, filters.from_fiscal_year, filters.to_fiscal_year)
			year_start_date = getdate(fiscal_year.year_start_date)
			year_end_date = getdate(fiscal_year.year_end_date)
		else:
			validate_dates(filters.period_start_date, filters.period_end_date)
			year_start_date = getdate(filters.period_start_date)
			year_end_date = getdate(filters.period_end_date)
		pjts=frappe.db.sql(
		"""select DISTINCT if(i.project,i.project,s.project) as project from `tabSales Invoice` s left join `tabSales Invoice Item` i on i.parent=s.name where
		s.posting_date between %(start_date)s and %(end_date)s and s.company=%(company)s and s.customer=%(customer)s and s.docstatus=1 and (i.project not in ('null','None') or s.project not in ('null','None')) """,
		{"start_date": year_start_date, "end_date": year_end_date,'company': filters.company,'customer': filters.customer},
		as_dict=1)
		for p in pjts:
			projects.append(p.project)
	return projects

def get_period_list(
	from_fiscal_year,
	to_fiscal_year,
	period_start_date,
	period_end_date,
	filter_based_on,
	periodicity,
	accumulated_values=False,
	company=None,
	reset_period_on_fy_change=True,
	ignore_fiscal_year=False,
):
	"""Get a list of dict {"from_date": from_date, "to_date": to_date, "key": key, "label": label}
	Periodicity can be (Yearly, Quarterly, Monthly)"""

	if filter_based_on == "Fiscal Year":
		fiscal_year = get_fiscal_year_data(from_fiscal_year, to_fiscal_year)
		validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year)
		year_start_date = getdate(fiscal_year.year_start_date)
		year_end_date = getdate(fiscal_year.year_end_date)
	else:
		validate_dates(period_start_date, period_end_date)
		year_start_date = getdate(period_start_date)
		year_end_date = getdate(period_end_date)

	year_end_date = getdate(today()) if year_end_date > getdate(today()) else year_end_date

	months_to_add = {"Yearly": 12, "Half-Yearly": 6, "Quarterly": 3, "Monthly": 1}[periodicity]

	period_list = []

	start_date = year_start_date
	months = get_months(year_start_date, year_end_date)

	for i in range(cint(math.ceil(months / months_to_add))):
		period = frappe._dict({"from_date": start_date})

		if i == 0 and filter_based_on == "Date Range":
			to_date = add_months(get_first_day(start_date), months_to_add)
		else:
			to_date = add_months(start_date, months_to_add)

		start_date = to_date

		# Subtract one day from to_date, as it may be first day in next fiscal year or month
		to_date = add_days(to_date, -1)

		if to_date <= year_end_date:
			# the normal case
			period.to_date = to_date
		else:
			# if a fiscal year ends before a 12 month period
			period.to_date = year_end_date

		if not ignore_fiscal_year:
			period.to_date_fiscal_year = get_fiscal_year(period.to_date, company=company)[0]
			period.from_date_fiscal_year_start_date = get_fiscal_year(period.from_date, company=company)[1]

		period_list.append(period)

		if period.to_date == year_end_date:
			break

	# common processing
	for opts in period_list:
		key = opts["to_date"].strftime("%b_%Y").lower()
		if periodicity == "Monthly" and not accumulated_values:
			label = formatdate(opts["to_date"], "MMM YYYY")
		else:
			if not accumulated_values:
				label = get_label(periodicity, opts["from_date"], opts["to_date"])
			else:
				if reset_period_on_fy_change:
					label = get_label(periodicity, opts.from_date_fiscal_year_start_date, opts["to_date"])
				else:
					label = get_label(periodicity, period_list[0].from_date, opts["to_date"])

		opts.update(
			{
				"key": key.replace(" ", "_").replace("-", "_"),
				"label": label,
				"year_start_date": year_start_date,
				"year_end_date": year_end_date,
			}
		)

	return period_list


def get_fiscal_year_data(from_fiscal_year, to_fiscal_year):
	fiscal_year = frappe.db.sql(
		"""select min(year_start_date) as year_start_date,
		max(year_end_date) as year_end_date from `tabFiscal Year` where
		name between %(from_fiscal_year)s and %(to_fiscal_year)s""",
		{"from_fiscal_year": from_fiscal_year, "to_fiscal_year": to_fiscal_year},
		as_dict=1,
	)

	return fiscal_year[0] if fiscal_year else {}


def validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year):
	if not fiscal_year.get("year_start_date") or not fiscal_year.get("year_end_date"):
		frappe.throw(_("Start Year and End Year are mandatory"))

	if getdate(fiscal_year.get("year_end_date")) < getdate(fiscal_year.get("year_start_date")):
		frappe.throw(_("End Year cannot be before Start Year"))


def validate_dates(from_date, to_date):
	if not from_date or not to_date:
		frappe.throw(_("From Date and To Date are mandatory"))

	if to_date < from_date:
		frappe.throw(_("To Date cannot be less than From Date"))


def get_months(start_date, end_date):
	diff = (12 * end_date.year + end_date.month) - (12 * start_date.year + start_date.month)
	return diff + 1


def get_label(periodicity, from_date, to_date):
	if periodicity == "Yearly":
		if formatdate(from_date, "YYYY") == formatdate(to_date, "YYYY"):
			label = formatdate(from_date, "YYYY")
		else:
			label = formatdate(from_date, "YYYY") + "-" + formatdate(to_date, "YYYY")
	else:
		label = formatdate(from_date, "MMM YY") + "-" + formatdate(to_date, "MMM YY")

	return label


def get_data(
	company,
	root_type,
	balance_must_be,
	filters=None,
	accumulated_values=1,
	only_current_fiscal_year=True,
	ignore_closing_entries=False,
	ignore_accumulated_values_for_fy=False,
	total=True,
):

	if filters.filter_based_on == "Fiscal Year":
		fiscal_year = get_fiscal_year_data(filters.from_fiscal_year, filters.to_fiscal_year)
		validate_fiscal_year(fiscal_year, filters.from_fiscal_year, filters.to_fiscal_year)
		year_start_date = getdate(fiscal_year.year_start_date)
		year_end_date = getdate(fiscal_year.year_end_date)
	else:
		validate_dates(filters.period_start_date, filters.period_end_date)
		year_start_date = getdate(filters.period_start_date)
		year_end_date = getdate(filters.period_end_date)

	accounts = get_accounts(company, root_type)
	if not accounts:
		return None

	accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

	company_currency = get_appropriate_currency(company, filters)

	gl_entries_by_account = {}
	for root in frappe.db.sql(
		"""select lft, rgt from tabAccount
			where root_type=%s and ifnull(parent_account, '') = ''""",
		root_type,
		as_dict=1,
	):
	
		set_gl_entries_by_account(
			company,
			year_start_date,
			year_end_date,
			root.lft,
			root.rgt,
			filters,
			gl_entries_by_account,
			ignore_closing_entries=ignore_closing_entries,
			root_type=root_type,
		)
	
	calculate_values(
		accounts_by_name,
		gl_entries_by_account,
		year_start_date,
		year_end_date, 
		accumulated_values,
		ignore_accumulated_values_for_fy,
	)
	
	accumulate_values_into_parents(accounts, accounts_by_name)
	
	out = prepare_data(accounts, balance_must_be, year_start_date,year_end_date, company_currency)
	
	out = filter_out_zero_value_rows(out, parent_children_map)

	if out and total:
		add_total_row(out, root_type, balance_must_be, company_currency)
	
	return out


def get_appropriate_currency(company, filters=None):
	if filters and filters.get("presentation_currency"):
		return filters["presentation_currency"]
	else:
		return frappe.get_cached_value("Company", company, "default_currency")


def calculate_values(
	accounts_by_name,
	gl_entries_by_account,
	year_start_date,
	year_end_date, 
	accumulated_values,
	ignore_accumulated_values_for_fy,
):
	for entries in gl_entries_by_account.values():
		for entry in entries:
			
			d = accounts_by_name.get(entry.account)
			d.entry.append(entry)
			if not d:
				frappe.msgprint(
					_("Could not retrieve information for {0}.").format(entry.account),
					title="Error",
					raise_exception=1,
				)
			key='total'
			if entry.posting_date <= year_end_date:
				
				if (accumulated_values or entry.posting_date >= year_start_date) and (
					not ignore_accumulated_values_for_fy or entry.posting_date <= year_end_date
				):
					
					d[key] = d.get(key, 0.0) + flt(entry.debit) - flt(entry.credit)

			if entry.posting_date < year_start_date:
				d["opening_balance"] = d.get("opening_balance", 0.0) + flt(entry.debit) - flt(entry.credit)

def accumulate_values_into_parents(accounts, accounts_by_name):
	"""accumulate children's values in parent accounts"""
	for d in reversed(accounts):
		if d.parent_account:
			key='total'
			
			accounts_by_name[d.parent_account][key] = accounts_by_name[d.parent_account].get(
				key, 0.0
			) + d.get(key, 0.0)

			accounts_by_name[d.parent_account]["opening_balance"] = accounts_by_name[d.parent_account].get(
				"opening_balance", 0.0
			) + d.get("opening_balance", 0.0)


def prepare_data(accounts, balance_must_be, year_start_date,year_end_date, company_currency):
	data = []
	
	for d in accounts:
		# add to output
		
		has_value = False
		total = 0
		row = frappe._dict(
			{
				"account": _(d.name),
				"parent_account": _(d.parent_account) if d.parent_account else "",
				"indent": flt(d.indent),
				"year_start_date": year_start_date,
				"year_end_date": year_end_date,
				"currency": company_currency,
				"include_in_gross": d.include_in_gross,
				"account_type": d.account_type,
				"is_group": d.is_group,
				"opening_balance": d.get("opening_balance", 0.0) * (1 if balance_must_be == "Debit" else -1),
				"account_name": (
					"%s - %s" % (_(d.account_number), _(d.account_name))
					if d.account_number
					else _(d.account_name)
				),
			}
		)
		
		
		key='total'
		if d.get(key) and balance_must_be == "Credit":
			# change sign based on Debit or Credit, since calculation is done using (debit - credit)
			d[key] *= -1

		row[key] =flt(d.get(key, 0.0), 3)

		if abs(row[key]) >= 0.005:
			# ignore zero values
			has_value = True
			total +=flt(row[key])
		
		row["has_value"] = has_value
		#row["total"] = total
		data.append(row)
		#-----------------------------------------------------------------------------------------------------

		pjtarry=[]
		stacc=[0]
		gentry=''
		purchtot=0
		
		if d.account_type=='Cost of Goods Sold':
			if len(d.entry):
				for ent in d.entry:
					if ent.voucher_type=='Sales Invoice':
						if ent.project:
							pjtarry.append(ent.project)

			if len(pjtarry):				
				stacc=frappe.db.get_all("Account",filters={'account_type':'Stock','root_type':'Asset'},pluck="name")
				gentry=frappe.db.get_all("GL Entry",filters={'posting_date':['<=',year_end_date],'posting_date':['>=',year_start_date],'voucher_type':'Purchase Invoice','project':['in',pjtarry],'account':['in',stacc]},fields=['posting_date','voucher_type','voucher_no','project','remarks','account_currency','debit_in_account_currency'])
				#for gl in gentry:
					#purchtot+=gl.debit_in_account_currency

		# gl entry under each account 
		voucher=[]
		etotal=0
		if len(d.entry):
			if gentry:
				for ent in gentry:
					amt=flt(ent.debit_in_account_currency)
					if abs(amt) >= 0.005:

						if amt and balance_must_be == "Credit":			
							amt *= -1

						billno=''
						if ent.voucher_type=='Purchase Invoice':
							billno=frappe.db.get_value(ent.voucher_type,ent.voucher_no,'bill_no') or ''

						row1 = frappe._dict(
							{
								"account":' ',
								"parent_account": _(d.parent_account) if d.parent_account else "",
								"posting_date":ent.posting_date,
								"voucher_type":ent.voucher_type,
								"voucher_no":ent.voucher_no,
								"indent": flt(d.indent+1),
								"year_start_date": year_start_date,
								"year_end_date": year_end_date,
								"project":ent.project,
								"currency": company_currency,
								"include_in_gross": d.include_in_gross,
								"total": flt(amt,3),
								"has_value":True,
								"opening_balance":0.0,
								"bill_no": billno,
								"remarks": str(ent.remarks).strip(),
							}
						)
						voucher.append(row1)
						etotal+=amt

			for ent in d.entry:
				if gentry and ent.voucher_type=='Sales Invoice':
					continue

				amt=flt(ent.debit) - flt(ent.credit)
				if abs(amt) >= 0.005:

					if amt and balance_must_be == "Credit":			
						amt *= -1

					billno=''
					if ent.voucher_type=='Purchase Invoice':
						billno=frappe.db.get_value(ent.voucher_type,ent.voucher_no,'bill_no') or ''

					row2 = frappe._dict(
						{
							"account":' ',
							"parent_account": _(d.parent_account) if d.parent_account else "",
							"posting_date":ent.posting_date,
							"voucher_type":ent.voucher_type,
							"voucher_no":ent.voucher_no,
							"indent": flt(d.indent+1),
							"year_start_date": year_start_date,
							"year_end_date": year_end_date,
							"project":ent.project,
							"currency": company_currency,
							"include_in_gross": d.include_in_gross,
							"total": flt(amt,3),
							"has_value":True,
							"opening_balance":0.0,
							"bill_no": billno,
							"remarks": str(ent.remarks).strip(),
						}
					)
					voucher.append(row2)
					etotal+=amt

			if abs(etotal) >= 0.005:
				row3 = frappe._dict(
					{
						"account":'Total',
						"parent_account": _(d.parent_account) if d.parent_account else "",					
						"indent": flt(d.indent+1),
						"year_start_date": year_start_date,
						"year_end_date": year_end_date,
						"currency": company_currency,
						"include_in_gross": d.include_in_gross,
						"total": flt(etotal,3),
						"has_value":True,
						"opening_balance":0.0
					}
				)
				voucher.append(row3)
			#row.update({'total':etotal})
		#data.append(row)
		if len(voucher):
			data+=voucher

	return data


def filter_out_zero_value_rows(data, parent_children_map, show_zero_values=False):
	data_with_value = []
	for d in data:
		if show_zero_values or d.get("has_value"):
			data_with_value.append(d)
		else:
			# show group with zero balance, if there are balances against child
			children = [child.name for child in parent_children_map.get(d.get("account")) or []]
			if children:
				for row in data:
					if row.get("account") in children and row.get("has_value"):
						data_with_value.append(d)
						break

	return data_with_value


def add_total_row(out, root_type, balance_must_be, company_currency):
	total_row = {
		"account_name": _("Total {0} ({1})").format(_(root_type), _(balance_must_be)),
		"account": _("Total {0} ({1})").format(_(root_type), _(balance_must_be)),
		"currency": company_currency,
		"opening_balance": 0.0,
	}

	for row in out:
		if not row.get("parent_account"):
			total_row.setdefault("total", 0.0)
			total_row["total"] += flt(row["total"])
			total_row["opening_balance"] += row["opening_balance"]

	if "total" in total_row:
		out.append(total_row)

		# blank row after Total
		out.append({})


def get_accounts(company, root_type):
	return frappe.db.sql(
		"""
		select name, account_number, parent_account, lft, rgt, root_type, report_type, account_name, include_in_gross, account_type, is_group, lft, rgt
		from `tabAccount`
		where company=%s and root_type=%s order by lft""",
		(company, root_type),
		as_dict=True,
	)


def filter_accounts(accounts, depth=20):
	parent_children_map = {}
	accounts_by_name = {}
	for d in accounts:
		d.update({'entry':[]})
		accounts_by_name[d.name] = d
		
		parent_children_map.setdefault(d.parent_account or None, []).append(d)

	filtered_accounts = []

	def add_to_list(parent, level):
		if level < depth:
			children = parent_children_map.get(parent) or []
			sort_accounts(children, is_root=True if parent == None else False)

			for child in children:
				child.indent = level
				filtered_accounts.append(child)
				add_to_list(child.name, level + 1)

	add_to_list(None, 0)

	return filtered_accounts, accounts_by_name, parent_children_map


def sort_accounts(accounts, is_root=False, key="name"):
	"""Sort root types as Asset, Liability, Equity, Income, Expense"""

	def compare_accounts(a, b):
		if re.split(r"\W+", a[key])[0].isdigit():
			# if chart of accounts is numbered, then sort by number
			return int(a[key] > b[key]) - int(a[key] < b[key])
		elif is_root:
			if a.report_type != b.report_type and a.report_type == "Balance Sheet":
				return -1
			if a.root_type != b.root_type and a.root_type == "Asset":
				return -1
			if a.root_type == "Liability" and b.root_type == "Equity":
				return -1
			if a.root_type == "Income" and b.root_type == "Expense":
				return -1
		else:
			# sort by key (number) or name
			return int(a[key] > b[key]) - int(a[key] < b[key])
		return 1

	accounts.sort(key=functools.cmp_to_key(compare_accounts))


def set_gl_entries_by_account(
	company,
	from_date,
	to_date,
	root_lft,
	root_rgt,
	filters,
	gl_entries_by_account,
	ignore_closing_entries=False,
	ignore_opening_entries=False,
	root_type=None,
):
	"""Returns a dict like { "account": [gl entries], ... }"""
	gl_entries = []

	account_filters = {
		"company": company,
		"is_group": 0,
		"lft": (">=", root_lft),
		"rgt": ("<=", root_rgt),
	}

	if root_type:
		account_filters.update(
			{
				"root_type": root_type,
			}
		)

	accounts_list = frappe.db.get_all(
		"Account",
		filters=account_filters,
		pluck="name",
	)

	if accounts_list:
		# For balance sheet
		ignore_closing_balances = frappe.db.get_single_value(
			"Accounts Settings", "ignore_account_closing_balance"
		)
		if not from_date and not ignore_closing_balances:
			last_period_closing_voucher = frappe.db.get_all(
				"Period Closing Voucher",
				filters={
					"docstatus": 1,
					"company": filters.company,
					"posting_date": ("<", filters["period_start_date"]),
				},
				fields=["posting_date", "name"],
				order_by="posting_date desc",
				limit=1,
			)
			if last_period_closing_voucher:
				gl_entries += get_accounting_entries(
					"Account Closing Balance",
					from_date,
					to_date,
					accounts_list,
					filters,
					ignore_closing_entries,
					last_period_closing_voucher[0].name,
				)
				from_date = add_days(last_period_closing_voucher[0].posting_date, 1)
				ignore_opening_entries = True

		gl_entries += get_accounting_entries(
			"GL Entry",
			from_date,
			to_date,
			accounts_list,
			filters,
			ignore_closing_entries,
			ignore_opening_entries=ignore_opening_entries,
		)

		if filters and filters.get("presentation_currency"):
			convert_to_presentation_currency(gl_entries, get_currency(filters))

		for entry in gl_entries:
			gl_entries_by_account.setdefault(entry.account, []).append(entry)
		
		return gl_entries_by_account


def get_accounting_entries(
	doctype,
	from_date,
	to_date,
	accounts,
	filters,
	ignore_closing_entries,
	period_closing_voucher=None,
	ignore_opening_entries=False,
):
	gl_entry = frappe.qb.DocType(doctype)
	query = (
		frappe.qb.from_(gl_entry)
		.select(
			gl_entry.party_type,
			gl_entry.party,
			gl_entry.voucher_type,
			gl_entry.voucher_no,			
			gl_entry.against,
			gl_entry.account,
			gl_entry.debit,
			gl_entry.credit,
			gl_entry.debit_in_account_currency,
			gl_entry.credit_in_account_currency,
			gl_entry.account_currency,
			gl_entry.project,
			gl_entry.remarks,
		)
		.where(gl_entry.company == filters.company)
	)
	#custom ^ gl_entry.project,
	if doctype == "GL Entry":
		query = query.select(gl_entry.posting_date, gl_entry.is_opening, gl_entry.fiscal_year)
		query = query.where(gl_entry.is_cancelled == 0)
		query = query.where(gl_entry.posting_date <= to_date)

		if ignore_opening_entries:
			query = query.where(gl_entry.is_opening == "No")
	else:
		query = query.select(gl_entry.closing_date.as_("posting_date"))
		query = query.where(gl_entry.period_closing_voucher == period_closing_voucher)

	query = apply_additional_conditions(doctype, query, from_date, ignore_closing_entries, filters)
	query = query.where(gl_entry.account.isin(accounts))

	entries = query.run(as_dict=True)

	return entries


def apply_additional_conditions(doctype, query, from_date, ignore_closing_entries, filters):
	gl_entry = frappe.qb.DocType(doctype)
	accounting_dimensions = get_accounting_dimensions(as_list=False)

	if ignore_closing_entries:
		if doctype == "GL Entry":
			query = query.where(gl_entry.voucher_type != "Period Closing Voucher")
		else:
			query = query.where(gl_entry.is_period_closing_voucher_entry == 0)

	if from_date and doctype == "GL Entry":
		query = query.where(gl_entry.posting_date >= from_date)

	if filters:
		if filters.get("project"):
			if not isinstance(filters.get("project"), list):
				filters.project = frappe.parse_json(filters.get("project"))

			query = query.where(gl_entry.project.isin(filters.project))
		else: #custom 
			projects=get_projects(filters) 
			if len(projects):
				query = query.where(gl_entry.project.isin(projects))

		if filters.get("cost_center"):
			filters.cost_center = get_cost_centers_with_children(filters.cost_center)
			query = query.where(gl_entry.cost_center.isin(filters.cost_center))

		if filters.get("include_default_book_entries"):
			company_fb = frappe.get_cached_value("Company", filters.company, "default_finance_book")

			if filters.finance_book and company_fb and cstr(filters.finance_book) != cstr(company_fb):
				frappe.throw(_("To use a different finance book, please uncheck 'Include Default FB Entries'"))

			query = query.where(
				(gl_entry.finance_book.isin([cstr(filters.finance_book), cstr(company_fb), ""]))
				| (gl_entry.finance_book.isnull())
			)
		else:
			query = query.where(
				(gl_entry.finance_book.isin([cstr(filters.finance_book), ""]))
				| (gl_entry.finance_book.isnull())
			)

	if accounting_dimensions:
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname):
				if frappe.get_cached_value("DocType", dimension.document_type, "is_tree"):
					filters[dimension.fieldname] = get_dimension_with_children(
						dimension.document_type, filters.get(dimension.fieldname)
					)

				query = query.where(gl_entry[dimension.fieldname].isin(filters[dimension.fieldname]))

	return query


def get_cost_centers_with_children(cost_centers):
	if not isinstance(cost_centers, list):
		cost_centers = [d.strip() for d in cost_centers.strip().split(",") if d]

	all_cost_centers = []
	for d in cost_centers:
		if frappe.db.exists("Cost Center", d):
			lft, rgt = frappe.db.get_value("Cost Center", d, ["lft", "rgt"])
			children = frappe.get_all("Cost Center", filters={"lft": [">=", lft], "rgt": ["<=", rgt]})
			all_cost_centers += [c.name for c in children]
		else:
			frappe.throw(_("Cost Center: {0} does not exist").format(d))

	return list(set(all_cost_centers))


def get_columns(accumulated_values=1, company=None):
	columns = [
		{
			"fieldname": "account",
			"label": _("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 300,
		},
		{
			"fieldname": "posting_date",
			"label": _("Date"),
			"fieldtype": "Date",
			"width": 150,
		},
		{
			"fieldname": "voucher_type",
			"label": _("Type"),
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Voucher"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 150,
		},
		{
			"fieldname": "bill_no",
			"label": _("Supplier Invoice No"),
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"fieldname": "remarks",
			"label": _("Remarks"),
			"fieldtype": "Data",
			"width": 250,
		},
		{
			"label": _("Project"),
			"fieldname": "project",
			"fieldtype": "Link",
			"options": "Project",
			"width": 150,
		},
		{
			"fieldname": "total",
			"label": _("Total"),
			"fieldtype": "Currency",
			"width": 150,
			"options": "currency",
		}
	]
	if company:
		columns.append(
			{
				"fieldname": "currency",
				"label": _("Currency"),
				"fieldtype": "Link",
				"options": "Currency",
				"hidden": 1,
			}
		)

	
	

	return columns


def get_filtered_list_for_consolidated_report(filters, period_list):
	filtered_summary_list = []
	for period in period_list:
		if period == filters.get("company"):
			filtered_summary_list.append(period)

	return filtered_summary_list