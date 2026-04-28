import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const sampleLeads = [
  {
    company: "Harbor Residential",
    contact: "Maya Chen",
    location: "Austin, TX",
    score: 88,
    priority: "High",
    reason: "Strong property management fit in a growing rental market.",
  },
  {
    company: "Northline Communities",
    contact: "Evan Brooks",
    location: "Charlotte, NC",
    score: 72,
    priority: "Medium",
    reason: "Relevant operator, but submitted property fit is less certain.",
  },
  {
    company: "Summit Dental Group",
    contact: "Priya Shah",
    location: "Denver, CO",
    score: 42,
    priority: "Low",
    reason: "Strong market, but company appears outside the property ICP.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-background">
      <section className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-6 py-10 lg:px-8">
        <div className="flex flex-col gap-4">
          <Badge className="w-fit" variant="secondary">
            EliseAI GTM Engineer Assessment
          </Badge>
          <div className="grid gap-4 lg:grid-cols-[1.3fr_0.7fr] lg:items-end">
            <div className="space-y-4">
              <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-foreground md:text-6xl">
                Inbound SDR Copilot for lead enrichment and scoring.
              </h1>
              <p className="max-w-3xl text-lg text-muted-foreground">
                A FastAPI and Next.js MVP that turns raw inbound leads into ranked,
                explainable, outreach-ready opportunities for property management SDRs.
              </p>
            </div>
            <Card>
              <CardHeader>
                <CardTitle>Scoring Model</CardTitle>
                <CardDescription>Deterministic rubric, source-backed reasons.</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-2xl font-semibold">45</p>
                  <p className="text-xs text-muted-foreground">Market Fit</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold">39</p>
                  <p className="text-xs text-muted-foreground">Company Fit</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold">16</p>
                  <p className="text-xs text-muted-foreground">Property Fit</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
          <Card>
            <CardHeader>
              <CardTitle>Lead Intake</CardTitle>
              <CardDescription>Upload a CSV or run sample leads through the analysis trigger.</CardDescription>
              <CardAction>
                <Badge variant="outline">MVP Trigger</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="csv-upload">
                  Lead CSV
                </label>
                <Input id="csv-upload" type="file" accept=".csv" />
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button className="flex-1">Run Analysis</Button>
                <Button className="flex-1" variant="outline">
                  Load Sample Data
                </Button>
              </div>
              <Separator />
              <p className="text-sm text-muted-foreground">
                Required columns: name, email, company, address, city, state, country.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Priority Queue Preview</CardTitle>
              <CardDescription>
                Sample output shape for scored and outreach-ready leads.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Company</TableHead>
                    <TableHead>Location</TableHead>
                    <TableHead>Score</TableHead>
                    <TableHead>Priority</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sampleLeads.map((lead) => (
                    <TableRow key={lead.company}>
                      <TableCell>
                        <div className="font-medium">{lead.company}</div>
                        <div className="text-sm text-muted-foreground">{lead.contact}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{lead.reason}</div>
                      </TableCell>
                      <TableCell>{lead.location}</TableCell>
                      <TableCell className="font-semibold">{lead.score}</TableCell>
                      <TableCell>
                        <Badge variant={lead.priority === "High" ? "default" : "secondary"}>
                          {lead.priority}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
