# Copyright (c) 2024, alantechnologies and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe.utils import flt, formatdate, getdate, add_days
from datetime import timedelta

def execute(filters=None):
    columns, data = [], []
    columns = get_columns()
    
    # Get the list of dates between from_date and to_date
    date_range = get_date_range(filters.get("from_date"), filters.get("to_date"))
    
    # Fetch sales data and map it by posting date
    sales_data = get_sales_data(filters)
    sales_data_map = {formatdate(d['posting_date'], "yyyy-mm-dd"): d for d in sales_data}
    
    # Fetch payment data (including returns) and map it by posting date
    payment_data = get_payment_data(filters)
    payment_data_map = {formatdate(d['posting_date'], "yyyy-mm-dd"): d for d in payment_data}
    
    # Create final data by mapping dates to sales and payment data, filling with zeros where needed
    data = []
    for day in date_range:
        day_sales = sales_data_map.get(day, {
            "posting_date": day,
            "cost": 0.0,
            "net_amount": 0.0,
            "tax_amount": 0.0,
            "shipping_charge": 0.0,
            "sales_amount": 0.0,
            "total_amount": 0.0
        })

        day_payments = payment_data_map.get(day, {
            "posting_date": day,
            "cash_payment": 0.0,
            "credit_card": 0.0,
            "stripe": 0.0,
            "bank": 0.0,
            "others": 0.0,
            "total": 0.0
        })
        day_sales.update(day_payments)
        data.append(day_sales)

    fildata=[]
    for dt in data:
        lnk=get_rp_link(dt.get('posting_date'),filters)
        dt.update({'posting_date':lnk})
        total=dt.get('cash_payment',0)+dt.get('credit_card',0)+dt.get('stripe',0)+dt.get('bank',0)+dt.get('others',0)
        dt.update({'total':total})
        if dt.get('total_amount',0) !=0 or dt.get('cash_payment',0) !=0 or dt.get('credit_card',0) !=0 or dt.get('stripe',0) !=0 or dt.get('bank',0) !=0 or dt.get('others',0):
            fildata.append(dt)
    return columns, fildata


