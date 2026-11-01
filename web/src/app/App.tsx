import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  AlertCircle,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  FileSearch,
  Github,
  Globe,
  Loader2,
  Network,
  Search,
  Shield,
  Sparkles,
  User,
} from "lucide-react";
import octopusImg from "@/imports/octopus.png";

type SearchState = "idle" | "scanning" | "results" | "error";
type EntityType = "person" | "company" | "other";

interface ApiNode {
  [key: string]: unknown;
}

interface SearchResponse {
  intake: {
    target_name: string;
    aliases: string[];
    entity_type: EntityType;
    purpose: string;
    known_info: string[];
    search_scope: string[];
    constraints?: string | null;
  };
  node_count: number;
  edge_count: number;
  graph: {
    nodes: ApiNode[];
    edges: Array<Record<string, unknown>>;
  };
  partial_results: boolean;
  warnings: string[];
  rate_limit_hits: number;
}

interface InsightItem {
  id: string;
  label: string;
  detail: string;
}

interface InsightGroup {
  id: string;
  title: string;
  subtitle: string;
  position: string;
  accent: string;
  items: InsightItem[];
}

const ENTITY_OPTIONS: Array<{ value: EntityType; label: string; icon: typeof User }> = [
  { value: "person", label: "Person", icon: User },
  { value: "company", label: "Company", icon: Building2 },
  { value: "other", label: "Other", icon: Globe },
];

const SEARCH_SCOPES = [
  { id: "github", label: "GitHub" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "wikipedia", label: "Wikipedia" },
  { id: "general_web", label: "General Web" },
];

const FALLBACK_GROUPS: InsightGroup[] = [
  {
    id: "people",
    title: "People & Profiles",
    subtitle: "Identity surface",
    position: "left-0 top-8",
    accent: "from-cyan-400/30 to-sky-400/10",
    items: [
      { id: "p1", label: "Lead profile", detail: "Primary identity and role mapping" },
      { id: "p2", label: "Public traces", detail: "LinkedIn, handle and authorship clues" },
    ],
  },
  {
    id: "company",
    title: "Corporations & Data",
    subtitle: "Business signal",
    position: "right-0 top-8",
    accent: "from-emerald-400/30 to-cyan-400/10",
    items: [
      { id: "c1", label: "Org footprint", detail: "Legal entity, domain and office references" },
      { id: "c2", label: "Market context", detail: "Open-source company and project indicators" },
    ],
  },
  {
    id: "code",
    title: "Code & Repos",
    subtitle: "Technical surface",
    position: "left-4 bottom-10",
    accent: "from-sky-400/30 to-indigo-400/10",
    items: [
      { id: "r1", label: "Repository activity", detail: "Commits, packages and engineering topics" },
      { id: "r2", label: "Stack hints", detail: "Languages, frameworks and tooling patterns" },
    ],
  },
  {
    id: "evidence",
    title: "Evidence & Logs",
    subtitle: "Supporting material",
    position: "right-4 bottom-10",
    accent: "from-cyan-300/30 to-teal-400/10",
    items: [
      { id: "e1", label: "Evidence bundle", detail: "Documents, pages and archived references" },
      { id: "e2", label: "Graph links", detail: "Relationships and corroborating connections" },
    ],
  },
];

