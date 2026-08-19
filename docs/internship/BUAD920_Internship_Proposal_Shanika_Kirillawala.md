# Internship Proposal — BUAD920 Internship (NZQF Level 9, 30 credits)

**Host organisation:** Wizards Learning Hub — Tuition Delivery & CWA Classroom Platform
**Intern:** Shanika Kirillawala (Student ID 20250356)
**Placement title:** Finance & Business Analysis Intern
**Period:** Thursday 27 August 2026 – Saturday 14 November 2026 (12 weeks, 240 host hours)
**Prepared for:** Academic Internship Coordinator, Auckland Institute of Studies, 28A Linwood Avenue, Mount Albert, Auckland 1025
**Course coordinator:** Mr Martin Mahler (BUAD920), Room A115
**Version:** 1.0 — «date of submission»

---

## Document control

| Item | Detail |
|---|---|
| Document | BUAD920 Internship Proposal — Wizards Learning Hub |
| Prepared by | «Host supervisor name», «position», Wizards Learning Hub |
| Reviewed by | Shanika Kirillawala (intern) |
| Approvals required | Host supervisor · Intern · AIS Academic Supervisor · BUAD920 Course Coordinator |
| Companion documents | Offer of Internship letter (see Appendix D); BUAD920 Course Outline; FINA802 & FINA903 Course Outlines |
| Confidentiality | Contains commercial information about Wizards Learning Hub. For AIS academic assessment purposes only. |

Fields marked «like this» are to be completed by the host organisation before signature.

---

## 1. Executive summary

Wizards Learning Hub offers Shanika Kirillawala a 12-week, 240-hour Finance and Business
Analysis internship that is deliberately engineered against three sets of criteria at once:

1. **BUAD920 Internship** — its four performance capabilities, four knowledge gains, five
   personal skills, and its four assessments (Introductory Report 25%, Management Report 35%,
   Reflective Journal 20%, Presentation 20%).
2. **FINA802 Financial Intelligence** — time value of money, valuation, risk and return,
   investment decision rules and their shortcomings, and capital structure theory.
3. **FINA903 Financial Risk Management** — funding and liquidity risk, market risk (interest
   rate, foreign exchange, commodity), credit risk, operational risk, hedging instruments, and
   the control and governance framework.

The placement is not observational. Shanika will own seven finance workstreams that the
business genuinely needs completed, working on live financial data from live systems, and will
present decision-grade recommendations to the owner at the end of the placement.

**Why this host is an unusually good fit for a Level 9 finance internship.** Wizards Learning
Hub is two businesses under one roof:

- **Arm A — Tuition Delivery.** A face-to-face and online tutoring operation in Auckland: term
  classes, holiday programmes, and student progress reporting. It behaves like a
  capacity-constrained *services* business — its economics are driven by tutor cost, class fill
  rate, venue cost, attendance and fee collection.
- **Arm B — CWA Classroom.** A software platform sold by subscription to schools and institutes
  and directly to individual students. It behaves like a *SaaS* business — its economics are
  driven by subscription tiers, churn, trial conversion, gross margin, and a cost base that is
  substantially denominated in **US dollars** (cloud infrastructure, AI vendors, card
  processing) against revenue that is substantially in **New Zealand dollars**.

That combination hands the intern, in a single small organisation, almost the full FINA802 and
FINA903 syllabus in applied form: contribution margin and break-even analysis, discounted cash
flow and cost of capital, capital budgeting with competing decision rules, receivables and
liquidity management, a real and measurable foreign exchange exposure, credit and operational
risk, and a governance framework that is genuinely immature and therefore genuinely worth
designing. Very few internship hosts can offer a services P&L, a SaaS P&L and a live FX
exposure to the same intern.

**What the business gets.** A management reporting pack it does not currently have, a defensible
unit-economics and pricing model for both arms, a 13-week cash forecast, an investment appraisal
of the product roadmap, an FX policy recommendation, and a risk register with a control
framework. These are real gaps, not manufactured exercises.

---

## 2. Purpose and scope of this proposal

This proposal sets out, for approval by AIS:

- the nature and suitability of the host organisation (§3);
- the intern's academic starting point and what the placement must deliver for her (§4);
- the design principles the placement is built on (§5);
- seven defined workstreams with tasks, data sources, deliverables and hour budgets (§6–§7);
- a week-by-week 12-week work plan and the hours reconciliation to BUAD920's 300-hour
  allocation (§8–§9);
- the supervision, feedback and escalation model (§10);
- how the placement feeds each of the four BUAD920 assessments, including candidate Management
  Report topics (§11);
- a full learning-outcome coverage matrix (§12);
- resources and system access provided (§13);
- data governance, confidentiality and academic integrity arrangements (§14);
- professional conduct expectations (§15);
- compliance and administration, including immigration and attendance obligations (§16);
- risks to the internship and their mitigations (§17); and
- success criteria and approvals (§18–§19).

It is deliberately detailed. The BUAD920 outline places responsibility on the student to be
clear about "timeframes, reporting requirements, procedures for resolving disputes, and
assessment levels of available support", and to be satisfied that "there are sufficient
available resources for the Internship and the assessments to be completed within the specified
timeframe and to the required standard". This document is the host's answer to each of those
points, in writing, before the placement starts.

---

## 3. Host organisation profile — Wizards Learning Hub

### 3.1 Identity and legal status

| Field | Detail |
|---|---|
| Trading name | Wizards Learning Hub |
| Legal entity | «Registered company name» |
| NZBN | «NZBN» |
| GST registered | «Yes / No — GST number» |
| Registered office / place of business | «Address», Auckland, New Zealand |
| Website | wizardslearninghub.co.nz |
| Sector | Education services (tutoring) and educational technology (SaaS) |
| Size | «Headcount: owner/director, tutors (FT/PT), contractors» |
| Financial year end | «31 March / other» |
| Accounting system | «Xero / MYOB / other» |

### 3.2 Arm A — Tuition Delivery (the classes)

Wizards Learning Hub delivers tutoring to school-age students in Auckland across mathematics,
coding, science and related subjects, in term-time classes and in school-holiday programmes.
The operating model is:

- students are enrolled into **classes** within **departments**;
- classes meet in scheduled **sessions**, and attendance is recorded per student per session;
- fees are billed against attendance — either on class days *held* or class days *attended*,
  depending on the fee configuration — at a daily rate set per department or per student
  (including $0 rates for scholarship places);
- invoices move from draft to issued, are emailed to the student, linked parents and guardians,
  and are settled by bank transfer, cash or cheque;
- bank transfers are reconciled by importing a bank CSV and mapping payer names to students,
  with overpayments held as a **student credit balance**.

The finance-relevant characteristics of this arm are: revenue is a function of enrolment ×
attendance × rate; direct cost is tutor hours; the largest fixed costs are venue and
administration; and cash conversion depends on invoice issue discipline and follow-up of
overdue accounts. It is, in other words, a textbook contribution-margin and working-capital
problem — with the data already captured in a system rather than in shoeboxes.

The business previously operated its student administration on a third-party tutoring platform
and has migrated that data in-house, which means historical enrolment records are available for
trend analysis.

### 3.3 Arm B — CWA Classroom (the platform)

CWA Classroom is a multi-tenant web platform built by the business and sold as a subscription.
It carries class and curriculum management, attendance, homework, student progress reporting,
quizzes and live quiz sessions, worksheets, an AI-assisted question-import and grading facility,
invoicing for the institutes that use it, and an administrative and reporting layer.

**Revenue model (current list prices):**

| Line | Price | Notes |
|---|---|---|
| Individual student | $19.90 / month | 14-day free trial; access blocked if not converted |
| Institute — Basic | $89 / month | 5 classes, 100 students, 500 invoices/yr, $0.30 per extra invoice |
| Institute — Silver | $129 / month | 10 classes, 200 students, 750 invoices/yr, $0.25 extra |
| Institute — Gold | $159 / month | 15 classes, 300 students, 1,000 invoices/yr, $0.20 extra |
| Institute — Platinum | $189 / month | 20 classes, 400 students, 2,000 invoices/yr, $0.15 extra |
| Module add-ons | $10 / month each | Teacher attendance, student attendance, progress reports |
| AI modules | tiered | Monthly page quotas (e.g. 300 / 600 / 1,000 pages) |

Subscriptions are collected through a card processor; discount codes, promotional codes and
fully-discounted (free) accounts exist and must be handled correctly in any revenue analysis —
a 100%-discount subscription never reaches the processor and correctly contributes $0 cash.

**Cost base.** The platform's direct cost of service is dominated by:

- **cloud infrastructure** — application servers, managed database, cache and object storage,
  billed monthly in **USD**;
- **AI vendor charges** — usage-based charges from two large-language-model vendors, billed in
  **USD**, and now fetched from each vendor's billing API rather than estimated (an earlier
  estimation approach silently understated AI cost by a large margin when a model changed and
  the assumed rate did not — a documented control failure that is directly relevant to
  workstream WS6);
- **payment processing fees** — a percentage plus fixed fee per transaction, with an additional
  currency-conversion margin where the settlement currency differs;
- **development and support labour**.

The business also records operating expenses by category (rent, utilities, salaries, supplies,
transport, maintenance, marketing, other), by department, with recurring expenses materialised
monthly and vendor charges synchronised from source — so an expense-side dataset already
exists.

### 3.4 The structural finance question the business has not yet answered

Two arms share one owner, one brand, one administrative overhead and one bank account. Neither
arm currently carries a fully-loaded margin. The business does not know, with evidence:

- what a tutoring class actually contributes after tutor, venue and administration cost, or at
  what fill rate a class breaks even;
- what a subscribing institute actually costs to serve once infrastructure and AI usage are
  allocated, or which plan tier is the most and least profitable;
- how much margin moves when the NZD/USD rate moves;
- which of the candidate product investments on the roadmap is worth funding first; or
- what its cash position will be in 13 weeks.

That gap is the internship.

---

## 4. The intern and the academic context

### 4.1 The intern

