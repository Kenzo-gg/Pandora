# Pandora — Sales and Inventory Management System

> **Project status:** 🟡 Planning / Development tracking  
> **Project period:** October 21 – November 20, 2026  
> **Team size:** 3 members  
> **Last updated:** October 21, 2026

Pandora is a Sales and Inventory Management System designed to help a store record sales, track stock levels, manage suppliers and restocking, and produce reports. Its goal is to make inventory movements accurate, efficient, and easy to monitor.

**Important:** This README is our project **progress tracker**. Tasks are **unchecked by default** because their completion has not yet been confirmed. Update the checkboxes, status table, and progress log as work is finished.

---

## 📌 Project Goals

- Manage products, categories, prices, and inventory quantities.
- Record sales, compute totals and change, and generate receipts.
- Automatically deduct stock after successful sales.
- Record purchases/restocking from suppliers and automatically add received stock.
- Show reorder-level or low-stock alerts.
- Manage suppliers and view their transaction history.
- Generate sales, inventory, product-movement, and profit/loss reports.
- Export reports to PDF or Excel.
- Support role-based access and database backups.

## 🛠️ Proposed Tech Stack

| Area | Technology |
| --- | --- |
| Backend | Python, Django |
| Frontend | HTML, CSS, Bootstrap, JavaScript (as needed) |
| Database | MySQL |
| Authentication | Django Authentication and Groups |
| Reports / exports | OpenPyXL, ReportLab (or another suitable library) |
| Development tools | VS Code, Git, GitHub |
| Diagrams | diagrams.net (Draw.io) |

> The technologies above are **proposed** until confirmed by the team. Record any changes here and explain them in the final presentation using references.

## 👥 Team Responsibilities

| Team member | Primary responsibility | Main deliverable |
| --- | --- | --- |
| **Member 1:** _Name_ | Database, backend, login, access control, integration | Database models and Crow's Foot ERD |
| **Member 2:** _Name_ | Frontend, products, inventory interface, sales | User interface, receipts, Use Case Diagram |
| **Member 3:** _Name_ | Suppliers, purchasing, reports, exports | Restocking, reports, Data Flow Diagram (DFD) |

**Shared responsibilities:** testing, documentation, reviewing changes, troubleshooting, PowerPoint, and live demonstration.

## 📅 One-Month Milestones

| Week | Dates | Target | Status |
| --- | --- | --- | --- |
| **Week 1** | Oct 21–27 | Setup, database design, diagrams, mockups | 🟡 In progress |
| **Week 2** | Oct 28–Nov 3 | User roles, product and supplier management | ⬜ Not confirmed |
| **Week 3** | Nov 4–10 | Sales, receipts, purchases, automatic stock updates | ⬜ Not confirmed |
| **Week 4** | Nov 11–17 | Reports, export, backup, security, testing | ⬜ Not confirmed |
| **Final** | Nov 18–20 | Documentation, slides, rehearsal, final fixes | ⬜ Not confirmed |

**Milestone statuses:** ⬜ Not started / not confirmed · 🟡 In progress · ✅ Completed · 🔴 Blocked

## ✅ Development Checklist

### Week 1 — Planning and System Design (Oct 21–27)

**Member 1 — Database & Backend**
- [ ] Create the Django project and GitHub repository.
- [ ] Configure the development environment and MySQL connection.
- [ ] Design a normalized database schema with primary and foreign keys.
- [ ] Draw the ERD with Crow's Foot notation and relationship cardinalities.

**Member 2 — Frontend & Sales**
- [ ] Draft user interface mockups (login, dashboard, products, checkout).
- [ ] Set up the base HTML layout and Bootstrap styling.
- [ ] Draw the Use Case Diagram for Administrator, Cashier, and Inventory Clerk.

**Member 3 — Purchasing & Reports**
- [ ] Identify fields needed for supplier, purchase, and report records.
- [ ] Draw the Data Flow Diagram (DFD).
- [ ] Prepare realistic sample products, suppliers, and transactions.

**Week 1 outcome:** Agreed models, diagrams, mockups, and a running starter project.

### Week 2 — User Accounts, Products, and Suppliers (Oct 28–Nov 3)

**Member 1 — Database & Backend**
- [ ] Create Django models, migrations, and database relationships.
- [ ] Implement login/logout and unique user accounts.
- [ ] Set up role-based permissions for Administrator, Cashier, and Inventory Clerk.

**Member 2 — Frontend & Sales**
- [ ] Build the dashboard/navigation layout.
- [ ] Implement product and category add/view/edit/delete interfaces.
- [ ] Display current stock, search/filter products, and show low-stock alerts.

**Member 3 — Purchasing & Reports**
- [ ] Implement supplier add/view/edit/delete features.
- [ ] Create supplier detail pages and prepare transaction-history views.
- [ ] Coordinate purchase form fields with Member 1's models.

**Week 2 outcome:** Authorized users can log in and manage products and suppliers.

### Week 3 — Sales and Restocking (Nov 4–10)

**Member 1 — Database & Backend**
- [ ] Implement reliable inventory update rules for sales and restocking.
- [ ] Prevent sales from creating negative stock.
- [ ] Ensure each transaction and its stock updates succeed or fail together (database transaction).
- [ ] Integrate the sales and purchasing modules.

**Member 2 — Frontend & Sales**
- [ ] Build the sales checkout form/cart.
- [ ] Calculate subtotal, applicable taxes (if any), total, amount received, and change.
- [ ] Save completed sales and their items.
- [ ] Generate a printable sales receipt.

**Member 3 — Purchasing & Reports**
- [ ] Record supplier purchases and received items.
- [ ] Automatically increase inventory when stock is received.
- [ ] Generate purchase-order or stock-in records.
- [ ] Display supplier purchase history.