function parseLines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function readString(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function normalizeNode(node: ApiNode, index: number) {
  const label = readString(node.label ?? node.name ?? node.title ?? node.id, `Node ${index + 1}`);
  const detail = readString(
    node.description ?? node.summary ?? node.url ?? node.kind ?? node.source,
    "Open-source signal"
  );
  const type = readString(node.type ?? node.kind ?? node.category, "entity").toLowerCase();

  return {
    id: String(node.id ?? `${type}-${index}`),
    label,
    detail,
    type,
    raw: node,
  };
}

function classifyNode(type: string, text: string) {
  const value = `${type} ${text}`.toLowerCase();
  if (/(person|profile|linkedin|author|researcher|engineer|founder|user)/.test(value)) {
    return "people";
  }
  if (/(company|org|organization|domain|corp|business|firm)/.test(value)) {
    return "company";
  }
  if (/(repo|github|code|package|library|commit|project|stack)/.test(value)) {
    return "code";
  }
  return "evidence";
}

function buildInsightGroups(nodes: ReturnType<typeof normalizeNode>[]) {
  const grouped = {
    people: [] as InsightItem[],
    company: [] as InsightItem[],
    code: [] as InsightItem[],
    evidence: [] as InsightItem[],
  };

  nodes.forEach((node) => {
    const bucket = classifyNode(node.type, `${node.label} ${node.detail}`);
    grouped[bucket].push({
      id: node.id,
      label: node.label,
      detail: node.detail,
    });
  });

  return FALLBACK_GROUPS.map((group) => ({
    ...group,
    items: grouped[group.id as keyof typeof grouped].slice(0, 2).length
      ? grouped[group.id as keyof typeof grouped].slice(0, 2)
      : group.items,
  }));
}

function statusLabel(searchState: SearchState, result: SearchResponse | null) {
  if (searchState === "results" && result?.partial_results) return "Partial results synchronized";
  if (searchState === "results") return "Results synchronized";
  if (searchState === "scanning") return "Backend scan in progress";
  if (searchState === "error") return "Request failed";
  return "System ready";
}

function statusColor(searchState: SearchState, result: SearchResponse | null) {
  if (searchState === "results" && result?.partial_results) return "text-amber-300";
  if (searchState === "results") return "text-emerald-300";
  if (searchState === "scanning") return "text-cyan-300";
  if (searchState === "error") return "text-rose-300";
  return "text-slate-300";
}

function InsightCard({ group }: { group: InsightGroup }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45 }}
      className={`absolute ${group.position} hidden w-72 rounded-[28px] border border-white/10 bg-slate-950/72 p-4 shadow-[0_24px_80px_rgba(0,0,0,0.45)] backdrop-blur-xl xl:block`}
    >
      <div className={`absolute inset-0 rounded-[28px] bg-gradient-to-br ${group.accent} opacity-70`} />
      <div className="relative">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/70">{group.subtitle}</p>
            <h3 className="mt-1 text-sm font-semibold text-white">{group.title}</h3>
          </div>
          <div className="rounded-full border border-white/10 bg-white/5 p-2 text-cyan-300">
            <ArrowUpRight className="h-4 w-4" />
          </div>
        </div>

        <div className="space-y-3">
          {group.items.map((item) => (
            <div key={item.id} className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3">
              <p className="text-sm font-medium text-white">{item.label}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">{item.detail}</p>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

export default function App() {
  const [query, setQuery] = useState("");
  const [purpose, setPurpose] = useState("");
  const [entityType, setEntityType] = useState<EntityType>("person");
  const [knownInfo, setKnownInfo] = useState("");
  const [aliases, setAliases] = useState("");
  const [constraints, setConstraints] = useState("");
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["github", "general_web"]);
  const [searchState, setSearchState] = useState<SearchState>("idle");
  const [scanProgress, setScanProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);

  useEffect(() => {
    if (searchState !== "scanning") return;
    const timer = window.setInterval(() => {
      setScanProgress((current) => (current >= 92 ? current : current + 3));
    }, 180);
    return () => window.clearInterval(timer);
  }, [searchState]);

  const normalizedNodes = useMemo(() => {
    if (!result) return [];
    return result.graph.nodes.slice(0, 8).map((node, index) => normalizeNode(node, index));
  }, [result]);

  const insightGroups = useMemo(() => buildInsightGroups(normalizedNodes), [normalizedNodes]);

  const summaryStats = useMemo(() => {
    if (!result) {
      return [
        { label: "Nodes", value: "--" },
        { label: "Edges", value: "--" },
        { label: "Sources", value: String(selectedScopes.length) },
      ];
    }

    return [
      { label: "Nodes", value: String(result.node_count) },
      { label: "Edges", value: String(result.edge_count) },
      { label: "Sources", value: String(result.intake.search_scope.length || 1) },
    ];
  }, [result, selectedScopes.length]);

  async function startSearch() {
    if (!query.trim() || !purpose.trim()) {
      setSearchState("error");
      setErrorMessage("Target and purpose are required.");
      return;
    }

    setSearchState("scanning");
    setScanProgress(8);
    setErrorMessage("");
    setResult(null);

    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_name: query.trim(),
          aliases: parseLines(aliases),
          entity_type: entityType,
          purpose: purpose.trim(),
          known_info: parseLines(knownInfo),
          search_scope: selectedScopes,
          constraints: constraints.trim() || null,
        }),
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}.`);
      }

      const payload = (await response.json()) as SearchResponse;
      setResult(payload);
      setScanProgress(100);
      setSearchState("results");
    } catch (error) {
      setSearchState("error");
      setScanProgress(0);
      setErrorMessage(error instanceof Error ? error.message : "Request failed.");
    }
  }

  function resetSearch() {
    setSearchState("idle");
    setScanProgress(0);
    setErrorMessage("");
    setResult(null);
  }

  function toggleScope(scopeId: string) {
    setSelectedScopes((current) =>
      current.includes(scopeId)
        ? current.filter((item) => item !== scopeId)
        : [...current, scopeId]
    );
  }

  return (
    <div
      className="relative min-h-screen w-screen overflow-hidden bg-[#020813] text-white"
      style={{ fontFamily: "'Space Grotesk', sans-serif" }}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(45,212,191,0.16),transparent_22%),radial-gradient(circle_at_80%_20%,rgba(14,165,233,0.16),transparent_24%),radial-gradient(circle_at_50%_65%,rgba(11,22,41,0.92),transparent_42%),linear-gradient(135deg,#020813_0%,#041221_45%,#06192a_100%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(125,211,252,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(125,211,252,0.08)_1px,transparent_1px)] [background-size:64px_64px]" />

      <section className="relative z-10 grid min-h-screen w-full grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)_340px]">
        <aside className="border-b border-white/10 bg-slate-950/70 backdrop-blur-2xl xl:border-r xl:border-b-0">
          <div className="flex h-full flex-col px-6 py-6">
            <div className="mb-8 flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-300/30 bg-cyan-400/10">
                <img
                  src={octopusImg}
                  alt="Octopus"
                  className="h-11 w-11 object-contain"
                  style={{ filter: "drop-shadow(0 0 18px rgba(45,212,191,0.5))" }}
                />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.32em] text-cyan-200/70">Octopus Intelligence</p>
                <h1 className="text-2xl font-semibold tracking-tight">
                  Research <span className="text-cyan-300">Console</span>
                </h1>
              </div>
            </div>

            <div className="mb-8 grid grid-cols-3 gap-2">
              {summaryStats.map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/8 bg-white/5 p-3">
                  <p className="text-[10px] uppercase tracking-[0.24em] text-slate-400">{item.label}</p>
                  <p className="mt-2 text-lg font-semibold text-white">{item.value}</p>
                </div>
              ))}
            </div>

            <div className="space-y-4">
              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Target</span>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && startSearch()}
                    placeholder="Person, company, domain"
                    className="h-13 w-full rounded-2xl border border-white/10 bg-slate-900/75 pl-11 pr-4 text-sm text-white outline-none transition focus:border-cyan-300/60"
                  />
                </div>
              </label>

              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Purpose</span>
                <textarea
                  value={purpose}
                  onChange={(event) => setPurpose(event.target.value)}
                  placeholder="Candidate review, company due diligence, threat research"
                  className="min-h-28 w-full rounded-2xl border border-white/10 bg-slate-900/75 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-300/60"
                />
              </label>

              <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Entity Type</span>
                  <div className="grid grid-cols-3 gap-2">
                    {ENTITY_OPTIONS.map(({ value, label, icon: Icon }) => {
                      const active = entityType === value;
                      return (
                        <button
                          key={value}
                          type="button"
                          onClick={() => setEntityType(value)}
                          className={`rounded-2xl border px-3 py-3 text-left transition ${
                            active
                              ? "border-cyan-300/60 bg-cyan-300/12 text-white"
                              : "border-white/10 bg-white/5 text-slate-400"
                          }`}
                        >
                          <Icon className="mb-2 h-4 w-4" />
                          <span className="text-xs">{label}</span>
                        </button>
                      );
                    })}
                  </div>
                </label>

                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Known Info</span>
                  <textarea
                    value={knownInfo}
                    onChange={(event) => setKnownInfo(event.target.value)}
                    placeholder="One fact per line"
                    className="min-h-24 w-full rounded-2xl border border-white/10 bg-slate-900/75 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-300/60"
                  />
                </label>
              </div>

              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Aliases</span>
                <textarea
                  value={aliases}
                  onChange={(event) => setAliases(event.target.value)}
                  placeholder="One alias per line"
                  className="min-h-24 w-full rounded-2xl border border-white/10 bg-slate-900/75 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-300/60"
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Scope</span>
                <div className="grid grid-cols-2 gap-2">
                  {SEARCH_SCOPES.map((scope) => {
                    const active = selectedScopes.includes(scope.id);
                    return (
                      <button
                        key={scope.id}
                        type="button"
                        onClick={() => toggleScope(scope.id)}
                        className={`rounded-2xl border px-4 py-3 text-sm transition ${
                          active
                            ? "border-cyan-300/55 bg-cyan-300/10 text-white"
                            : "border-white/10 bg-white/5 text-slate-400"
                        }`}
                      >
                        {scope.label}
                      </button>
                    );
                  })}
                </div>
              </label>

              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[0.24em] text-slate-400">Constraints</span>
                <textarea
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value)}
                  placeholder="Date, geography, public-only, language filters"
                  className="min-h-24 w-full rounded-2xl border border-white/10 bg-slate-900/75 px-4 py-3 text-sm text-white outline-none transition focus:border-cyan-300/60"
                />
              </label>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={startSearch}
                disabled={searchState === "scanning"}
                className="flex h-13 flex-1 items-center justify-center gap-2 rounded-2xl bg-cyan-300 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300"
              >
                {searchState === "scanning" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
                {searchState === "scanning" ? `Scanning ${scanProgress}%` : "Start Research"}
              </button>
              <button
                type="button"
                onClick={resetSearch}
                className="h-13 rounded-2xl border border-white/10 bg-white/5 px-5 text-sm text-slate-200 transition hover:bg-white/10"
              >
                Reset
              </button>
            </div>
          </div>
        </aside>

        <main className="relative overflow-hidden">
          <div className="absolute left-6 right-6 top-6 z-20 flex flex-wrap items-center justify-between gap-4 rounded-[28px] border border-white/10 bg-slate-950/55 px-5 py-4 backdrop-blur-xl">
            <div>
              <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Live Pipeline</p>
              <div className="mt-2 flex items-center gap-3">
                <span className={`text-sm font-medium ${statusColor(searchState, result)}`}>{statusLabel(searchState, result)}</span>
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">
                  {query.trim() || "Awaiting target"}
                </span>
                {result?.partial_results && (
                  <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-3 py-1 text-xs text-amber-200">
                    Partial Results
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right">
                <p className="text-[10px] uppercase tracking-[0.24em] text-slate-500">Stack</p>
                <p className="mt-1 text-sm font-semibold text-white">FastAPI + React</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right">
                <p className="text-[10px] uppercase tracking-[0.24em] text-slate-500">Viewport</p>
                <p className="mt-1 text-sm font-semibold text-white">Full Screen</p>
              </div>
            </div>
          </div>

          <div className="relative flex min-h-[720px] h-full items-center justify-center px-6 py-28">
            {insightGroups.map((group) => (
              <InsightCard key={group.id} group={group} />
            ))}

            <div className="relative flex h-[620px] w-full max-w-[920px] items-center justify-center">
              <div className="absolute h-[420px] w-[420px] rounded-full bg-cyan-300/12 blur-[120px]" />
              <div className="absolute h-[540px] w-[540px] rounded-full border border-cyan-300/10" />
              <motion.div
                className="absolute h-[620px] w-[620px] rounded-full border border-cyan-300/10"
                animate={{ rotate: 360 }}
                transition={{ duration: 38, repeat: Infinity, ease: "linear" }}
              />
              <motion.div
                className="absolute h-[500px] w-[500px] rounded-full border border-cyan-200/10"
                animate={{ rotate: -360 }}
                transition={{ duration: 26, repeat: Infinity, ease: "linear" }}
              />

              <div className="pointer-events-none absolute inset-x-0 top-[20%] hidden xl:block">
                <div className="mx-auto h-px w-[68%] bg-gradient-to-r from-transparent via-cyan-300/25 to-transparent" />
              </div>
              <div className="pointer-events-none absolute inset-y-0 left-[18%] hidden xl:block">
                <div className="h-full w-px bg-gradient-to-b from-transparent via-cyan-300/18 to-transparent" />
              </div>
              <div className="pointer-events-none absolute inset-y-0 right-[18%] hidden xl:block">
                <div className="h-full w-px bg-gradient-to-b from-transparent via-cyan-300/18 to-transparent" />
              </div>

              <motion.div
                animate={searchState === "scanning" ? { scale: [1, 1.04, 1] } : { y: [0, -8, 0] }}
                transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
                className="relative z-10 flex h-[360px] w-[360px] items-center justify-center rounded-full"
              >
                <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(45,212,191,0.2),transparent_58%)] blur-3xl" />
                <img
                  src={octopusImg}
                  alt="Octopus intelligence visual"
                  className="relative z-10 h-full w-full object-contain"
                  style={{ filter: "drop-shadow(0 0 32px rgba(45,212,191,0.45))" }}
                />
              </motion.div>

              <div className="absolute bottom-10 left-1/2 z-10 w-full max-w-md -translate-x-1/2 rounded-[28px] border border-white/10 bg-slate-950/65 p-5 text-center backdrop-blur-xl">
                <p className="text-[10px] uppercase tracking-[0.3em] text-cyan-200/70">Central Research Surface</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  {result?.intake.target_name || "Octopus Intelligence"}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  {result?.intake.purpose ||
                    "A cleaner central scene with structured intelligence cards around the octopus visual."}
                </p>
              </div>
            </div>
          </div>

          <div className="absolute bottom-6 left-6 z-20 rounded-2xl border border-white/10 bg-slate-950/55 px-4 py-3 text-xs text-slate-300 backdrop-blur-xl">
            <div className="mb-2 flex items-center gap-2 text-cyan-300">
              <Shield className="h-4 w-4" />
              Professional scene mode
            </div>
            <p className="max-w-xs leading-5 text-slate-400">
              The center visual now uses the cleaned octopus art with surrounding intelligence panels inspired by your reference.
            </p>
          </div>
        </main>

        <aside className="border-t border-white/10 bg-slate-950/70 backdrop-blur-2xl xl:border-l xl:border-t-0">
          <div className="flex h-full flex-col px-6 py-6">
            <div className="mb-6 flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Results Feed</p>
                <h2 className="mt-1 text-xl font-semibold text-white">Backend output</h2>
              </div>
              <Sparkles className="h-5 w-5 text-cyan-300" />
            </div>

            <div className="space-y-4">
              <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                <div className="mb-3 flex items-center gap-3">
                  <Network className="h-5 w-5 text-cyan-300" />
                  <span className="text-sm font-medium text-white">Status</span>
                </div>
                <p className="text-sm leading-6 text-slate-300">
                  {searchState === "results" && result
                    ? result.partial_results
                      ? `${result.intake.target_name} returned partial graph data because some model calls hit rate limits.`
                      : `${result.intake.target_name} synchronized with the search graph.`
                    : searchState === "scanning"
                      ? "The request is being processed by the FastAPI backend."
                      : searchState === "error"
                        ? errorMessage
                        : "Fill the form and start the research run."}
                </p>
              </div>

              <AnimatePresence mode="wait">
                {searchState === "error" && (
                  <motion.div
                    key="error"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="rounded-[28px] border border-rose-400/30 bg-rose-400/10 p-5"
                  >
                    <div className="mb-3 flex items-center gap-2 text-rose-200">
                      <AlertCircle className="h-4 w-4" />
                      Error
                    </div>
                    <p className="text-sm leading-6 text-rose-100">{errorMessage}</p>
                  </motion.div>
                )}

                {searchState === "results" && result && (
                  <motion.div
                    key="result"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="space-y-4"
                  >
                    <div className={`rounded-[28px] p-5 ${result.partial_results ? "border border-amber-300/25 bg-amber-300/10" : "border border-emerald-300/20 bg-emerald-300/8"}`}>
                      <div className={`mb-3 flex items-center gap-2 ${result.partial_results ? "text-amber-200" : "text-emerald-200"}`}>
                        <CheckCircle2 className="h-4 w-4" />
                        {result.partial_results ? "Partial results returned" : "API connected"}
                      </div>
                      <p className={`text-sm leading-6 ${result.partial_results ? "text-amber-50/90" : "text-emerald-50/90"}`}>
                        {result.node_count} nodes and {result.edge_count} edges returned for {result.intake.target_name}.
                      </p>
                      {result.warnings.length > 0 && (
                        <p className="mt-3 text-xs leading-5 text-slate-300">
                          {result.warnings[0]}
                        </p>
                      )}
                    </div>

                    <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                      <p className="mb-4 text-xs uppercase tracking-[0.24em] text-slate-400">Structured Input</p>
                      <div className="space-y-3 text-sm text-slate-300">
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-slate-500">Target</span>
                          <span className="text-right text-white">{result.intake.target_name}</span>
                        </div>
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-slate-500">Purpose</span>
                          <span className="max-w-[200px] text-right text-white">{result.intake.purpose}</span>
                        </div>
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-slate-500">Scope</span>
                          <span className="text-right text-white">{result.intake.search_scope.join(", ") || "-"}</span>
                        </div>
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-slate-500">Entity</span>
                          <span className="text-right text-white">{result.intake.entity_type}</span>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                      <div className="mb-4 flex items-center justify-between">
                        <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Source Preview</p>
                        <Github className="h-4 w-4 text-slate-500" />
                      </div>
                      <div className="space-y-3">
                        {normalizedNodes.length > 0 ? (
                          normalizedNodes.slice(0, 4).map((node) => (
                            <div key={node.id} className="rounded-2xl border border-white/8 bg-slate-900/70 p-4">
                              <p className="text-sm font-semibold text-white">{node.label}</p>
                              <p className="mt-1 text-xs uppercase tracking-[0.22em] text-cyan-200/70">{node.type}</p>
                              <p className="mt-2 text-sm leading-6 text-slate-400">{node.detail}</p>
                            </div>
                          ))
                        ) : (
                          <p className="text-sm leading-6 text-slate-400">
                            No graph nodes were returned for this request.
                          </p>
                        )}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}