Shanika Kirillawala (ID 20250356) is a postgraduate business student at AIS whose taught
programme is finance-weighted. She brings, at minimum:

| Course | Capability brought to the placement |
|---|---|
| ACCT801 Accounting for Managers | Financial statement preparation and interpretation for management decisions |
| FINA802 Financial Intelligence | Time value of money; equity and instrument valuation; risk and return; investment decision rules and their shortcomings; sources of finance and capital structure theory |
| FINA903 Financial Risk Management | Funding, liquidity, interest rate, FX, commodity, credit and operational risk; procurement and management of funds; financial instruments for hedging; embedded derivatives; regulatory and control frameworks |

FINA802's assessed work required her to compute beta from five years of monthly data, apply
CAPM, value equity with single-stage and multi-stage dividend discount models, build and analyse
a three-asset portfolio (returns, standard deviations, betas, pairwise correlations, risk-return
scatter), price bonds under a rate shock, analyse debt/equity and interest coverage trends
against a peer, apply trade-off and pecking-order theory, and compute cost of debt, WACC,
payback, NPV, IRR and PI with a justified recommendation. FINA903 required her to assess and
manage the full risk taxonomy, recommend a funding strategy, and propose and justify hedging
instruments within a control framework.

This placement is designed so that every one of those techniques is exercised again — but
against a **private, unlisted, dual-arm SME** rather than a listed company. That transfer is not
trivial, and it is where the Level 9 learning sits. Appendix E sets out, technique by
technique, how each listed-company method must be adapted here (for example: no observable
share price, so beta must come from unlevered comparable-company betas re-levered to the
company's own capital structure; no dividend history, so DDM gives way to free-cash-flow
valuation; no NZX bond issuance, so cost of debt comes from actual facility pricing and
interest expense over interest-bearing debt).

### 4.2 What BUAD920 requires, and how this proposal answers it

The BUAD920 outline defines the internship's purpose as applying classroom management theory in
a workplace to gain insight into real-world business problems, and lists four performance
capabilities, four knowledge gains and five personal skills. It also prescribes an **enquiry
approach**: begin with questions, record observations and data, analyse for patterns, conclude
with insight or possible solutions.

Every workstream in §6 is written in that form — it opens with a business question, names the
observations and data to be recorded, and ends in an analysed deliverable with a recommendation.
The reflective journal prompts in Appendix C are drawn directly from the enquiry questions the
outline suggests (organisation structure, funding source and resource allocation, history and
future, knowledge and skills used and gained, staff and client dynamics, goals and whether they
are met, what is effective and ineffective, what the intern would change, and how she has
grown).

### 4.3 Variation to the standard pattern — and why it should be approved

The BUAD920 indicative time allocation describes the placement as "normally 30 hours per week
for eight weeks" = 240 hours. This placement delivers the **same 240 hours** as **20 hours per
week over 12 weeks**, on Thursdays and Fridays (8 working hours each, plus a 1-hour unpaid
break) and Saturdays (4 working hours, plus a 30-minute break).

The host asks AIS to approve this pattern on three grounds:

1. **Hours are unchanged.** 20 × 12 = 240 host hours exactly, and the full 300-hour course
   allocation reconciles (§9).
2. **The longer elapsed window materially improves the academic output.** Several workstreams
   are inherently month-boundary dependent — a month-end close, an invoicing run, a subscription
   billing cycle, a vendor invoice, an FX movement. Eight weeks spans two month-ends; twelve
   weeks spans three, giving the intern a second and third observation of the same cycle and
   turning a snapshot into a trend. The Management Report is stronger for it.