**Week 3 outcome:** Demonstrate a complete **sale → stock deduction → restock → stock increase** cycle.

### Week 4 — Reports, Security, and Testing (Nov 11–17)

**Member 1 — Database & Backend**
- [ ] Verify permissions for critical actions and sensitive records.
- [ ] Set up and test a database backup and restore procedure.
- [ ] Fix integration bugs and validate stock movement history.

**Member 2 — Frontend & Sales**
- [ ] Add daily, weekly, and monthly sales summaries to the interface.
- [ ] Add record/report filters (date, product type, transaction status where applicable).
- [ ] Improve usability, error messages, and responsive styling.

**Member 3 — Purchasing & Reports**
- [ ] Create inventory status reports.
- [ ] Create fast-moving and slow-moving product reports.
- [ ] Create profit/loss summaries using recorded sales and cost data.
- [ ] Implement PDF and Excel report exports.

**All members**
- [ ] Test the complete transaction flow with sample data.
- [ ] Fix high-priority bugs and verify totals and stock quantities.
- [ ] Check that each role can access only authorized features.

**Week 4 outcome:** Integrated system with working reporting, exports, and security checks.

### Final Days — Presentation and Submission (Nov 18–20)

- [ ] Update and verify the ERD, Use Case Diagram, and DFD against the implemented system.
- [ ] Capture screenshots and sample input/output forms (receipt, stock-in record, reports).
- [ ] Document the final tech stack and cite reasons/references for each choice.
- [ ] Prepare the PowerPoint presentation.
- [ ] Rehearse the complete operation within **45 minutes**.
- [ ] Perform a final test and prepare a working backup/demo dataset.

## 🗃️ Proposed Database Entities

The exact tables and relationships must be finalized during Week 1.

- **Users / Roles** — logins and access permissions.
- **Categories** — product categories.
- **Suppliers** — company and contact details.
- **Products** — product code, name, category, supplier (if applicable), prices, stock, reorder level.
- **Sales** — date, cashier, totals, payment information.
- **Sale_Items** — products, quantities, and selling prices for each sale.
- **Purchases** — supplier, dates, and purchasing/receiving details.
- **Purchase_Items** — products, quantities, and unit costs received.
- **Stock_Movements** — auditable additions and deductions, with references to transactions.

> Keep sales and purchase line items separate from transaction headers to support normalization. Preserve historical transaction prices instead of relying only on a product's current price.

## 🧪 Acceptance Tests / Demo Checklist

Use these tests to confirm a feature truly works before checking off a milestone.

- [ ] An authorized user can log in and access only their allowed pages.
- [ ] An authorized user can create, update, and search for a product.
- [ ] Inventory shows correct stock before a sale.
- [ ] Completing a sale decreases stock by the quantity sold.
- [ ] Trying to sell more units than available is rejected.
- [ ] A completed sale produces a receipt with correct totals and change.
- [ ] Recording received stock increases inventory by the received quantity.
- [ ] A purchase or stock-in record is saved with supplier and items.
- [ ] A product at/below its reorder level triggers a low-stock indication.
- [ ] Daily, weekly, and monthly reports show correct totals.
- [ ] Fast/slow-moving and profit/loss figures match the sample data.
- [ ] PDF and Excel exports open correctly.
- [ ] A backup can be restored successfully.

### Example Full-Cycle Demo

1. Log in as an administrator or appropriate staff member.
2. Create a supplier and a product with **20 units** in stock.
3. Sell **3 units**; verify the receipt and new stock of **17**.
4. Receive **10 units** from the supplier; verify new stock of **27**.
5. Review sales, purchase, inventory movement, and report records.
6. Export a report and demonstrate role-based restrictions.

## 🎤 Presentation Plan (Maximum 45 Minutes)

| Segment | Time | Lead |
| --- | --- | --- |
| Introduction and tech stack with references | 5 min | Member 1 |
| ERD, Use Case Diagram, and DFD | 10 min | All members |
| Live system demonstration | 20 min | Members 2 and 3, Member 1 supports |
| Reports, testing, and security | 5 min | All members |
| Questions and answers | 5 min | All members |
| **Total** | **45 min** | |

## 📝 Progress Log

Add a row whenever a task is completed, a blocker occurs, or an important decision is made.

| Date | Member | Work completed / decision | Status / blocker |
| --- | --- | --- | --- |
| 2026-10-21 | Team | Created initial one-month project tracker | Planning; task completion not yet verified |
| YYYY-MM-DD | Member _ | _Describe change or feature_ | _Done / In progress / Blocked_ |

## 🚧 Issues and Blockers

| Issue | Owner | Next action | Status |
| --- | --- | --- | --- |
| _Add an issue here_ | _Member_ | _Proposed fix_ | _Open / Resolved_ |

## 🤝 Team Workflow

1. Agree on shared model names and fields before starting dependent features.
2. Work on separate Git branches (for example: `feature/database`, `feature/sales`, `feature/purchases-reports`).
3. Make small commits with clear messages; review changes before merging into `main`.
4. Run migrations and test the full project after integrating a feature.
5. Update this README and record blockers at each group check-in.
6. Do a joint integration test at the end of each week.

## 📚 Tech References (for Final Presentation)

- [Django documentation](https://docs.djangoproject.com/en/stable/)
- [Python documentation](https://docs.python.org/3/)
- [MySQL documentation](https://dev.mysql.com/doc/)
- [Bootstrap documentation](https://getbootstrap.com/docs/)
- [Django authentication and authorization](https://docs.djangoproject.com/en/stable/topics/auth/)

---

**Pandora — Sales and Inventory Management System**  
*Built by a team of three. Update this file as development progresses.*
