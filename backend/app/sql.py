"""Every SQL statement the dashboard runs. All read from the existing views; nothing is
written to the database. Parameters use psycopg named style: %(name)s."""

COMPANIES = """
SELECT companyname, min(date)::date AS first_date, max(date)::date AS last_date, count(*) AS line_count
FROM salesanalysis
GROUP BY companyname
"""

SALES = """
SELECT companyname, vouchertype, vouchertypename, date::date AS date, voucherno,
       partyledgername, ledgername, ledgergroupl1, stockitemname,
       quantity, actualuom, altquantity, altuom, amount,
       stockgroupl1, stockgroupl2, stockcategory, partygroupl2,
       {route} AS route, {city} AS city, {agent} AS agent, {zone} AS zone,
       statename, mobile, contactname
FROM salesanalysis
WHERE date >= %(start)s
  AND companyname ~ %(company_re)s
  AND (ledgergroupl1 = 'Sales Accounts' OR ledgername = ANY(%(discount_ledgers)s))
"""

OUTSTANDING = """
SELECT companyname, billname, customerguid, customer, billtype, billdate::date AS billdate,
       duedate::date AS duedate, daysfrombilldate, daysfromduedate, originalamount,
       adjustedamount, pendingamount, lastagnstdate::date AS lastagnstdate, creditperiod,
       customergroupl2, customergroupl3, customergroupl4, statename, mobile, contactname
FROM customeroutstanding
WHERE companyname = %(company)s
"""

PAYABLES = """
SELECT companyname, supplierguid, supplier, billname, billtype, billdate::date AS billdate,
       duedate::date AS duedate, daysfrombilldate, daysfromduedate, originalamount,
       adjustedamount, pendingamount, lastagnstdate::date AS lastagnstdate, creditperiod
FROM supplierpayable
WHERE companyname = %(company)s
"""

BILLWISE = """
SELECT companyname, vouchertype, voucherid, voucherdate::date AS voucherdate, voucherno,
       ledgerguid, ledgername, typeofledger, billname, billtype,
       billdate::date AS billdate, duedate::date AS duedate, creditperiod, billlineamount
FROM araptransbillwise
WHERE voucherdate >= %(start)s
  AND companyname ~ %(company_re)s
"""

PURCHASES = """
SELECT companyname, date::date AS date, voucherid, voucherno, vouchertype,
       partyledgername, ledgername, ledgergroupl1, stockitemname, stockgroupl1,
       quantity, actualuom, amount
FROM vw_ledgerinvtxn
WHERE vouchertype IN ('Purchase', 'Debit Note')
  AND ispartyledger = false
  AND ledgergroupl1 = 'Purchase Accounts'
  AND date >= %(start)s
  AND companyname ~ %(company_re)s
"""

# vw_ledgerinvtxn still contains Sales Orders (its exclusion list spells 'SalesOrder'
# without a space). If that view is fixed, point this query at a view that keeps orders.
# orderduedate is a text column: blank on most lines and sometimes "10 Days", so only
# values that look like a date are converted (the rest become NULL).
ORDERS = """
SELECT companyname, vouchertype, date::date AS date, voucherno, partyledgername,
       stockitemname, quantity, actualuom, amount,
       CASE WHEN orderduedate ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(orderduedate, 10)::date END
           AS orderduedate,
       batchlineorderno, preclosereason, preclosuredate::date AS preclosuredate
FROM vw_ledgerinvtxn
WHERE invlineid IS NOT NULL
  AND date >= %(start)s
  AND companyname ~ %(company_re)s
  AND (vouchertype = 'Sales Order'
       OR (vouchertype = 'Sales' AND batchlineorderno IS NOT NULL
           AND batchlineorderno NOT IN ('', 'Not Applicable')))
"""

PRODUCTION = """
SELECT companyname, date::date AS date, voucherid, voucherno, vouchermasterid, enteredby,
       stockitemname, stockitemguid, movementtype, quantity, actualuom, bomname,
       godownname, isscrap
FROM production
WHERE date >= %(start)s
  AND companyname ~ %(company_re)s
"""

# itembom repeats a component when an item was renamed (its name lookup is not
# company-specific), so keep one row per component.
BOM = """
SELECT DISTINCT ON (stockitemguid, bomname, componentserial)
       stockitemguid, stockitemname, bomname, componentserial, componentguid,
       componentstockitemname, qty, uom, headeritemqty, headeritemuom, headeritemaltqty
FROM itembom
WHERE companyname = %(company)s
ORDER BY stockitemguid, bomname, componentserial, componentstockitemname
"""

CLOSING_STOCK = """
SELECT stockitemname, godownname, batchname, closingqty, actualuom, stockgroupl1
FROM closingstock
WHERE companyname = %(company)s
"""

CUSTOMER_MASTER = """
SELECT ledgerguid, ledgername, creditlimit, creditperiod
FROM vw_coa
WHERE companyname = %(company)s
  AND (ledgergroupreservednamel2 = 'Sundry Debtors' OR ledgergroupl2 = 'Sundry Debtors')
"""

VOUCHER_HEADERS = """
SELECT DISTINCT companyname, voucherid, vouchermasterid, voucheralterid, date::date AS date,
       vouchertype, vouchertypename, voucherno, enteredby, partyledgername
FROM vw_ledgerinvtxn
WHERE date >= %(start)s
  AND companyname ~ %(company_re)s
"""

# Columns a dimension setting may point at (guards the {route}/{city}/... substitution)
ALLOWED_DIM_COLUMNS = {
    "partygroupl1", "partygroupl2", "partygroupl3", "partygroupl4", "partygroupl5",
    "partygroupl6", "partygroupl7", "costcentreclass", "zone", "statename", "pincode",
    "address3", "address4", "enteredby", "godownname",
}
