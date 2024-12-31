# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, today


class FullandFinalStatement(Document):
	def before_insert(self):
		self.get_outstanding_statements()

	def validate(self):
		self.validate_relieving_date()
		self.get_assets_statements()
<<<<<<< HEAD
		if self.docstatus == 1:
			self.validate_settlement("payables")
			self.validate_settlement("receivables")
			self.validate_asset()
=======
		self.set_total_asset_recovery_cost()
		self.set_totals()

	def before_submit(self):
		self.validate_settlement("payables")
		self.validate_settlement("receivables")
		self.validate_assets()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry",)
		self.set_gratuity_status()
>>>>>>> 9079dbb1 (fix: refactor code, consider fnf payment status update via journal entry)

	def validate_relieving_date(self):
		if not self.relieving_date:
			frappe.throw(
				_("Please set {0} for Employee {1}").format(
					frappe.bold(_("Relieving Date")),
					get_link_to_form("Employee", self.employee),
				),
				title=_("Missing Relieving Date"),
			)

	def validate_settlement(self, component_type):
		for data in self.get(component_type, []):
			if data.status == "Unsettled":
				frappe.throw(_("Settle all Payables and Receivables before submission"))

	def validate_asset(self):
		for data in self.assets_allocated:
			if data.status == "Owned":
				frappe.throw(_("All allocated assets should be returned before submission"))

	@frappe.whitelist()
	def get_outstanding_statements(self):
		if self.relieving_date:
			if not len(self.get("payables", [])):
				components = self.get_payable_component()
				self.create_component_row(components, "payables")
			if not len(self.get("receivables", [])):
				components = self.get_receivable_component()
				self.create_component_row(components, "receivables")
			self.get_assets_statements()
		else:
			frappe.throw(
				_("Set Relieving Date for Employee: {0}").format(get_link_to_form("Employee", self.employee))
			)

	def get_assets_statements(self):
		if not len(self.get("assets_allocated", [])):
			for data in self.get_assets_movement():
				self.append("assets_allocated", data)

	def create_component_row(self, components, component_type):
		for component in components:
			self.append(
				component_type,
				{
					"status": "Unsettled",
					"reference_document_type": component if component != "Bonus" else "Additional Salary",
					"component": component,
				},
			)

	def get_payable_component(self):
		return [
			"Salary Slip",
			"Gratuity",
			"Expense Claim",
			"Bonus",
			"Leave Encashment",
		]

	def get_receivable_component(self):
		return [
			"Loan",
			"Employee Advance",
		]

	def get_assets_movement(self):
		asset_movements = frappe.get_all(
			"Asset Movement Item",
			filters={"docstatus": 1},
			fields=["asset", "from_employee", "to_employee", "parent", "asset_name"],
			or_filters={"from_employee": self.employee, "to_employee": self.employee},
		)

		data = []
		inward_movements = []
		outward_movements = []
		for movement in asset_movements:
			if movement.to_employee and movement.to_employee == self.employee:
				inward_movements.append(movement)

			if movement.from_employee and movement.from_employee == self.employee:
				outward_movements.append(movement)

		for movement in inward_movements:
			outwards_count = [movement.asset for movement in outward_movements].count(movement.asset)
			inwards_counts = [movement.asset for movement in inward_movements].count(movement.asset)

			if inwards_counts > outwards_count:
				data.append(
					{
						"reference": movement.parent,
						"asset_name": movement.asset_name,
						"date": frappe.db.get_value("Asset Movement", movement.parent, "transaction_date"),
						"status": "Owned",
					}
				)
		return data

	@frappe.whitelist()
	def create_journal_entry(self):
		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")
		jv = frappe.new_doc("Journal Entry")
		jv.company = self.company
		jv.voucher_type = "Bank Entry"
		jv.posting_date = today()

		difference = self.total_payable_amount - self.total_receivable_amount

		for data in self.payables:
			if data.amount > 0 and not data.paid_via_salary_slip:
				account_dict = {
					"account": data.account,
					"debit_in_account_currency": flt(data.amount, precision),
				}
				if data.reference_document_type == "Expense Claim":
					account_dict["party_type"] = "Employee"
					account_dict["party"] = self.employee

				jv.append("accounts", account_dict)

		for data in self.receivables:
			if data.amount > 0:
				account_dict = {
					"account": data.account,
					"credit_in_account_currency": flt(data.amount, precision),
				}
				if data.reference_document_type == "Employee Advance":
					account_dict["party_type"] = "Employee"
					account_dict["party"] = self.employee

				jv.append("accounts", account_dict)

		jv.append(
			"accounts",
			{
				"credit_in_account_currency": difference if difference > 0 else 0,
				"debit_in_account_currency": -(difference) if difference < 0 else 0,
				"reference_type": self.doctype,
				"reference_name": self.name,
			},
		)
		return jv

	def set_gratuity_status(self):
		for payable in self.payables:
			if payable.component != "Gratuity":
				continue
			gratuity = frappe.get_doc("Gratuity", payable.reference_document)
			amount = payable.amount if self.docstatus == 1 and self.status == "Paid" else 0
			gratuity.db_set("paid_amount", amount)
			if self.docstatus == 2:
				gratuity.cancel()
			else:
				gratuity.set_status(update=True)


