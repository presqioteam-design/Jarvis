"""
What Jarvis knows about Presqio. Emails and AI replies use only these facts.
Update this file when the product or pricing changes.
"""

NAME = "Presqio"
PHONE = "+91 63093 87321"
WEBSITE = "https://presqio.pages.dev"
SIGNUP_URL = "https://presqio.pages.dev/register"
TRIAL = "14-day free trial of the Growth plan, no card needed"

# Given to the AI when it answers a business's questions. Plain facts only.
_FACTS = """
Presqio is phone-based staff attendance, rosters, leave and payroll for businesses with one or more branches:
shops and showrooms, restaurants and hotels, clinics and hospitals, factories and warehouses, construction and
project sites, security and facility services, schools and colleges, salons, spas and gyms, field sales and service
teams, and offices.

Attendance
- Employees open Presqio in their phone's browser (nothing to install) and sign in with their employee ID.
- Every check-in and check-out takes a fresh selfie plus a GPS reading. It is rejected if the employee is outside the branch's set radius or the GPS reading is too inaccurate.
- Time is recorded on the server, so changing the phone clock doesn't help.
- Location is read only at check-in and check-out, never tracked during the day.
- Attendance register: date-wise grid of in/out times with selfies, hours worked, multiple sessions per day, rest days and leave. Exports to CSV.
- Missed punches are fixed through a correction request with a reason; an admin approves it and every change is kept in an audit trail.
- Kiosk: one shared tablet or phone at the entrance; staff type their employee ID and take a selfie. For staff without smartphones.
- Several sites: someone who works at more than one branch or site can check in at any of theirs. Field staff can be allowed to check in from anywhere (the selfie and location are still recorded, and the day is marked off-site).
- Leave: employees take leave themselves from their phone (it's recorded at once and the admin sees it). Leave types (casual, sick, earned, unpaid...) with yearly allowances and balances. Holidays never count as absences.
- Shifts: day, night and overnight, with grace time and set working days.
- Roster: plan who works which shift each day, split shifts (e.g. lunch and dinner), days off, and rotations (weekly morning/evening/night, 4 on 2 off) filled for weeks at once. Employees see their coming shifts.
- Languages: the employee app and the kiosk work in English, Hindi and Telugu.

Payroll
- Salary structure per employee (earnings and deductions), monthly payroll runs, loss-of-pay days suggested from attendance, payslips with PAN, UAN, ESI and bank details.
- Pay can be a monthly salary, a daily wage (per day worked) or an hourly wage, with overtime worked out from check-in times and paid at 1x, 1.5x or 2x after review.

Multiple branches
- One organization (e.g. "XYZ Group of Hotels") holds every hotel as a branch, each with its own check-in radius, shifts and staff. Owners manage all of them from one login.
- Team: owners invite admins (everything), branch managers (only their branches: employees, attendance, approvals, roster; no payroll) and viewers (read-only) by email.
- At sign-up the owner picks the kind of business, and Presqio suggests shifts and leave types that fit.

Why hotels use it
- Night and overnight shifts are supported.
- Selfie + GPS stops one employee marking attendance for another and stops check-ins from home.
- Hotel groups see every property on one dashboard.
- Housekeeping, kitchen and front-desk staff use the phone they already have; no biometric machine to buy.
- Attendance feeds straight into payroll, so no copying from paper registers at month end.

Pricing
- Prices are not published yet. If asked about price, say: "Please call us on {PHONE} for pricing." Never quote a number.
- Every account starts with a {TRIAL}.

Links and contact
- Website: {WEBSITE}
- Start the free trial: {SIGNUP_URL}
- Pages for each kind of business: {WEBSITE}/for/shops, /for/restaurants, /for/clinics, /for/factories, /for/construction, /for/security-services, /for/schools, /for/salons-and-gyms, /for/field-teams, /for/offices
- Phone / WhatsApp: {PHONE}
- There is no separate demo page: a "demo" is the free trial or a call with the Presqio team.

Presqio does NOT have these. Never claim them:
- Face recognition (selfies are kept as evidence for a person to check; faces are not matched automatically)
- Biometric device integration
- Google Sheets sync
- Automatic PF/ESI/TDS calculation (deductions are lines the admin sets up)
- A Play Store or App Store app (employees use the phone browser)
""".strip()



def facts() -> str:
    """The product facts with the phone and website from Settings."""
    from . import prefs
    e = prefs.emails()
    return _FACTS.format(PHONE=e["phone"], WEBSITE=e["website"], SIGNUP_URL=SIGNUP_URL, TRIAL=TRIAL)


FACTS = _FACTS.format(PHONE=PHONE, WEBSITE=WEBSITE, SIGNUP_URL=SIGNUP_URL, TRIAL=TRIAL)   # defaults, for tests
