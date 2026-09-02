import sampleAnalyses from "@/lib/sample-analyses.json"

export const REPO_URL = "https://github.com/yashvisal/inbound-sdr-copilot"

export const QUESTIONS = [
  {
    question: "Who do I prioritize?",
    answer:
      "Inbound leads arrive in whatever order the form sends them. Every one gets scored on the same 100-point rubric, so the queue is ranked by opportunity instead of arrival time.",
  },
  {
    question: "Why is this lead worth my time?",
    answer:
      "A number alone isn't an argument. Every score comes with its reasons: the market signals, the company evidence and the property classification, each traced back to the source it came from.",
  },
  {
    question: "What do I say?",
    answer:
      "The first email is written from the verified enrichment: the market insight, what the company actually operates, the property context. Facts a rep can stand behind, not filler.",
  },
]

export const CATEGORIES = [
  {
    key: "location",
    title: "Location Fit",
    points: 45,
    summary:
      "Leasing demand where the property actually sits: renter share, income, vacancy and transit access at the block-group level, on top of city population, rent and growth.",
    sources: ["Census ACS", "Census Geocoder"],
  },
  {
    key: "company",
    title: "Company Fit",
    points: 39,
    summary:
      "Whether this is a buyer at all: leasing volume, operational complexity and product fit, read from website metadata and search evidence.",
    sources: ["Company website", "Parallel search"],
  },
  {
    key: "property",
    title: "Property Fit",
    points: 16,
    summary:
      "Whether the submitted address is a residential leasing asset, using OSM property type plus search results filtered to that exact building.",
    sources: ["OSM / Nominatim", "Parallel search"],
  },
]

export const PIPELINE = [
  {
    title: "Enrich",
    body: "Resolve the address to census geography, then pull market data, company website metadata and address-matched search results.",
  },
  {
    title: "Extract",
    body: "The model reads that evidence and sorts it into buckets, like “leasing volume: High”, citing the snippet each one came from.",
  },
  {
    title: "Score",
    body: "Buckets map to points against a fixed rubric. Caps apply for weak product fit and unit counts are calibrated in code.",
  },
  {
    title: "Draft",
    body: "Sales insights and a personalized email, written only from verified enrichment and the score reasoning.",
  },
]

export const GUARDRAILS = [
  {
    title: "Deterministic score",
    body: "The same evidence always produces the same number. The model never sees the rubric, so it can't game it.",
  },
  {
    title: "Citations are checked",
    body: "Every bucket must point at a snippet that exists in the evidence packet. Unsupported claims are dropped.",
  },
  {
    title: "Rule-based fallback",
    body: "If the model is unavailable or returns malformed JSON, a rule classifier takes over and the run still completes.",
  },
]

export interface SampleLead {
  id: string
  name: string
  company: string
  address: string
  city: string
  score: number
  priority: string
  location: number
  companyFit: number
  property: number
}

export const SAMPLE_LEADS: SampleLead[] = sampleAnalyses.leads.map((entry) => ({
  id: `${entry.lead.company}-${entry.lead.address}`,
  name: entry.lead.name,
  company: entry.lead.company,
  address: entry.lead.address,
  city: `${entry.lead.city}, ${entry.lead.state}`,
  score: entry.score.final_score,
  priority: entry.score.priority,
  location: entry.score.market_fit.score,
  companyFit: entry.score.company_fit.score,
  property: entry.score.property_fit.score,
}))
