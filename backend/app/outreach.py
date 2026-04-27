from app.models import LeadAnalysis, LeadInput, ScoreBreakdown


FOLLOW_UPS = [
    "Day 0: Send initial personalized outreach.",
    "Day 2: Follow up with a concise value prop tied to leasing responsiveness.",
    "Day 5: Follow up with an operational pain point around resident communication.",
]


def build_sales_insights(score: ScoreBreakdown) -> list[str]:
    insights = [
        *score.market_fit.reasons[:2],
        *score.company_fit.reasons[:2],
        *score.property_fit.reasons[:1],
    ]
    if score.timing.score >= 4:
        insights.extend(score.timing.reasons[:1])
    return insights[:5]


def build_outreach_email(lead: LeadInput, score: ScoreBreakdown) -> str:
    market_reason = score.market_fit.reasons[0] if score.market_fit.reasons else "your market appears relevant for leasing demand"
    company_reason = score.company_fit.reasons[0] if score.company_fit.reasons else "your team appears relevant to property operations"
    property_reason = score.property_fit.reasons[0] if score.property_fit.reasons else "the submitted property appears relevant"

    return (
        f"Hi {lead.name},\n\n"
        f"I noticed {lead.company} and wanted to reach out because {market_reason.lower()} "
        f"{company_reason.lower()}, and {property_reason.lower()}\n\n"
        "EliseAI helps property management teams respond faster to leasing inquiries, "
        "automate resident communication, and reduce manual follow-up work for onsite teams.\n\n"
        "Would it be worth a quick conversation to compare how your team handles inbound "
        "leasing and resident messages today?\n\n"
        "Best,\n"
        "SDR Team"
    )


def attach_sales_outputs(analysis: LeadAnalysis) -> LeadAnalysis:
    analysis.sales_insights = build_sales_insights(analysis.score)
    analysis.why_this_lead = analysis.sales_insights[:3]
    analysis.why_now = analysis.score.timing.reasons[0] if analysis.score.timing.score >= 4 else None
    analysis.outreach_email = build_outreach_email(analysis.lead, analysis.score)
    analysis.follow_ups = FOLLOW_UPS
    return analysis
