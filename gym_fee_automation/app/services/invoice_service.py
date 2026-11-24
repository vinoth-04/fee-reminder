"""PDF invoice / receipt for a paid membership payment. Generated on demand, nothing stored."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import config, db
from app.errors import AppError
from app.services.due_date_service import parse_date, split_month
from app.services.validators import format_inr

ACCENT = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
LOGO_PATH = config.BASE_DIR / "static" / "images" / "logo.jpg"

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def invoice_number(payment_id: str) -> str:
    """P000012 -> INV-000012. Same payment always gives the same number."""
    return "INV-" + payment_id.lstrip("P").zfill(6)


def _month_label(ym: str) -> str:
    y, m = split_month(ym)
    return f"{_MONTHS[m - 1]} {y}"


def _date_label(value: str) -> str:
    d = parse_date(value)
    return d.strftime("%d %b %Y") if d else "-"


def _load(payment_id: str) -> dict:
    with db.read() as conn:
        rows = db.rows(conn, """
            SELECT p.payment_id, p.member_id, p.payment_month, p.amount, p.payment_date,
                   p.payment_status, p.payment_mode,
                   COALESCE(m.name, '') AS member_name, COALESCE(m.phone, '') AS phone
            FROM payments p LEFT JOIN members m ON m.member_id = p.member_id
            WHERE p.payment_id = ?""", (payment_id,))
    if not rows:
        raise AppError(404, f"Payment {payment_id} not found.")
    if rows[0]["payment_status"] != "Paid":
        raise AppError(409, "An invoice can only be generated for a paid payment.")
    return rows[0]


def build_invoice_pdf(payment_id: str) -> tuple[bytes, str]:
    """Returns (pdf_bytes, suggested_filename)."""
    p = _load(payment_id)
    gym = config.load_settings().get("gym_name", "").strip() or "Gym Membership"
    number = invoice_number(p["payment_id"])

    h_title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=20, textColor=ACCENT, leading=24)
    h_gym = ParagraphStyle("g", fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT, leading=16)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=MUTED, leading=12)
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=10, textColor=ACCENT, leading=14)
    bold = ParagraphStyle("bb", parent=body, fontName="Helvetica-Bold")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"{number} - {p['member_name']}", author=gym)
    story = []

    # Header: gym name (+ logo) on the left, invoice title on the right
    left = [Paragraph(gym, h_gym)]
    if LOGO_PATH.exists():
        try:
            left.insert(0, Image(str(LOGO_PATH), width=22 * mm, height=22 * mm, kind="proportional"))
            left.insert(1, Spacer(1, 3 * mm))
        except Exception:
            pass
    right = [Paragraph("PAYMENT RECEIPT", h_title), Spacer(1, 2 * mm),
             Paragraph(f"Invoice no: <b>{number}</b>", body),
             Paragraph(f"Date: {_date_label(p['payment_date'])}", body)]
    header = Table([[left, right]], colWidths=[85 * mm, 85 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    # right column paragraphs need right alignment
    for para in right:
        if isinstance(para, Paragraph):
            para.style = ParagraphStyle("r", parent=para.style, alignment=2)
    story += [header, Spacer(1, 10 * mm)]

    # Billed to
    story += [Paragraph("BILLED TO", small),
              Paragraph(p["member_name"] or "-", bold),
              Paragraph(f"Member ID: {p['member_id']}", body),
              Paragraph(f"Phone: {p['phone'] or '-'}", body),
              Spacer(1, 8 * mm)]

    # Line items
    amount = format_inr(p["amount"]).replace("₹", "Rs. ")
    rows = [["Description", "Period", "Amount"],
            ["Monthly gym membership fee", _month_label(p["payment_month"]), amount]]
    items = Table(rows, colWidths=[85 * mm, 45 * mm, 40 * mm])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), ACCENT),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [items, Spacer(1, 4 * mm)]

    # Totals
    totals = Table([["Total paid", amount],
                    ["Payment mode", p["payment_mode"] or "-"],
                    ["Payment date", _date_label(p["payment_date"])],
                    ["Status", "PAID"]], colWidths=[130 * mm, 40 * mm])
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("TEXTCOLOR", (0, 0), (-1, -1), ACCENT),
        ("TEXTCOLOR", (1, 3), (1, 3), colors.HexColor("#15803d")),
        ("FONTNAME", (1, 3), (1, 3), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [totals, Spacer(1, 18 * mm),
              Paragraph("This is a computer-generated receipt and does not need a signature.", small),
              Paragraph(f"Thank you for being a member of {gym}.", small)]

    doc.build(story)
    safe = "".join(c if c.isalnum() else "_" for c in (p["member_name"] or "member"))[:30]
    return buf.getvalue(), f"{number}_{safe}.pdf"