@frappe.whitelist()
def get_account_and_amount(ref_doctype, ref_document):
	if not ref_doctype or not ref_document:
		return None

	if ref_doctype == "Salary Slip":
		salary_details = frappe.db.get_value(
			"Salary Slip", ref_document, ["payroll_entry", "net_pay"], as_dict=1
		)
		amount = salary_details.net_pay
		payable_account = (
			frappe.db.get_value("Payroll Entry", salary_details.payroll_entry, "payroll_payable_account")
			if salary_details.payroll_entry
			else None
		)
		return [payable_account, amount]

	if ref_doctype == "Gratuity":
		payable_account, amount = frappe.db.get_value("Gratuity", ref_document, ["payable_account", "amount"])
		return [payable_account, amount]

	if ref_doctype == "Expense Claim":
		details = frappe.db.get_value(
			"Expense Claim",
			ref_document,
			["payable_account", "grand_total", "total_amount_reimbursed", "total_advance_amount"],
			as_dict=True,
		)
		payable_account = details.payable_account
		amount = details.grand_total - (details.total_amount_reimbursed + details.total_advance_amount)
		return [payable_account, amount]

	if ref_doctype == "Loan":
		details = frappe.db.get_value(
			"Loan", ref_document, ["payment_account", "total_payment", "total_amount_paid"], as_dict=1
		)
		payment_account = details.payment_account
		amount = details.total_payment - details.total_amount_paid
		return [payment_account, amount]

	if ref_doctype == "Employee Advance":
		details = frappe.db.get_value(
			"Employee Advance",
			ref_document,
			["advance_account", "paid_amount", "claimed_amount", "return_amount"],
			as_dict=1,
		)
		payment_account = details.advance_account
		amount = details.paid_amount - (details.claimed_amount + details.return_amount)
		return [payment_account, amount]


def update_full_and_final_statement_status(doc, method=None):
	print("\n\n at update_full_and_final_statement_status \n\n")
	"""Updates FnF status on Journal Entry Submission/Cancellation"""
	status = "Paid" if doc.docstatus == 1 else "Unpaid"

	for entry in doc.accounts:
		if entry.reference_type == "Full and Final Statement":
<<<<<<< HEAD
			frappe.db.set_value("Full and Final Statement", entry.reference_name, "status", status)
=======
			fnf = frappe.get_doc("Full and Final Statement", entry.reference_name)
			fnf.db_set("status", status)
			fnf.notify_update()
<<<<<<< HEAD
<<<<<<< HEAD


def update_status_of_reference_documents(doc, status="Paid"):
	for payable in doc.payables:
		if payable.component == "Gratuity":
			frappe.db.set_value("Gratuity", payable.reference_document, "status", status)
>>>>>>> 885cf10b (fix: update status of reference documents)
=======
>>>>>>> b5af146f (fix: set gratuity paid_amont field)
=======
			fnf.set_gratuity_status()
>>>>>>> 9079dbb1 (fix: refactor code, consider fnf payment status update via journal entry)
