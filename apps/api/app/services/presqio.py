"""
What Jarvis knows about Presqio. Emails and AI replies use only these facts.
Update this file when the product or pricing changes.
"""

NAME = "Presqio"
PHONE = "+91 63093 87321"
WEBSITE = "https://presqio.pages.dev"
SIGNUP_URL = "https://presqio.pages.dev/register"
TRIAL = "14-day free trial of the Growth plan, no card needed"

# Given to the AI when it answers a hotel's questions. Plain facts only.
FACTS = f"""
Presqio is phone-based staff attendance and payroll for businesses with one or more branches, such as hotels.

Attendance
- Employees open Presqio in their phone's browser (nothing to install) and sign in with their employee ID.
- Every check-in and check-out takes a fresh selfie plus a GPS reading. It is rejected if the employee is outside the branch's set radius or the GPS reading is too inaccurate.
- Time is recorded on the server, so changing the phone clock doesn't help.
- Location is read only at check-in and check-out, never tracked during the day.
- Attendance register: date-wise grid of in/out times with selfies, hours worked, multiple sessions per day, rest days and leave. Exports to CSV.
- Missed punches are fixed through a correction request with a reason; an admin approves it and every change is kept in an audit trail.
- Leave: employees apply from their phone; admins approve.
- Shifts: day, night and overnight, with grace time and set working days.

Payroll
- Salary structure per employee (earnings and deductions), monthly payroll runs, loss-of-pay days suggested from attendance, payslips with PAN, UAN, ESI and bank details.

Multiple branches
- One organization (e.g. "XYZ Group of Hotels") holds every hotel as a branch, each with its own check-in radius, shifts and staff. Owners manage all of them from one login.

Why hotels use it
- Night and overnight shifts are supported.
- Selfie + GPS stops one employee marking attendance for another and stops check-ins from home.
- Hotel groups see every property on one dashboard.
- Housekeeping, kitchen and front-desk staff use the phone they already have; no biometric machine to buy.
- Attendance feeds straight into payroll, so no copying from paper registers at month end.

Pricing (per month, excluding taxes)
- Free: ₹0, 1 branch, up to 10 employees
- Starter: ₹999, up to 3 branches, up to 50 employees
- Growth: ₹2,999, up to 10 branches, up to 250 employees
- Every account starts with a {TRIAL}.

Links and contact
- Website: {WEBSITE}
- Start the free trial: {SIGNUP_URL}
- Phone / WhatsApp: {PHONE}
- There is no separate demo page: a "demo" is the free trial or a call with the Presqio team.

Presqio does NOT have these. Never claim them:
- Face recognition (selfies are kept as evidence for a person to check; faces are not matched automatically)
- Biometric device integration
- Google Sheets sync
- Automatic PF/ESI/TDS calculation (deductions are lines the admin sets up)
- A Play Store or App Store app (employees use the phone browser)
""".strip()