3. **Saturday attendance places her in the tuition arm at its busiest.** Saturday is a live
   teaching day. Being on site while classes run is what converts the tuition-arm analysis from
   a spreadsheet exercise into observed operational reality — which is precisely what
   performance capability 3 ("develop practical perspectives linking principles, theories, and
   academic content to workplace applications") asks for.

The host confirms the intern will be released, without deduction from her hours, for any AIS
academic supervision meeting, workshop or drop-in session (including the Wednesday BUAD920
tutorial) that falls during the placement.

---

## 5. Design principles

The placement is built on five rules, and the host will be held to them:

1. **Real data, real decisions.** Every workstream uses live company data and ends in a
   recommendation the owner will actually respond to — accept, reject, or defer with reasons.
   No sandbox exercises.
2. **Question first, spreadsheet second.** Each workstream opens with the business question, in
   the enquiry form BUAD920 requires. The analysis exists to answer it.
3. **Method is stated, not hidden.** Every calculation is delivered with its formula, inputs,
   source and assumptions visible. This is the FINA802 rubric standard ("all workings are
   shown", "clear explanations of formulas and steps") and it is also how the business will be
   able to re-run the analysis after she leaves.
4. **Assumptions are owned.** Where data is missing or unreliable, the intern states the
   assumption and the sensitivity of the conclusion to it rather than quietly picking a number.
   A missing figure must look missing.
5. **Nothing is delivered without a limitation section.** Every report names what it could not
   establish and what it would take to establish it. Distinction-level Level 9 work is
   self-critical.

---

## 6. Workstreams

Seven workstreams. Hours shown are host hours; the total is 240 including induction, supervision
and presentation preparation on site (see §8).

Legend for the mapping column — **PC** = BUAD920 performance capability 1–4; **KG** = knowledge
gain A–D; **PS** = personal skill i–v; **F802** = FINA802 learning outcome; **F903** = FINA903
performance capability / knowledge gain.

---

### WS1 — Financial baseline and the monthly management reporting pack

**Business question.** *What does this business actually earn and spend, by arm, and how would
the owner know each month without asking anyone?*

**Why it matters.** There is no standing management reporting pack. Revenue sits in the card
processor and in the invoicing ledger; costs sit in expense records, vendor charge syncs and the
accounting system. Nobody has put them in one place, by arm, on a comparable basis.

**Tasks.**
1. Map the financial data landscape: every source of revenue and cost, its system of record, its
   currency, its update frequency, and its reliability.
2. Build a 12-month profit and loss, split **Tuition Delivery / CWA Classroom / shared
   overhead**, with a documented and defensible overhead allocation basis (and a note on why the
   basis was chosen and how the result changes under an alternative basis).
3. Extract a balance sheet snapshot and a cash flow summary for the same period.
4. Compute the standard ratio set — gross margin, operating margin, current ratio, quick ratio,
   debtor days, expense-to-revenue by category, revenue per tutor hour, revenue per subscribing
   institute — with definitions.
5. Design a **one-page monthly management reporting pack** template plus a supporting detail
   pack, and the month-end close checklist that produces it.
6. Run the pack live for the month-ends falling inside the placement, and hand it over with
   instructions.

**Data sources.** Expense records by category and department; recurring-expense materialisation;
vendor charge sync; card-processor revenue reporting (actual paid invoices, post-discount,
post-refund); invoicing ledger, payments and credit transactions; the accounting system;
bank statements.

**Deliverables.** D1.1 Financial data map · D1.2 12-month segmented P&L, balance sheet and cash
flow with ratio pack · D1.3 Monthly management pack template · D1.4 Month-end close checklist.

**Hours.** 34 · **Weeks.** 1–4, then recurring monthly.

**Mapping.** PC 2, 3 · KG A, B, C · PS iii · F802 financial statement literacy · F903 KG a, b.

---

### WS2 — Unit economics and pricing architecture

**Business question.** *Which classes and which subscription tiers make money, once every cost
is loaded — and are the current prices right?*

**Why it matters.** Prices for both arms were set by judgement. Neither has been tested against
a fully-loaded cost. The SaaS tiers in particular bundle usage-metered resources (invoice
volumes, AI page quotas) at flat monthly prices, which is a margin risk that has never been
quantified.

**Tasks — Tuition arm.**
1. Build a contribution-margin model per class and per student: fee revenue less tutor cost,
   materials, venue, and an allocated share of administration.
2. Compute break-even fill rate per class format and per venue, and compare to actual fill rates
   and attendance.
3. Model holiday-programme economics separately (short duration, different cost shape, different
   marketing spend).
4. Identify loss-making classes and quantify the options: reprice, re-timetable, merge, or close.

**Tasks — SaaS arm.**
5. Build a fully-loaded cost-to-serve per subscribing institute: allocated infrastructure, AI
   vendor charges, payment processing, support time. Derive **gross margin by plan tier**.
6. Test the metered bundles: at what invoice volume and at what AI page volume does a Basic /
   Silver / Gold / Platinum account stop being profitable? Compare the overage rates ($0.30 down
   to $0.15 per extra invoice) to actual marginal cost.
7. Compute **ARPU, gross churn, net revenue retention, customer acquisition cost, CAC payback
   period and customer lifetime value** for both the individual ($19.90) and institute lines.
   LTV is to be computed as a **discounted** cash flow, not an undiscounted multiple — this is
   the direct application of FINA802's time-value-of-money and perpetuity-with-growth methods to
   a subscription contract, and the discount rate is the WACC derived in WS4.
8. Analyse the **14-day free trial**: trial-to-paid conversion rate, cost of servicing a
   non-converting trial, and the cash-timing effect of the trial window.
9. Produce a pricing recommendation with modelled revenue and margin impact, price-elasticity
   assumptions stated, and a downside case.

**Deliverables.** D2.1 Tuition contribution-margin and break-even model · D2.2 SaaS
cost-to-serve and gross-margin-by-tier model · D2.3 Subscription metrics pack (ARPU, churn, NRR,
CAC, CAC payback, discounted LTV, LTV:CAC) · D2.4 Trial conversion analysis · D2.5 Pricing
recommendation memo with scenarios.

**Hours.** 46 · **Weeks.** 3–8.

**Mapping.** PC 1, 2, 3 · KG A, C · PS i, iii · F802 LO2 (time value of money, valuation), LO4
(risk and return) · F903 PC 1, KG a, b, c.

---

### WS3 — Working capital, receivables and cash flow forecasting

**Business question.** *How much cash will this business have in 13 weeks, and what is trapped
in unpaid fees?*

**Why it matters.** The tuition arm bills in arrears against attendance and collects by bank
transfer reconciled from a CSV. That is a working-capital cycle with real leakage risk: invoices
not issued, invoices issued and not chased, payments received and not matched to a student,
credit balances sitting unapplied. Liquidity risk in an SME is rarely about solvency; it is
about timing.

**Tasks.**
1. Build an **accounts receivable ageing** (current, 30, 60, 90+ days) from the invoicing ledger;
   quantify total receivables and concentration by student, class and department.
2. Compute **debtor days / DSO** and its trend; identify the invoice-to-cash cycle time and where
   the days actually go.
3. Audit invoice **completeness**: reconcile sessions held and attendance recorded against
   invoices issued, and quantify any uninvoiced delivery (gap invoicing). Uninvoiced delivered
   teaching is a pure cash leak.
4. Audit the **bank CSV reconciliation** process: unmatched payment rate, manual-intervention
   rate, aged unapplied credit balances; recommend process and control improvements.
5. Propose a **bad-debt provisioning policy** and a **credit policy** for fee accounts (terms,
   reminder cadence, escalation, when to stop service), and quantify the current implied
   bad-debt rate.
6. Build a **13-week rolling cash flow forecast** with direct-method receipts and payments,
   including the subscription billing cycle, vendor payment dates, payroll dates and tax dates.
   Include an actual-versus-forecast variance sheet so the model is testable.
7. Recommend a **minimum liquidity buffer / cash runway policy** and test it against the
   forecast's downside scenario.

**Deliverables.** D3.1 AR ageing and DSO analysis · D3.2 Invoice completeness / revenue leakage
audit · D3.3 Reconciliation process review with control recommendations · D3.4 Credit and
bad-debt policy proposal · D3.5 13-week rolling cash flow forecast model with variance tracking
· D3.6 Liquidity buffer policy recommendation.

**Hours.** 40 · **Weeks.** 2–9.

**Mapping.** PC 1, 2, 3 · KG A, B, C · PS ii, iii, iv · F802 LO2 · F903 PC 1, 2 (funding and
liquidity risk; credit risk), KG a, b.

---

### WS4 — Cost of capital and capital budgeting for the roadmap

**Business question.** *Of the investments the business is considering, which should be funded
first — and what hurdle rate should any of them clear?*

**Why it matters.** Development capacity is the scarcest resource in the business and it is
currently allocated by intuition. There is no hurdle rate, so no proposal has ever been
rejected on financial grounds.

**Tasks.**
1. **Cost of debt.** Derive the average cost of debt from actual interest expense over total
   interest-bearing debt, cross-checked against current facility pricing. Where the business
   carries no debt, derive an indicative SME borrowing rate and state the basis.
2. **Cost of equity.** CAPM, adapted for an unlisted company: risk-free rate from current NZ
   government bond yields; equity risk premium stated with source; beta from a set of listed
   comparable education / education-technology companies, **unlevered and re-levered** to the
   company's own target capital structure; plus an explicit, justified size and illiquidity
   premium. The comparable set and the adjustment must be argued, not asserted.
3. **WACC.** Combine at target weights, after tax at the NZ company rate, and state the range —
   a point estimate for an SME's WACC is false precision, so deliver a range with a base case.
4. **Appraise four candidate investments**, each with a five-year cash flow forecast:
   - **C1** — automate invoice PDF rendering and email delivery end-to-end (cost saved: admin
     hours; revenue effect: faster cash collection);
   - **C2** — expand the AI question-import and AI grading modules to a higher quota tier
     (revenue: module subscriptions; cost: AI vendor charges that scale with usage — margin is
     the whole question);
   - **C3** — commercialise the live-quiz product as a separately-priced module;
   - **C4** — open a second tuition venue or add a Saturday holiday-programme stream (a
     capacity investment in the tuition arm, for contrast with three software investments).
5. For each: **Payback period, discounted payback, NPV, IRR and Profitability Index**, ranked.
6. **Critically evaluate the decision rules against each other** — where IRR and NPV disagree and
   why (scale differences, non-conventional cash flows, multiple IRRs, the reinvestment-rate
   assumption); why payback survives in practice despite ignoring the time value of money and
   everything past the cut-off; when PI is the right rule (capital rationing — which is exactly
   this business's situation). This is FINA802 LO1 in its natural habitat.
7. **Sensitivity and scenario analysis** — one-way sensitivity on the two or three variables that
   matter, plus a downside scenario; identify the breakeven value of the key driver.
8. Produce a **capital allocation recommendation** to the owner, ranked, with the hurdle rate and
   a proposed standing appraisal process for future proposals.

**Deliverables.** D4.1 WACC derivation paper (with the unlisted-company adjustments argued)
· D4.2 Four investment appraisal models · D4.3 Decision-rule critique · D4.4 Sensitivity and
scenario analysis · D4.5 Capital allocation recommendation memo · D4.6 Standing investment
appraisal template for future proposals.

**Hours.** 44 · **Weeks.** 5–10.

**Mapping.** PC 1, 2, 3 · KG A, C · PS iii · F802 LO1 (decision rules and their shortcomings),
LO2, LO4 · F903 PC 1, 3, KG a, c.

---

### WS5 — Foreign exchange, vendor cost and market risk

**Business question.** *The business earns New Zealand dollars and pays a meaningful share of
its costs in US dollars. How much is that worth, and should it be hedged?*

**Why it matters.** This is a genuine, measurable, unmanaged exposure — not a case study.
Cloud infrastructure, both AI vendors and card-processing conversion margins are USD-referenced;
tuition fees and most subscription revenue are NZD. Nobody has quantified the exposure or
formed a policy on it.

**Tasks.**
1. **Quantify the exposure.** Build a currency-split cost base from actual vendor charges over
   at least 12 months. Separate:
   - **transaction exposure** — committed and forecast USD payables over the next 12 months;
   - **translation exposure** — any USD-denominated balances at reporting date;
   - **economic exposure** — how a sustained NZD/USD shift changes competitiveness and margin,
     including the AI cost that scales with customer usage.
2. **Sensitivity.** Model gross margin and operating margin at NZD/USD scenarios (e.g. ±5%,
   ±10%, ±15% from spot), by arm and in total. Express the result as "cents of margin per
   NZD/USD cent" so it is intelligible to the owner.
3. **Interest rate risk.** Assess exposure on any term debt, overdraft or lease obligations to an
   OCR change; if the business is debt-free, assess the rate risk it *would* take on under the
   WS7 funding options and under the WS4 investment programme.
4. **Input cost risk.** Assess exposure to non-FX input cost movement — venue lease review,
   electricity, wage inflation against tutor rates — as the practical SME analogue of commodity
   price risk.
5. **Evaluate the hedging toolkit** available to an NZ SME, with the mechanics, cost, accounting
   treatment and suitability of each:
   - natural hedging (USD revenue matching, invoicing offshore customers in USD);
   - a **USD-denominated bank account** and matching of receipts to payables;
   - **FX forward contracts** (including how a small book is actually executed and what credit
     line a bank requires);
   - **FX options** and collars, and why the premium may or may not be justified at this scale;
   - **vendor-side commercial hedges** — annual prepayment or committed-use discounts with cloud
     and AI vendors, which convert a variable USD exposure into a fixed one and often at a
     discount, and are frequently the correct answer at this size;
   - **contractual pass-through** — repricing or indexation clauses in customer terms.
6. **Recommend a policy** with a stated hedge ratio, tenor, instrument, approval authority and
   review cadence — and justify why the recommended instrument beats the alternatives at this
   scale. Include a short, honest treatment of the **hedge accounting** consequences (hedge
   designation, documentation and effectiveness testing requirements, and why an SME may
   rationally choose *not* to seek hedge accounting and simply accept P&L volatility), and note
   where **embedded derivatives** could arise in customer or vendor contracts (for example a
   contract denominated in a currency that is not the functional currency of either party).

**Deliverables.** D5.1 Currency exposure quantification · D5.2 Margin sensitivity model to
NZD/USD · D5.3 Interest rate and input cost risk assessment · D5.4 Hedging instrument evaluation
· D5.5 FX risk management policy recommendation with hedge accounting note.

**Hours.** 34 · **Weeks.** 6–11.

**Mapping.** PC 1, 2, 3 · KG A, C · PS iii · F802 LO4 · F903 PC 1, 2, 4, 5 (market risk;
instruments; derivatives and hedging; embedded derivatives), KG d, e, f.

---

### WS6 — Risk register, internal controls and governance framework

**Business question.** *What can go financially wrong here, who owns it, and what stops it?*

**Why it matters.** The business runs on a small team with concentrated authority and automated
money flows. It has already experienced at least one documented control failure of exactly the
type this workstream exists to prevent: AI cost was estimated from an assumed rate rather than
fetched from the vendor, the underlying model changed, the assumed rate did not, and a large
share of real cost went unrecorded until someone noticed. That is an operational risk event with
a direct P&L consequence, and it is a legitimate, non-hypothetical case study for the report.

**Tasks.**
1. Build a **financial and operational risk register** — risk, category, cause, consequence,
   inherent likelihood × impact, existing control, control effectiveness, residual rating, owner,
   treatment, review date. Categories to cover at minimum:
   - **funding and liquidity** — cash runway, concentration of receipts, seasonality of term fees;
   - **credit** — fee default by families; non-payment or failure of a subscribing institute;
     concentration risk if one institute is a large share of SaaS revenue;
   - **market** — NZD/USD (WS5), interest rate, input cost;
   - **operational** — payment/webhook failure causing unrecorded revenue; duplicate or missed
     invoicing; vendor cost runaway; reconciliation error; key-person dependency on the owner;
     supplier concentration on a single cloud and two AI vendors; service outage;
   - **compliance and regulatory** — GST and income tax obligations, PAYE, the Privacy Act 2020
     as it applies to children's education data, consumer and contract obligations to schools,
     and card-industry obligations discharged via the payment processor;
   - **strategic** — dependence of the SaaS arm on a small number of reference customers.
2. Assess and document the **existing control environment**: what is automated, what is manual,
   what is undocumented, what depends entirely on one person.
3. Design a **control framework proportionate to an SME** — a delegation-of-authority and
   approval matrix, segregation of duties where headcount allows and compensating controls where
   it does not, a month-end close checklist (from WS1), a vendor-cost variance alert threshold,
   a revenue-completeness reconciliation (billing system to processor to bank), and a quarterly
   risk review cadence. Present it against the three-lines model, and argue explicitly what
   should and should not be adopted at this size — recommending a large-corporate framework
   wholesale to a small business is a failure of judgement, not a display of knowledge.
4. Write a **business continuity and key-person note**: what happens to invoicing, payroll and
   platform operation if the owner is unavailable for two weeks.

**Deliverables.** D6.1 Risk register (live document, handed over) · D6.2 Control environment
assessment · D6.3 Proposed control and governance framework with approval matrix · D6.4 Business
continuity / key-person note · D6.5 Written case study of the AI cost control failure, its root
cause and the control that now prevents it.

**Hours.** 32 · **Weeks.** 4–11.

**Mapping.** PC 1, 2, 3, 4 · KG A, C, D · PS ii, iii, iv · F903 PC 1, 6 (responsibilities for
financial risk, regulatory requirements, and the control framework), KG a.

---

### WS7 — Funding strategy and capital structure

**Business question.** *If the business funds the WS4 investment programme, where should the
money come from?*

**Why it matters.** The WS4 recommendation is not actionable without a funding answer, and the
funding answer determines the WACC that WS4 discounts at. The two workstreams close a loop, and
recognising that loop is itself Level 9 reasoning.

**Tasks.**
1. Establish the current capital structure: debt/equity ratio and interest coverage (EBIT ÷
   interest expense) over the available history, and the trend.
2. Compare against an appropriate benchmark — a listed or private peer in education services or
   ed-tech SaaS, with the choice of peer **justified** on business model, size and cost
   structure, and with the limitations of the comparison stated honestly.
3. Evaluate the realistic funding sources for an Auckland SME at this stage: retained earnings,
   further owner equity, bank term debt and overdraft (and what security a bank would require),
   asset finance, government innovation grants and R&D support, revenue-based finance, and
   angel/seed equity — each with cost, dilution, covenant burden, speed and control implications.
4. Apply **trade-off theory** (tax shield against financial distress and agency cost, for a
   business with few tangible assets to secure lending against) and **pecking order theory**
   (why an owner-operated SME with asymmetric information almost always funds internally first)
   to this specific business, and say which better explains and better guides its behaviour.
5. Recommend a funding path for the WS4 programme, with a target capital structure, an interest
   coverage floor as a self-imposed covenant, and trigger conditions for moving to the next
   funding source.

**Deliverables.** D7.1 Capital structure and coverage trend analysis · D7.2 Peer benchmark with
justification and limitations · D7.3 Funding options evaluation matrix · D7.4 Capital structure
theory application · D7.5 Funding strategy recommendation.

**Hours.** 26 · **Weeks.** 8–12.

**Mapping.** PC 1, 2, 3 · KG A, C · PS iii · F802 LO1, LO5 (sources of finance and capital
structure theory) · F903 PC 1, 3 (recommend a strategy on the procurement and management of
funds), KG a, c.

---

## 7. Deliverables register

| # | Deliverable | WS | Due (week) | Audience |
|---|---|---|---|---|
| D1.1 | Financial data map | 1 | 2 | Host supervisor |
| D1.2 | 12-month segmented P&L, balance sheet, cash flow, ratio pack | 1 | 4 | Owner |
| D1.3 | Monthly management reporting pack template | 1 | 5 | Owner |
| D1.4 | Month-end close checklist | 1 | 5 | Owner |
| D2.1 | Tuition contribution margin & break-even model | 2 | 6 | Owner |
| D2.2 | SaaS cost-to-serve & gross margin by tier | 2 | 7 | Owner |
| D2.3 | Subscription metrics pack (ARPU, churn, NRR, CAC, LTV) | 2 | 8 | Owner |
| D2.4 | Trial conversion analysis | 2 | 8 | Owner |
| D2.5 | Pricing recommendation memo | 2 | 8 | Owner |
| D3.1 | AR ageing & DSO analysis | 3 | 4 | Owner |
| D3.2 | Invoice completeness / revenue leakage audit | 3 | 6 | Owner |
| D3.3 | Reconciliation process review | 3 | 7 | Owner |
| D3.4 | Credit & bad-debt policy proposal | 3 | 8 | Owner |
| D3.5 | 13-week rolling cash flow forecast model | 3 | 9 | Owner |
| D3.6 | Liquidity buffer policy | 3 | 9 | Owner |
| D4.1 | WACC derivation paper | 4 | 7 | Owner |
| D4.2 | Four investment appraisal models | 4 | 9 | Owner |
| D4.3 | Decision-rule critique | 4 | 9 | Owner / academic |
| D4.4 | Sensitivity & scenario analysis | 4 | 10 | Owner |
| D4.5 | Capital allocation recommendation memo | 4 | 10 | Owner |
| D4.6 | Standing investment appraisal template | 4 | 10 | Owner |
| D5.1 | Currency exposure quantification | 5 | 8 | Owner |
| D5.2 | Margin sensitivity to NZD/USD | 5 | 9 | Owner |
| D5.3 | Interest rate & input cost risk assessment | 5 | 10 | Owner |
| D5.4 | Hedging instrument evaluation | 5 | 11 | Owner |
| D5.5 | FX risk management policy recommendation | 5 | 11 | Owner |
| D6.1 | Risk register | 6 | 10 | Owner |
| D6.2 | Control environment assessment | 6 | 10 | Owner |
| D6.3 | Control & governance framework proposal | 6 | 11 | Owner |
| D6.4 | Business continuity / key-person note | 6 | 11 | Owner |
| D6.5 | AI cost control failure case study | 6 | 11 | Owner / academic |
| D7.1 | Capital structure & coverage trend | 7 | 9 | Owner |
| D7.2 | Peer benchmark | 7 | 10 | Owner |
| D7.3 | Funding options evaluation matrix | 7 | 11 | Owner |
| D7.4 | Capital structure theory application | 7 | 11 | Owner / academic |
| D7.5 | Funding strategy recommendation | 7 | 12 | Owner |
| **H1** | **Handover pack** — all models, documented, with a maintenance guide | all | 12 | Owner |
| **A1** | BUAD920 Introductory Report | — | 4 | AIS |
| **A2** | BUAD920 Management Report | — | 11 | AIS |
| **A3** | BUAD920 Reflective Journal | — | 12 | AIS |
| **A4** | BUAD920 Presentation | — | 12 | AIS + host |

---

## 8. Twelve-week work plan

Working pattern: **Thursday 08:00–17:00** (8 hrs + 1 hr break) · **Friday 08:00–17:00** (8 hrs +
1 hr break) · **Saturday 08:30–13:00** (4 hrs + 30 min break) = **20 hours per week**.

| Wk | Dates (Thu / Fri / Sat) | Focus | Milestone |
|---|---|---|---|
| 1 | 27 / 28 / 29 Aug | Induction, H&S, systems access, confidentiality agreement. Meet the team and observe Saturday classes. Begin the financial data map (WS1). | Induction complete; journal started |
| 2 | 3 / 4 / 5 Sep | Complete data map. Begin AR ageing (WS3). Gather material for the Introductory Report — structure, history, funding source, resource allocation. | **D1.1** · Introductory Report outline agreed with academic supervisor |
| 3 | 10 / 11 / 12 Sep | Build segmented P&L (WS1). Begin tuition contribution model (WS2). Micro/macro environment analysis for the Introductory Report. | Draft Introductory Report to academic supervisor for feedback |
| 4 | 17 / 18 / 19 Sep | Finish baseline financials and ratio pack. AR ageing complete. Start risk register (WS6). **Month-end close #1 observed.** | **D1.2, D3.1** · **A1 Introductory Report submitted** |
| 5 | 24 / 25 / 26 Sep | Management pack template and close checklist. Begin WACC work (WS4). Cost-to-serve data extraction (WS2). | **D1.3, D1.4** · Management Report topic confirmed |
| 6 | 1 / 2 / 3 Oct | Tuition break-even complete. Invoice completeness audit. Begin currency exposure build (WS5). | **D2.1, D3.2** · Mid-point review with host supervisor |
| 7 | 8 / 9 / 10 Oct | SaaS gross margin by tier. WACC paper. Reconciliation process review. | **D2.2, D3.3, D4.1** |
| 8 | 15 / 16 / 17 Oct | Subscription metrics, trial conversion, pricing memo. Credit policy. Currency exposure quantified. | **D2.3, D2.4, D2.5, D3.4, D5.1** |
| 9 | 22 / 23 / 24 Oct | Investment appraisals and decision-rule critique. 13-week cash forecast. FX sensitivity. Capital structure trend. | **D3.5, D3.6, D4.2, D4.3, D5.2, D7.1** |
| 10 | 29 / 30 / 31 Oct | Sensitivity/scenario work; capital allocation memo. Risk register and control assessment. Peer benchmark. **Month-end close #2 run by the intern.** | **D4.4, D4.5, D4.6, D5.3, D6.1, D6.2, D7.2** · Management Report draft to academic supervisor |
| 11 | 5 / 6 / 7 Nov | Hedging evaluation and FX policy. Control framework, continuity note, control-failure case study. Funding options. | **D5.4, D5.5, D6.3, D6.4, D6.5, D7.3, D7.4** · **A2 Management Report submitted** |
| 12 | 12 / 13 / 14 Nov | Funding strategy. Handover pack and model documentation. Final presentation to owner, team and academic supervisor. Exit interview and written reference. | **D7.5, H1** · **A3 Reflective Journal submitted** · **A4 Presentation delivered** |

**Public holidays.** No New Zealand public holiday falls on a Thursday, Friday or Saturday
within 27 August – 14 November 2026 (Labour Day, Monday 26 October 2026, falls outside the
working pattern). The full 240 hours are therefore available without substitution days. Any
hours lost to illness or an approved absence will be made up by agreement and recorded on the
timesheet, so that the 240-hour requirement is met and evidenced.

---

## 9. Hours reconciliation to the BUAD920 allocation

BUAD920 is a 30-credit course representing 300 hours of learning. This placement reconciles to
that allocation exactly:

| BUAD920 element | Course allocation | This placement |
|---|---|---|
| Time in the internship organisation | 240 hrs | **240 hrs** — 20 hrs/wk × 12 weeks (Thu 8 + Fri 8 + Sat 4) |
| Time with academic supervisor | 10 hrs | 10 hrs — initial meeting, two draft-feedback sessions, Wednesday drop-in attendance as needed, final presentation |
| Preparing written reports (outside the organisation) | 34 hrs | 34 hrs — Introductory Report (≈12), Management Report (≈22) |
| Reflective journal | 12 hrs | 12 hrs — 1 hr per week structured entry + 2 hrs consolidation |
| Preparation of presentation materials | 3 hrs | 3 hrs |
| Presentation | 1 hr | 1 hr |
| **Total** | **300 hrs** | **300 hrs** |

Report writing and journal writing sit **outside** the 240 host hours, per the course outline.
The host supervisor will not schedule work that encroaches on them.

---

## 10. Supervision, mentoring and feedback

### 10.1 Host supervision

| Field | Detail |
|---|---|
| Host supervisor | «Name» |
| Position | «Position» |
| Qualifications / experience | «e.g. CA / CPA / MBA; years in finance or business management» |
| Phone | «Phone» |
| Email | «Email» |
| Alternate contact (if supervisor unavailable) | «Name, position, contact» |

### 10.2 Contact and feedback rhythm

| Cadence | Activity |
|---|---|
| Daily | Short stand-up at the start of each working day (15 min) — priorities, blockers |
| Weekly | 45-minute one-to-one — deliverable review, written feedback, next week's priorities, journal check-in |
| Fortnightly | Working session with the owner on a live workstream output |
| Week 6 | **Formal mid-point review** — written assessment against the success criteria in §18, documented and shared with the academic supervisor |
| Week 12 | Exit interview, written performance reference, and handover sign-off |

Feedback will be **specific and written**, not verbal-only. The BUAD920 personal skills require
the intern to evidence how she responded to feedback; she cannot evidence what was never
recorded. The intern is expected to ask for feedback proactively — it is listed as the first
"do" in the AIS internship guidance and it is treated here as a performance expectation, not a
courtesy.

### 10.3 Academic supervision

The intern will maintain regular contact with her AIS academic supervisor by email and in
person, and is encouraged by the course outline to submit an **interim draft report** for
feedback. The host will:

- release her, without deduction from her hours, for academic supervision meetings and the
  Wednesday BUAD920 drop-in tutorial (16:30–17:30, room M213);
- make the host supervisor available to the academic supervisor on request, including for a
  site visit;
- review and clear any company-identifying material in her draft reports within **three working
  days** of receiving them, so that draft feedback deadlines are never missed because of the
  host (see §14.2).

### 10.4 Escalation and dispute resolution

1. **Step 1 — direct.** Raise the issue with the host supervisor at the daily stand-up or
   weekly one-to-one. Most issues are scope, priority or data-access issues and resolve here.
2. **Step 2 — owner.** If unresolved within five working days, escalate to «owner/director
   name», who will respond in writing within five working days.
3. **Step 3 — academic.** If still unresolved, or if the intern prefers not to raise it
   internally, she may contact her AIS Academic Supervisor or the BUAD920 Course Coordinator
   (Mr Martin Mahler, martinm@ais.ac.nz) directly. The AIS Student Career Centre is also
   available for support with placement duties.
4. **No detriment.** Escalating an issue, internally or to AIS, will not affect the intern's
   assessment, reference or treatment at the host. This is stated explicitly because an intern
   on a student visa is in an unequal bargaining position, and the host does not wish that
   inequality to suppress a legitimate concern.

The intern may also contact the AIS Student Career Centre or Student Support Services at any
time; the host will not require notice of or reasons for such contact.

---

## 11. How the placement feeds each BUAD920 assessment

### 11.1 Introductory Report (25%) — due week 4

*"Students familiarise themselves with their internship organisation and identify and evaluate
the operating environment (micro and macro)."* Assessed against KG A, B; PC 1, 3; PS iii.

The host will supply, in weeks 1–3, the material this report needs:

- **Organisation** — history and founding, legal structure, ownership, governance, organisation
  chart, the two-arm operating model, mission and goals, and how performance against them is
  currently judged.
- **Funding source and resource allocation** — how the business has been funded to date, how
  cash is allocated between teaching delivery, platform development and marketing, and who
  decides.
- **Micro environment** — customers (families, schools/institutes, individual students),
  competitors in Auckland tutoring and in ed-tech SaaS, suppliers (cloud, AI vendors, payment
  processor, venue lessors), substitutes (free online learning, in-school support, private
  one-to-one tutors), and barriers to entry — a Porter's Five Forces treatment applied honestly,
  including where the framework fits the SaaS arm badly and why.
- **Macro environment** — a PESTLE analysis grounded in New Zealand: education policy and
  curriculum change, the demand effect of national assessment reform, migration and Auckland
  demographic trends, household discretionary income and the interest rate environment, the
  Privacy Act 2020 and children's data, AI policy and school AI-use guidance, and the NZD/USD
  environment as it affects the cost base.

**Recommended structure:** organisation profile → operating model and revenue streams → funding
and resource allocation → micro environment → macro environment → synthesis: the three most
material environmental factors and their financial implications → conclusion.

The intern should be careful to *evaluate*, not merely describe. The distinction between a C
and an A on this assessment is almost always whether the environmental analysis ends in a
judgement about materiality.

### 11.2 Management Report (35%) — due week 11

*"Enabling the student to utilise their personal experiences and observations to display an
integrated analytical approach to a problem or development within the internship organisation."*
Assessed against KG A, C, D; PC 2, 3; PS i, iii, iv.

Three candidate topics, all fully supported by the workstreams above. The topic must be
confirmed with the academic supervisor by **week 5**.

| # | Candidate topic | Draws on | Assessment |
|---|---|---|---|
| **M1** *(recommended)* | **"Pricing and margin architecture for a dual-arm education business: what a class and a subscription actually earn, and what should change."** Establish fully-loaded unit economics for both arms, expose the tiers and classes that destroy value, quantify the FX-driven volatility in the SaaS cost base, and recommend a pricing and portfolio response with modelled impact. | WS1, WS2, WS5 | Strongest fit. It is a single integrated problem, it uses the intern's own observations from both arms, it is quantitative enough for Level 9, it has an unambiguous recommendation, and the FX component lifts it out of routine management accounting into FINA903 territory. |
| **M2** | **"Capital allocation under constraint: building an investment appraisal framework for an owner-operated SME."** Derive a defensible WACC for an unlisted company, appraise the four candidate investments, critique the competing decision rules, and recommend both a ranking and a standing process. | WS4, WS7 | Excellent for FINA802 depth and the most technically demanding. Slightly narrower on the "management" dimension and more dependent on forecast assumptions the intern must build herself. |
| **M3** | **"From intuition to control: designing a proportionate financial control framework for a growing SME."** Use the documented AI-cost control failure as the anchoring case, build the risk register, assess the control environment and recommend a framework sized to the business. | WS3, WS6 | Very strong on FINA903 LO6 and on critical reflection, with a compelling real incident at its centre. Least quantitative of the three, so the intern must work harder to evidence analytical depth. |

**Recommendation: M1**, with M2's WACC and M3's risk framing referenced as supporting analysis.
M1 gives the widest coverage of the assessment matrix while remaining a single, coherent
argument — which is what "an integrated analytical approach to a problem" means.

Whichever is chosen, the report must: state the problem and why it matters to the organisation;
set out method and data sources; present the analysis with workings visible; acknowledge
limitations and assumptions; and end in a specific, costed, actionable recommendation with an
implementation path. A Level 9 management report that stops at "the business should consider
reviewing its pricing" has failed regardless of how good the analysis behind it was.

### 11.3 Reflective Journal (20%) — due week 12

*"A structured report summarising the Internship experience, based upon your reflective journal
and research of the organisation."* Assessed against KG A, B, D; PC 1, 2, 4; PS i, ii, iii, iv.

The journal is the highest-risk assessment on any internship, because it cannot be
reconstructed at the end. It must be written weekly, contemporaneously, from week 1. The host
will protect **one hour per week outside host hours** for it and will remind the intern at each
weekly one-to-one that it is due.

- **Cadence:** one structured entry per working week (12 entries), ~1 hour each, plus 2 hours
  consolidating into the submitted report.
- **Structure per entry:** what I did → what I observed → what surprised me → what theory or
  course content applied (or failed to apply) → what I would do differently → what I still need
  to learn.
- **Prompts:** Appendix C provides a 12-week prompt bank drawn directly from the enquiry
  questions in the BUAD920 outline, so that by week 12 every one of those questions has been
  answered from experience.
- **Critical reflection, not diary.** The knowledge gain being assessed is "critically reflect
  on, and evaluate, the learning experience". Entries recording only what happened will not
  reach a passing standard. Each entry must contain at least one judgement about the intern's
  own performance or assumptions.

The most valuable journal material is usually the moment a classroom model does not survive
contact with the business — a theory that turned out not to apply, an assumption that proved
wrong, a recommendation the owner rejected and why. The outline asks for exactly that ("what
theories did you expect would be useful... but that have turned out not to be useful?"). The
host actively encourages her to record disagreements with management, including disagreements
with the host supervisor, and undertakes not to treat them as a performance matter.

### 11.4 Presentation (20%) — week 12

*"A short presentation based on your experience and report."* Assessed against KG A, C, D; PC 1,
4; PS v.

- **Audience:** the owner, the tutoring team, and the AIS academic supervisor (invited).
- **Format:** «15–20» minutes plus questions, in person at the host premises with a remote
  option for the academic supervisor.
- **Rehearsal:** a full dry run in week 11 with written feedback from the host supervisor, and a
  second rehearsal in week 12 if requested.
- **Content:** the organisation and her role → the problem she took on → method → findings →
  recommendation → what she learned and how she changed. The last section carries PC 4 and KG D
  and is routinely under-weighted by students; it should be at least a quarter of the talk.
- The host will provide a room, a display, and a genuine question-and-answer session — the
  owner will push back on the recommendations, which is better preparation for the assessed
  presentation than polite applause.

---

## 12. Learning outcome coverage matrix

### 12.1 BUAD920 — Performance Capabilities

| # | Performance capability | Where evidenced |
|---|---|---|
| 1 | Adapt to the demands of a quasi-employment role in the NZ business environment | Full 240 hours across a 12-week pattern including Saturday operating days; daily stand-ups; deadline-bound deliverables; direct client-facing observation in the tuition arm (WS1–WS7) |
| 2 | Create incisive summary reports distilled from effective records of activities | 37 defined deliverables, each a summary artefact distilled from underlying records; the monthly management pack (D1.3) is literally this capability as a business product; timesheet and journal as the record base |
| 3 | Develop practical perspectives linking principles, theories and academic content to workplace applications | Every workstream applies a named FINA802/FINA903 technique to live company data; Appendix E documents the required adaptations from listed-company to SME method |
| 4 | Reflect on, and critically evaluate, their own learning experiences, especially ongoing learning needs | Weekly journal with mandated self-judgement (§11.3); mid-point review (week 6); exit interview; presentation's closing section; WS6's requirement to critique a real control failure without hindsight bias |

### 12.2 BUAD920 — Knowledge Gains

| # | Knowledge gain | Where evidenced |
|---|---|---|
| A | Understand the professional NZ business environment | Introductory Report PESTLE and Five Forces; NZ tax, Privacy Act 2020, employment and consumer obligations in WS6; NZ funding landscape in WS7; NZ interest rate and FX environment in WS5 |
| B | Appreciate the value of record-keeping in order to formulate a summary report | WS1's data map and close checklist; WS3's reconciliation and completeness audits — a workstream whose entire subject is the consequence of poor records; the journal as a worked demonstration |
| C | Identify principles, theories, content and practices through linking programme content to practical experience | WS2 (TVM, contribution margin), WS4 (CAPM, WACC, NPV/IRR/PI/payback), WS5 (exposure types, hedging instruments, hedge accounting), WS7 (trade-off, pecking order) |
| D | Critically reflect on, and evaluate, the learning experience | Journal; mid-point review; D6.5 control-failure case study; limitations section required in every deliverable (§5, principle 5) |

### 12.3 BUAD920 — Personal Skills

| # | Personal skill | Where evidenced |
|---|---|---|
| i | Interpersonal skills — active listening, building trust, teamwork | Interviews with tutors and administrative staff for WS1–WS3; working sessions with the owner; observing Saturday classes and client handling; the trust required to be given access to real financial data |
| ii | Flexibility and adaptability in a corporate environment | Two very different operating arms; shifting priorities across a 12-week plan; month-end deadlines that override the plan; incomplete and imperfect source data |
| iii | Self-motivation, time management, integrity, critical thinking | 37 deliverables on a published schedule with no daily task allocation; principle 4 (assumptions are owned) and principle 5 (limitations declared) are integrity requirements; the decision-rule critique in WS4 is a pure critical-thinking artefact |
| iv | Strong work ethic — punctuality, respect, completion of projects | Timesheet-recorded attendance; the handover pack (H1) as the completion test — an unfinished model that nobody else can run is not a completed project |
| v | Communication and presentation skills | 37 written deliverables in business register; week 11 rehearsal; week 12 presentation with adversarial Q&A |

### 12.4 Carry-over from FINA802 and FINA903

| Course outcome | Workstream |
|---|---|
| F802 LO1 — critically evaluate alternative decision rules and their shortcomings | WS4 (payback, discounted payback, NPV, IRR, PI; where and why they disagree) |
| F802 LO2 — apply time value of money, valuation and instrument valuation | WS2 (discounted LTV, perpetuity with growth), WS4 (DCF, discounted payback) |
| F802 LO4 — explain and justify the relationship between risk and return | WS4 (CAPM, beta from comparables, size and illiquidity premia), WS5 (risk-adjusted margin) |
| F802 LO5 — compare sources of finance and relate to capital structure theory | WS7 (funding options matrix; trade-off and pecking order applied) |
| F903 PC1 — assess, monitor and manage financial risk with a practical approach | WS3, WS5, WS6 (register, controls, monitoring cadence) |
| F903 PC2 — evaluate funding, liquidity, interest rate, FX, commodity, credit and operational risk | WS3 (funding, liquidity, credit), WS5 (interest rate, FX, input cost), WS6 (operational) |
| F903 PC3 — recommend a strategy on the procurement and management of funds | WS7 (funding strategy), WS3 (liquidity buffer policy) |
| F903 PC4 — propose and justify financial instruments to manage risk | WS5 (forwards, options, collars, natural hedging, vendor commitments — with justification of the chosen instrument at this scale) |
| F903 PC5 — outline the practical elements of embedded derivatives and hedging derivatives | WS5 (hedge designation and effectiveness, hedge accounting trade-off, embedded derivatives in vendor and customer contracts) |
| F903 PC6 — identify responsibilities for financial risk, regulatory requirements and the control framework | WS6 (approval matrix, three lines, GST/PAYE/Privacy Act 2020, business continuity) |
| F903 KG a–f | WS1 (statements), WS1/WS2 (ratios and risk identification), WS5 (economics and FX), WS5 (financial products as risk tools), WS5 (markets and exposure types) |

---

## 13. Resources, access and tooling provided

| Provided | Detail |
|---|---|
| Workspace | Desk, chair and secure storage at «premises address» on Thursdays, Fridays and Saturdays |
| Equipment | «Laptop provided / bring-your-own with company account»; monitor; secure Wi-Fi |
| Accounts | Company email address; shared drive with a dedicated internship folder; calendar |
| Financial systems | Read access to the accounting system; read access to the payment processor dashboard (revenue, subscriptions, payouts, fees); read access to cloud and AI vendor billing consoles or exported statements |
| Platform reporting | Read access to the CWA Classroom administrative reporting layer — invoicing ledger and payments, expense reports by category and department, subscription and module records, attendance and session data, usage records |
| Data extracts | Where direct system access is not appropriate, the host will provide CSV or spreadsheet extracts within two working days of request |
| Analysis tooling | Spreadsheet software; access to market data sources for risk-free rates, comparable-company betas and FX rates; AIS library and database access retained by the intern |
| Mentoring | Weekly one-to-one with the host supervisor; fortnightly session with the owner; introduction to the business's external accountant «name» for one session on statutory reporting and tax |
| Reference material | Internal specifications for the invoicing, subscription, expense and AI-usage modules; prior-year financial statements; the vendor contracts relevant to WS5 |

**Access principle.** The intern receives read access to real financial data. She will not be
given payment-initiation rights, the ability to issue or cancel invoices in production, or
access to production customer records beyond what a workstream requires. This protects both the
business and the intern: an intern should never be the person who could have moved money.

---

## 14. Data governance, confidentiality and academic integrity

### 14.1 Confidentiality

- The intern will sign a confidentiality agreement in week 1 covering financial information,
  customer data, vendor terms, pricing strategy and source code.
- Student and family data held in the platform is personal information under the **Privacy Act
  2020**, and a substantial portion of it relates to children. The intern will work with
  **aggregated or de-identified** data wherever a workstream permits, and will access
  identifiable records only where genuinely necessary (for example, receivables ageing by
  account) and only within the systems themselves.
- No customer, student or family personal data will leave the host's systems, be copied to
  personal devices or storage, or appear in any academic submission — in any form, including as
  an illustrative example or a screenshot.

### 14.2 What may appear in AIS submissions

AIS assessment necessarily involves disclosing information about the host. The host agrees to
disclosure on these terms:

- **Permitted:** the business model, operating structure, market context, the analytical methods
  applied, the intern's own reasoning and conclusions, and her reflections.
- **Permitted with indexing:** commercially sensitive absolute figures (revenue, margin,
  customer counts, vendor rates) may be presented **indexed, banded or expressed as
  percentages** rather than in dollars, where the host requests it. Indexed presentation does
  not weaken the analysis and is standard practice in company-based academic work.
- **Requires clearance:** named customers or institutes, named vendors' negotiated rates,
  unpublished pricing plans, and source code.
- **Process:** the intern submits her draft to the host supervisor, who returns it **cleared or
  with specific redactions within three working days**. The host will not use this process to
  alter her analysis, conclusions or criticism of the business — only to protect third-party and
  commercially sensitive detail. If a redaction would materially damage the report, the host and
  intern will find an indexed or banded alternative rather than removing the analysis.
- Reports will be marked *"Commercial in confidence — submitted for AIS academic assessment"*.
- Submission through Moodle/Turnitin for originality checking is expressly permitted.

### 14.3 Academic integrity

The intern is responsible for AIS academic integrity requirements, and the host will not ask her
to compromise them:

- **APA (7th ed.)** referencing throughout, with a reference list.
- **AI declaration.** Any use of artificial intelligence tools — including for paraphrasing or
  proofreading — must be declared and cited per the AIS *Guide to Declaring and Citing AI Tools*.
  This applies equally to any AI tooling used in the course of the internship work itself, and
  the host will keep a record of AI tools made available to her so the declaration can be
  complete and accurate. The host's own platform uses AI vendors; where the intern uses those
  facilities as part of her analysis, that use is declarable too.
- **Draft similarity check.** One draft submission to Turnitin before final submission, as the
  outline permits.
- **Prerequisites.** The intern confirms she has attended the APA Referencing Skills and
  Academic Integrity workshops and passed the **Good Referencing Test (GRT)** — without which
  BUAD920 assessments cannot be submitted. This should be verified **before week 1**, not
  discovered in week 11.
- Work submitted for assessment must be the intern's own. Host staff may provide data,
  explanation and feedback; they will not draft her assessed work.

---

## 15. Professional conduct expectations

The AIS guidance *What not to do during your internship* is adopted as the conduct standard for
this placement, and the host commits to the reciprocal obligations.

**Expected of the intern**

| Expectation | What it means here |
|---|---|
| Ask for feedback | Bring specific questions to the weekly one-to-one; ask what would have made a deliverable better, not whether it was fine |
| Thank people who help you | Tutors and administrative staff will give up teaching-preparation time for her interviews |
| Pay attention even when not involved | Saturday teaching sessions, parent conversations and vendor discussions are where the operating reality is visible |
| Listen more than you talk | Particularly in the first fortnight, and particularly before proposing changes to processes she has seen once |
| Don't scoff at menial tasks | Some of the most valuable analysis in WS3 comes from personally working through a bank CSV reconciliation |
| Dress and behave to the setting | Smart casual; the tuition arm involves contact with children and parents, and presentation matters accordingly |
| Fit the culture, don't isolate | Small team, direct communication, no formal hierarchy — but that is not licence for informality with clients |
| Keep in touch afterwards | The host expects to remain a professional reference and welcomes continued contact |

**Expected of the host**

- Give her real work with real consequences, not filing.
- Provide the data, access and introductions listed in §13 within the promised timeframes.
- Give written, specific, timely feedback.
- Protect the report and journal hours that sit outside her 240 host hours.
- Take her recommendations seriously enough to argue with them.
- Provide a written reference at the end of the placement regardless of outcome.

**Child safety.** The tuition arm works with school-age students. The intern will complete the
host's child-safety briefing in week 1, will not be left in sole charge of students, and will
observe classes in the presence of a tutor. «Confirm whether a police vetting check is required
for the level of student contact involved and, if so, complete before week 1.»

**Health and safety.** Induction under the Health and Safety at Work Act 2015 in week 1: hazards,
emergency procedures, first aid, incident reporting, and the right to stop unsafe work.

---

## 16. Compliance and administration

| Item | Position |
|---|---|
| **Student visa / VOC** | The internship is a course requirement, but the intern must confirm her student visa conditions permit it and, if not, obtain a **Variation of Conditions** from Immigration New Zealand before week 1. The host will supply this proposal and the offer letter as supporting documentation on request. **This is a gating item — the placement cannot start without it.** |
| **Employment status** | «Confirm whether the placement is unpaid (course-required work experience), paid at or above the adult minimum wage, or paid a stipend.» If paid, a written employment agreement compliant with the Employment Relations Act 2000 is required in addition to this proposal, and PAYE, KiwiSaver and holiday pay obligations apply. If unpaid, the arrangement must genuinely be for the intern's benefit as a course requirement, and the host must not derive value in the manner of an employee substitute. **The host will take its own advice on this point before week 1 and record the outcome here.** |
| **Full-time student status** | Maintained throughout, per the BUAD920 outline. |
| **Attendance** | 100% attendance is an AIS and Immigration New Zealand requirement. Attendance is recorded on a weekly timesheet (Appendix B), signed by the host supervisor, and available to AIS on request. |
| **Timetable clashes** | «Confirm no remaining Saturday class commitments conflict with the Saturday 08:30–13:00 pattern.» |
| **Insurance** | The intern is covered by ACC. «Confirm the host's public liability and any professional indemnity cover extends to the intern.» |
| **Hours variation** | The 20 hrs × 12 weeks pattern requires BUAD920 Course Coordinator approval (see §4.3). |
| **Records retained** | Signed timesheets, weekly feedback notes, mid-point review, exit interview record, and this proposal. |

---

## 17. Risks to the internship and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Visa / VOC not in place before week 1 | Medium | High — placement cannot start | Confirmed as a gating item in week −2; host supplies documentation immediately on request |
| R2 | Source financial data is incomplete or inconsistent, so workstreams stall | High | Medium | WS1's data map is deliberately scheduled first, in week 1–2, precisely to surface this early; where data is missing the intern documents the gap as a finding rather than waiting — an unavailable figure is itself an audit result |
| R3 | Reflective journal left until the end | Medium | High — 20% of the grade, unrecoverable | Journal is a standing agenda item at every weekly one-to-one; host protects one hour per week; entries are dated and cannot be back-filled credibly |
| R4 | Commercial sensitivity blocks material needed for the Management Report | Medium | High | §14.2 clearance process with a three-working-day turnaround and an indexed-presentation fallback agreed in advance |
| R5 | Scope is too large for 240 hours | Medium | Medium | Workstreams are prioritised WS1 → WS3 → WS2 → WS4 → WS5 → WS6 → WS7; WS7 is explicitly the flex item and may be reduced to a scoping paper without damaging assessment coverage, since PC/KG coverage is already complete without it |
| R6 | Host supervisor unavailable (illness, travel) | Medium | Medium | Named alternate contact in §10.1; weekly one-to-one may be held remotely; owner is a standing escalation point |
| R7 | Key-person dependency — most institutional knowledge sits with the owner | High | Medium | Front-load interviews in weeks 1–3; record answers in writing at the time; this risk is itself a finding for WS6 |
| R8 | Month-end close falls outside working days, so the intern never observes one | Low | Medium | 12-week span covers three month-ends; if a close falls on a non-working day, the intern attends by agreement and takes the time in lieu |
| R9 | Intern's recommendations are not acted on, weakening the reflective material | Medium | Low | The owner commits to a written response — accept, reject or defer with reasons — to each recommendation memo; a reasoned rejection is *better* journal material than silent acceptance |
| R10 | Illness or absence reduces hours below 240 | Medium | High — course requirement | Make-up hours agreed and timesheet-recorded; the 12-week span carries slack that an 8-week pattern would not |

---

## 18. Success criteria

The mid-point (week 6) and exit (week 12) reviews assess against these criteria. They are stated
now so that the intern knows the standard from day one.

**Meets expectations**

- 240 hours completed and evidenced; punctual and reliable.
- All scheduled deliverables produced to a usable standard, with workings and sources shown.
- Analysis is technically correct and the conclusions follow from it.
- Journal maintained weekly from week 1.
- Assessments submitted on time.

**Exceeds expectations — the distinction standard**

- Recommendations are specific, costed and implementable, with an implementation path — not
  "the business should consider".
- The intern found at least one material issue **nobody asked her to look for**. In a business
  with the data gaps described in §3.4, this should be achievable; it is the single strongest
  signal of Level 9 capability.
- Models are documented well enough that the business runs them after she leaves — the handover
  pack (H1) is used, not filed.
- Limitations and assumptions are stated honestly and unprompted, including where her own
  analysis is weak.
- She has argued a position with the owner, been challenged on it, and either defended it with
  evidence or changed it for stated reasons.
- The reflective journal shows genuine change in her thinking across the twelve weeks, not a
  retrospective narrative of competence.

**The host's undertaking.** If the intern meets the "meets expectations" standard, the host will
provide a written reference addressing performance, reliability and specific competencies, and
will act as a referee for future applications.

---

## 19. Approvals

| Role | Name | Signature | Date |
|---|---|---|---|
| Host supervisor, Wizards Learning Hub | «Name, position» | | |
| Owner / authorised officer, Wizards Learning Hub | «Name, position» | | |
| Intern | Shanika Kirillawala (20250356) | | |
| AIS Academic Supervisor | | | |
| BUAD920 Course Coordinator | Mr Martin Mahler | | |

---

## Appendix A — Placement calendar

| Week | Thursday (8 hrs) | Friday (8 hrs) | Saturday (4 hrs) | Cumulative hrs |
|---|---|---|---|---|
| 1 | 27 Aug 2026 | 28 Aug 2026 | 29 Aug 2026 | 20 |
| 2 | 3 Sep 2026 | 4 Sep 2026 | 5 Sep 2026 | 40 |
| 3 | 10 Sep 2026 | 11 Sep 2026 | 12 Sep 2026 | 60 |
| 4 | 17 Sep 2026 | 18 Sep 2026 | 19 Sep 2026 | 80 |
| 5 | 24 Sep 2026 | 25 Sep 2026 | 26 Sep 2026 | 100 |
| 6 | 1 Oct 2026 | 2 Oct 2026 | 3 Oct 2026 | 120 |
| 7 | 8 Oct 2026 | 9 Oct 2026 | 10 Oct 2026 | 140 |
| 8 | 15 Oct 2026 | 16 Oct 2026 | 17 Oct 2026 | 160 |
| 9 | 22 Oct 2026 | 23 Oct 2026 | 24 Oct 2026 | 180 |
| 10 | 29 Oct 2026 | 30 Oct 2026 | 31 Oct 2026 | 200 |
| 11 | 5 Nov 2026 | 6 Nov 2026 | 7 Nov 2026 | 220 |
| 12 | 12 Nov 2026 | 13 Nov 2026 | 14 Nov 2026 | **240** |

Daily hours: Thursday and Friday 08:00–17:00 (8 working hours plus a 1-hour unpaid break);
Saturday 08:30–13:00 (4 working hours plus a 30-minute break).

---

## Appendix B — Weekly timesheet and record template

| Field | Entry |
|---|---|
| Week number / dates | |
| Thursday — in / out / hours | |
| Friday — in / out / hours | |
| Saturday — in / out / hours | |
| Total hours this week | |
| Cumulative hours | |
| Workstreams progressed | |
| Deliverables completed | |
| Deliverables in progress | |
| Blockers / data requests outstanding | |
| Feedback received (written summary) | |
| Priorities for next week | |
| Intern signature | |
| Host supervisor signature | |

The BUAD920 knowledge gain B is "appreciate the value of record-keeping in order to formulate a
summary report", and performance capability 2 is creating summary reports "distilled from
effective records of activities". This timesheet is the record those outcomes are assessed
against — it is not administrative overhead, it is assessed evidence.

---

## Appendix C — Reflective journal prompt bank

One entry per week. Each entry answers the standing questions plus that week's prompt.

**Standing questions (every entry):** What did I do? What did I observe? What surprised me? What
course content applied — or failed to apply? What would I do differently? What do I still need
to learn?

| Week | Prompt (drawn from the BUAD920 enquiry questions) |
|---|---|
| 1 | What is the structure of this organisation, and how does the structure differ from what I expected of a business this size? |
| 2 | What is the organisation's funding source, and how does it allocate resources between its two arms? Who actually decides? |
| 3 | What is the organisation's history, and what does its future look like? Whose view of the future am I hearing, and is it evidenced? |
| 4 | What knowledge and skills from my programme am I actually using? Which have turned out to be less useful here than I expected, and why? |
| 5 | What are the dynamics among staff, and between staff and clients? What have I learned about this business by watching a Saturday class rather than reading its data? |
| 6 | *(Mid-point.)* What are the organisation's goals? Are they being met? Why or why not? And separately: what has the mid-point review told me about my own performance that I did not already believe? |
| 7 | What is effective in this organisation's system of operation? What is ineffective? Who is most effective, and what specifically makes them so? |
| 8 | I have now recommended a price change. How was it received? What did the pushback reveal about factors my analysis did not capture? |
| 9 | What would I change in this organisation? Why, and — concretely — how? What would it cost, and what would stop it working? |
| 10 | What new knowledge and skills have I gained that I could not have gained in a classroom? Where am I still weak? |
| 11 | How has this internship met my expectations, and how has it not? What was the most challenging aspect, and what did I do about it? |
| 12 | In what ways have I changed since week 1? What are my strengths and weaknesses as I now understand them, and what are my ongoing learning needs? |

---

## Appendix D — Corrections required to the draft offer letter

The draft offer of internship letter should be corrected before it is issued to AIS. The
following items are inconsistent, incomplete or would raise questions at the coordinator's end.

| # | Item in the draft | Issue | Correction |
|---|---|---|---|
| 1 | "End Date: ex. Friday, 28th May 2025" | A placeholder example was left in, and the date precedes the start date by over a year | **Saturday 14 November 2026** — 12 weeks from the first working day |
| 2 | "Start Date: Monday 24th August 2026" | 24 August 2026 is a Monday, but the working pattern is Thursday–Saturday, so no work occurs that day | **Thursday 27 August 2026**, or retain 24 August as the engagement start and state the first working day is Thursday 27 August |
| 3 | "Duration: 12 weeks (240 hours)" vs "Working Hours: 20 hours per week" | Internally consistent (12 × 20 = 240) and consistent with BUAD920's 240 hours — but it departs from the outline's "normally 30 hours per week for eight weeks" | Retain, and add one sentence stating that the same 240 hours are delivered over a longer window, with coordinator approval sought (see §4.3) |
| 4 | "Supervisor Name / Supervisor Position / Phone: xxxx / Email: xxxx@mail.com" | Placeholders | Complete with real details and a professional company email domain, not a generic mail address |
| 5 | "Wizards Learning Hub (NZBN942xxxxxx)" | Masked NZBN | Complete NZBN and, if different, the registered legal entity name |
| 6 | "Company Letterhead (if applicable)" | Left in the document | Remove and issue on actual letterhead |
| 7 | "support his professional growth" | Incorrect pronoun for the named intern | "**her** professional growth" |
| 8 | "Student Name & Job Title: Shanika Kirillawala, Intern Position" | "Intern Position" is not a job title | "**Finance and Business Analysis Intern**" |
| 9 | "Job Responsibilities (Please include approved JD once approved)" | Instruction to the drafter left in the document | Remove the parenthetical and attach the finalised responsibilities |
| 10 | The last two responsibilities — business promotion activities, and administrative support for holiday programmes (client handling, organising activities, preparing study materials) | These are marketing and operations duties, not finance duties. Retaining them unaltered invites the coordinator to question whether the placement "aligns with the specialisation", which is the outline's suitability test | Either remove, or reframe so the finance purpose is explicit — e.g. "**evaluate the return on investment of business promotion activity and the contribution margin of holiday programmes, including on-site observation of programme delivery**". The second form keeps the useful exposure and makes it assessable |
| 11 | Responsibilities list generally | Sound, but generic — it would fit any finance internship anywhere | Replace with, or append, the seven workstreams in §6 of this proposal, which name specific deliverables and are demonstrably aligned to FINA802 and FINA903 |
| 12 | Duplicated "Best regards, Signature of authorized officer" block | Formatting artefact appearing twice | Remove the duplicate |
| 13 | No mention of supervision arrangements, or of the intern's release for academic supervision | The outline makes ongoing supervisor consultation a requirement | Add one line referring to the supervision model in §10 of this proposal |
| 14 | No statement on payment status | The coordinator and Immigration New Zealand will both want to know | State clearly whether the placement is unpaid course-required work experience or paid, per §16 |

**Recommended approach:** issue a **short, clean offer letter** (parties, role title, dates,
hours, pattern, supervisor, payment status, supervision commitment) and attach **this proposal**
as the schedule of work. That structure reads far better to an academic coordinator than a
single letter carrying a long bulleted duty list, and it makes the learning-outcome alignment
explicit rather than something the coordinator has to infer.

---

## Appendix E — Technique transfer: listed-company methods in a private SME

The intern's assessed finance work used listed New Zealand companies. This placement uses an
unlisted SME. The adaptations below are not workarounds — they are the substance of the Level 9
learning, and each should be argued explicitly in her reports.

| Technique as assessed | Why it does not transfer directly | The adaptation required here |
|---|---|---|
| **Beta from 5 years of monthly share prices** | No observable share price | Select listed comparables in education services and ed-tech SaaS; take their equity betas; **unlever** each using its own debt/equity and tax rate; take a median asset beta; **re-lever** to the company's target structure. Justify the comparable set and show the sensitivity of WACC to the choice |
| **CAPM cost of equity** | The market premium alone understates the required return for a small, illiquid, undiversified, owner-concentrated business | Build up: risk-free (NZ government bond, tenor matched to the forecast horizon) + re-levered beta × equity risk premium + **size premium** + **illiquidity/marketability premium**, each sourced and justified. Deliver a range, not a point |
| **Single- and multi-stage DDM** | The company pays no dividends and has no dividend history | Use **free cash flow to firm** discounted at WACC, or free cash flow to equity at cost of equity, with a two-stage structure (explicit forecast then terminal growth). The multi-stage *mechanics* are identical; only the cash flow definition changes |
| **Portfolio risk, correlation, diversification** | The owner holds one undiversified asset — this business | Reframe as **concentration risk**: the owner's human and financial capital are perfectly correlated with the same enterprise. Apply the same statistical reasoning to the *customer* portfolio instead — revenue concentration by institute, correlation of demand across the two arms, and whether the tuition and SaaS arms are genuinely diversifying or share a common demand driver |
| **Bond pricing under a rate shock** | The company has issued no bonds | Apply the same discounting to the company's **actual debt and lease obligations**: reprice fixed obligations under an OCR shock and quantify the effect on interest coverage. Where the company is debt-free, price the debt it *would* issue under the WS7 funding options |
| **Debt/equity and interest coverage vs a listed peer** | Private peers do not publish; listed peers are far larger | Use listed peers with the size difference stated as an explicit limitation; supplement with published NZ SME sector benchmarks; and be honest that the comparison is indicative, not conclusive |
| **Trade-off and pecking order theory** | Both were developed with reference to large, widely-held firms | Test them against an owner-operated firm: the tax shield is worth less where taxable profit is small and volatile; distress costs are higher where assets are intangible and unsecurable; and pecking order is *strengthened*, not weakened, by owner control preferences and information asymmetry. Say which theory better explains this firm's actual behaviour, with evidence |
| **NPV / IRR / PI / payback** | Transfers directly — but the cash flows do not exist and must be built | The analytical work moves from *computing* the metrics to *constructing and defending the forecast*. State the drivers, the evidence for each, and the sensitivity of the decision to each. This is where the marks are |
| **FX transaction, translation, economic exposure** | Transfers directly, and the exposure is real | Quantify from actual USD vendor charges. The genuinely SME-specific judgement is **instrument selection**: a bank will price a small forward book unattractively and may require a credit line, so a vendor prepayment or committed-use discount may dominate a forward on both cost and simplicity. Recommending a forward because it is the textbook answer, without testing that, would be the wrong answer |

---

## Appendix F — Systems and data sources

| Source | Holds | Currency | Used by |
|---|---|---|---|
| Accounting system | Statutory financials, general ledger, payroll, GST | NZD | WS1, WS7 |
| Payment processor | Subscription revenue actually collected, refunds, discounts, processing fees, payouts | NZD / USD | WS1, WS2, WS3, WS5 |
| Platform — invoicing ledger | Student invoices, line items by class, payments, credit transactions, payer-name mappings | NZD | WS1, WS3 |
| Platform — expense records | Operating expenses by category and department, recurring expense materialisation | NZD | WS1, WS2 |
| Platform — vendor charge sync | Cloud infrastructure and AI vendor charges fetched from source billing APIs | USD | WS1, WS2, WS5, WS6 |
| Platform — subscription records | Plans, tiers, module add-ons, discounts, promo codes, trial and subscription status | NZD | WS2 |
| Platform — attendance and sessions | Sessions held, attendance by student, the basis for attendance-billed fees | — | WS2, WS3 |
| Platform — usage records | AI page consumption against module quotas | — | WS2, WS5 |
| Bank | Statements, CSV exports for reconciliation, facility terms | NZD / USD | WS3, WS5, WS7 |
| Vendor contracts | Cloud, AI and processing terms, committed-use and prepayment options | USD | WS5 |
| External market data | Risk-free rates, comparable betas, FX rates, sector benchmarks | — | WS4, WS5, WS7 |

---

*Prepared by Wizards Learning Hub for submission to the Auckland Institute of Studies in support
of Shanika Kirillawala's BUAD920 Internship placement.*