def get_columns():
    return [

        # Actual columns for sales and receipts under group headings
        {"label": "Date", "fieldname": "posting_date", "fieldtype": "HTML", "width": 120},
        {"label": "Cost", "fieldname": "cost", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Sales Amount", "fieldname": "sales_amount", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Shipping", "fieldname": "shipping_charge", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Total", "fieldname": "net_amount", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Tax", "fieldname": "tax_amount", "fieldtype": "Currency", "options": "Company Currency", "width": 80},
        {"label": "Net Total", "fieldname": "total_amount", "fieldtype": "Currency", "options": "Company Currency", "width": 110},

        # Columns for Receipts section
        {"label": "Cash", "fieldname": "cash_payment", "fieldtype": "Currency", "options": "Company Currency", "width": 110},  
        {"label": "Credit Card", "fieldname": "credit_card", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Stripe", "fieldname": "stripe", "fieldtype": "Currency", "options": "Company Currency", "width": 110}, 
        {"label": "Bank", "fieldname": "bank", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Others", "fieldname": "others", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
        {"label": "Receipt Total", "fieldname": "total", "fieldtype": "Currency", "options": "Company Currency", "width": 110},
    ]

 
def get_date_range(from_date, to_date):
    """Generate a list of all dates between from_date and to_date."""
    from_date = getdate(from_date)
    to_date = getdate(to_date)
    return [(from_date + timedelta(days=i)).strftime('%Y-%m-%d') for i in range((to_date - from_date).days + 1)]

def get_sales_data(filters):
    shpacc=frappe.db.get_all('Vendor Account Mapping',fields=['shipping_revenue_account'],pluck='shipping_revenue_account')
    spacc="','".join(shpacc)
    conditions = ""
    if filters.get("company"):
        conditions += "AND si.company='{}' ".format(filters.get("company"))
    if filters.get("from_date") and filters.get("to_date"):
        conditions += "AND si.posting_date BETWEEN '{}' AND '{}'".format(filters.get("from_date"), filters.get("to_date"))

    query = """
    SELECT 
        si.posting_date,
        SUM(si.base_net_total) AS sales_amount,
        SUM((select sum(c.qty * if(c.incoming_rate,c.incoming_rate,0)) from `tabSales Invoice Item` c where c.item_code <> 'Shipping Charges' and c.parent=si.name group by c.parent)) as cost, >
        SUM((SELECT stc.base_tax_amount
            FROM `tabSales Taxes and Charges` stc 
            WHERE stc.parent = si.name
            AND stc.account_head IN ('{spacc}'))) AS shipping_charge,
        (SUM(si.base_net_total) + SUM(COALESCE(
            (SELECT stc.base_tax_amount
                FROM `tabSales Taxes and Charges` stc 
                WHERE stc.parent = si.name
                AND stc.account_head IN ('{spacc}')), 0))) AS net_amount,
        (SUM(si.base_total_taxes_and_charges) - SUM(COALESCE(
            (SELECT stc.base_tax_amount
                FROM `tabSales Taxes and Charges` stc 
                WHERE stc.parent = si.name
                AND stc.account_head IN ('{spacc}')), 0))) AS tax_amount,   
        SUM(si.base_grand_total) AS total_amount
    FROM 
        `tabSales Invoice` si
    WHERE 
        si.docstatus = 1 {conditions}
    GROUP BY 
        si.posting_date
    ORDER BY 
        si.posting_date DESC
    """.format(conditions=conditions,spacc=spacc)
    return frappe.db.sql(query, as_dict=1)


def get_payment_data(filters):
    conditions = ""
    if filters.get("company"):
            conditions += "AND pe.company='{}' ".format(filters.get("company"))
    if filters.get("from_date") and filters.get("to_date"):
            conditions += "AND pe.posting_date BETWEEN '{}' AND '{}'".format(filters.get("from_date"), filters.get("to_date"))
    query = """
               SELECT 
            pe.posting_date,
            -- Cash Payment, subtract returns 
            SUM(CASE 
                WHEN pe.payment_type = 'Receive' 
                    AND pe.party_type='Customer'
                    AND pe.paid_to IN ('110201 - Cash on hand - Cash Sales - GPEX','110208 - Petty Cash - Office - GPEX') 
                THEN pe.base_paid_amount
                ELSE 0 END) -
            SUM(CASE 
                WHEN pe.payment_type = 'Pay' 
                    AND pe.party_type='Customer'
                    AND pe.paid_from IN ('110201 - Cash on hand - Cash Sales - GPEX','110208 - Petty Cash - Office - GPEX')
                THEN pe.base_paid_amount
                ELSE 0 END) AS cash_payment,
                        -- credi card
                        SUM(CASE 
                WHEN pe.payment_type = 'Receive' 
                    AND pe.party_type='Customer'
                    AND pe.paid_to = '110104 - Network Solutions Card Sales  (AED) - GPEX' 
                THEN pe.base_paid_amount
                ELSE 0 END) -
            SUM(CASE 
                WHEN pe.payment_type = 'Pay' 
                    AND pe.party_type='Customer'
                    AND pe.paid_from = '110104 - Network Solutions Card Sales  (AED) - GPEX' 
                THEN pe.base_paid_amount
                ELSE 0 END) AS credit_card,
                        -- strip
                        SUM(CASE 
                WHEN pe.payment_type = 'Receive' 
                    AND pe.party_type='Customer'
                    AND pe.paid_to = '110106 - STRIPE Payment Gateway - GPEX'
                THEN pe.base_paid_amount
                ELSE 0 END) -
            SUM(CASE 
                WHEN pe.payment_type = 'Pay' 
                    AND pe.party_type='Customer'
                    AND pe.paid_from = '110106 - STRIPE Payment Gateway - GPEX' 
                THEN pe.base_paid_amount
                ELSE 0 END) AS stripe,
                        -- bank
                        SUM(CASE 
                WHEN pe.payment_type = 'Receive' 
                    AND pe.party_type='Customer'
                    AND pe.paid_to IN ('110101 - First Abu Dhabi  Bank - AED - GPEX')
                THEN pe.base_paid_amount
                ELSE 0 END) -
            SUM(CASE 
                WHEN pe.payment_type = 'Pay' 
                    AND pe.party_type='Customer'
                    AND pe.paid_from IN ('110101 - First Abu Dhabi  Bank - AED - GPEX')
                THEN pe.base_paid_amount
                ELSE 0 END) AS bank,
                        -- other
            SUM(CASE 
                WHEN pe.payment_type = 'Receive' 
                    AND pe.party_type='Customer'
                    AND pe.paid_to NOT IN ('110201 - Cash on hand - Cash Sales - GPEX', '110208 - Petty Cash - Office - GPEX', '110104 - Network Solutions Card Sales  (AED) - GPEX', '110106 - STRI>
                THEN pe.base_paid_amount
                ELSE 0 END) -
            SUM(CASE 
                WHEN pe.payment_type = 'Pay' 
                    AND pe.party_type='Customer'
                    AND pe.paid_from NOT IN ('110201 - Cash on hand - Cash Sales - GPEX', '110208 - Petty Cash - Office - GPEX', '110104 - Network Solutions Card Sales  (AED) - GPEX', '110106 - ST>
                THEN pe.base_paid_amount
                ELSE 0 END) AS others
        FROM 
            `tabPayment Entry` pe
        WHERE 
            pe.docstatus = 1 {conditions}
        GROUP BY 
            pe.posting_date
        ORDER BY 
            pe.posting_date DESC
    """.format(conditions=conditions)
    return frappe.db.sql(query, as_dict=1, debug=0)

def get_rp_link(post_date,filters):
    company=filters.get("company")
    from_date=formatdate(getdate(post_date), "yyyy-mm-dd")
    to_date=formatdate(getdate(post_date), "yyyy-mm-dd")
    post_date=formatdate(getdate(post_date), "dd-mm-yyyy")
    rp_url = f'/app/query-report/Tax%20Sales%20Register?company={company}&from_date={from_date}&to_date={to_date}'
    return f'<a href="{rp_url}" target="_blank">{post_date}</a>'