"""
Outreach emails. Fixed wording (not AI-written) so every email is accurate
and on-message; only the hotel name, area and sender are filled in.
Plain text, one link, an opt-out line: this keeps Gmail from flagging them.
"""

from dataclasses import dataclass

from .presqio import PHONE, SIGNUP_URL, WEBSITE


@dataclass
class Email:
    subject: str
    body: str


SIGNATURE = """Regards,
{sender}
{phone} (call or WhatsApp)
{website}"""

OPT_OUT = 'If you\'d rather not hear from us, reply "stop" and we won\'t email you again.'

FIRST = """Hello {hotel} team,

We're writing from Presqio, a staff attendance and payroll tool that suits hotels like yours in {area}.

Your staff check in from the phone they already carry. Each check-in takes a selfie and a GPS reading at your hotel, so nobody can mark attendance for a colleague or check in from home. It works for night and overnight shifts, and the attendance flows straight into monthly payroll and payslips. There's no machine to buy and no app to install.

If you run more than one property, you can see all of them on one dashboard.

You can try it free for 14 days, no card needed:
{signup}

Or just reply to this email, or call us on {phone}, and we'll help you set it up.

{signature}

{opt_out}"""

FOLLOW_UP_1 = """Hello again,

A quick follow-up on staff attendance at {hotel}.

If month-end payroll means copying hours from a register, Presqio does that part for you. Attendance from the selfie check-ins goes straight into payroll, with loss-of-pay days suggested automatically and payslips that include PAN, UAN, ESI and bank details.

The 14-day free trial is here: {signup}
Or we're happy to walk you through it on a 10-minute call: {phone}

{signature}

{opt_out}"""

FOLLOW_UP_2 = """Hello,

This is our last note about Presqio for {hotel}.

If staff attendance isn't a priority right now, no problem, and we won't follow up again. If it is, you can start the free trial any time at {signup}, or call us on {phone}.

Thank you for your time.

{signature}"""

SEQUENCE = [FIRST, FOLLOW_UP_1, FOLLOW_UP_2]


def render(step: int, hotel: str, area: str, sender: str = "Presqio Team") -> Email:
    """step 0 = first email; 1 and 2 are follow-ups sent as replies in the same thread."""
    fields = {"hotel": hotel.strip(), "area": area.strip() or "your area", "signup": SIGNUP_URL, "phone": PHONE}
    sender = sender if "presqio" in sender.lower() else f"{sender}\nPresqio"
    signature = SIGNATURE.format(sender=sender, phone=PHONE, website=WEBSITE)
    body = SEQUENCE[step].format(**fields, signature=signature, opt_out=OPT_OUT)
    subject = f"Staff attendance for {fields['hotel']}"
    return Email(subject=subject if step == 0 else f"Re: {subject}", body=body)


def area_from(address: str, campaign_label: str = "") -> str:
    """'Madhapur, Hyderabad, Telangana' -> 'Madhapur'."""
    source = campaign_label or address
    return source.split(",")[0].strip()
