from io import BytesIO
from reportlab.lib.pagesizes import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

def generate_receipt_pdf(sale):
    buffer = BytesIO()
    # Thermal receipt size (approx 80mm width, dynamic height)
    # We use a standard page size or a custom one. Let's use 80mm width.
    page_width = 80 * mm
    doc = SimpleDocTemplate(buffer, pagesize=(page_width, 200 * mm),
                            rightMargin=5*mm, leftMargin=5*mm,
                            topMargin=5*mm, bottomMargin=5*mm)

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=2
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        spaceAfter=10,
        textColor=colors.grey
    )
    
    normal_style = ParagraphStyle(
        'NormalSmall',
        parent=styles['Normal'],
        fontSize=8,
        spaceAfter=5
    )
    
    bold_style = ParagraphStyle(
        'BoldSmall',
        parent=styles['Normal'],
        fontSize=8,
        fontName='Helvetica-Bold',
        spaceAfter=5
    )
    
    right_style = ParagraphStyle(
        'RightSmall',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_RIGHT
    )

    elements = []

    # Header
    elements.append(Paragraph("BOUTIQUE POS", title_style))
    elements.append(Paragraph("Elegant Retail Solutions", subtitle_style))
    elements.append(Paragraph(f"<b>Receipt #:</b> {sale.order_number}", normal_style))
    elements.append(Paragraph(f"<b>Date:</b> {sale.created_at.strftime('%Y-%m-%d %H:%M')}", normal_style))
    elements.append(Paragraph(f"<b>Cashier:</b> {sale.cashier.name if sale.cashier else 'N/A'}", normal_style))
    
    if sale.customer:
        elements.append(Paragraph(f"<b>Customer:</b> {sale.customer.name}", normal_style))
    
    elements.append(Spacer(1, 5))

    # Items Table
    data = [['Item', 'Qty', 'Price', 'Total']]
    for item in sale.items:
        # Truncate long names
        name = item.product_name[:20] + '..' if len(item.product_name) > 22 else item.product_name
        # Add size/color info if exists
        variant_info = ""
        if item.size or item.color:
            variant_info = f" ({item.size}/{item.color})"
        
        data.append([
            Paragraph(f"{name}{variant_info}", normal_style),
            str(item.quantity),
            f"{item.unit_price:,.0f}",
            f"{item.line_total:,.0f}"
        ])

    table = Table(data, colWidths=[30*mm, 8*mm, 15*mm, 17*mm])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.grey),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 10))

    # Totals
    elements.append(Paragraph(f"<b>Subtotal:</b> KES {sale.subtotal:,.2f}", right_style))
    if sale.discount > 0:
        elements.append(Paragraph(f"<b>Discount:</b> -KES {sale.discount:,.2f}", right_style))
    elements.append(Paragraph(f"<b>TOTAL: KES {sale.total_amount:,.2f}</b>", right_style))
    
    elements.append(Spacer(1, 5))
    elements.append(Paragraph(f"<b>Payment:</b> {sale.payment_method.upper()}", normal_style))
    if sale.mpesa_ref:
        elements.append(Paragraph(f"<b>Ref:</b> {sale.mpesa_ref}", normal_style))

    elements.append(Spacer(1, 15))
    elements.append(Paragraph("Thank you for shopping with us!", ParagraphStyle('Center', parent=normal_style, alignment=TA_CENTER)))
    elements.append(Paragraph("Goods once sold are not returnable.", ParagraphStyle('CenterSmall', parent=subtitle_style, fontSize=6)))

    doc.build(elements)
    buffer.seek(0)
    return buffer
